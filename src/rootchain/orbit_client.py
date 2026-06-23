"""Async Orbit REST API client with retries, caching, and multi-strategy MR discovery.

Queries the Orbit JSON DSL at POST /api/v4/orbit/query. All filter values are passed
as typed parameters — never string-interpolated — to avoid injection and Orbit's
strict filter-key validation.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Config
from .models import (
    Err,
    LinkedIssue,
    MRContext,
    Ok,
    Result,
    StackFrame,
    SymbolHistory,
    VulnerabilityFinding,
)

log = structlog.get_logger()




def _parse_merged_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    except (ValueError, AttributeError):
        return None


def _days_since(dt: datetime | None) -> int:
    if dt is None:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (datetime.now(UTC) - dt).days


def _node_str(node: dict, *keys: str, default: str = "") -> str:
    """Extract first matching key from a flat Orbit response node."""
    for key in keys:
        val = node.get(key)
        if val is not None:
            return str(val)
    return default


def _filter_merged_mrs(nodes: list[dict]) -> list[dict]:
    """Extract merged MergeRequest nodes from a flat node list, sorted by merge date desc.

    Orbit traversal may omit merged_at — accept state='merged' as the fallback indicator.
    """
    mrs = [
        n for n in nodes
        if n.get("type") == "MergeRequest"
        and (n.get("merged_at") or n.get("state") == "merged")
    ]
    return sorted(mrs, key=lambda n: n.get("merged_at") or "2020-01-01", reverse=True)


def _dedup_mrs(mrs: list[dict]) -> list[dict]:
    """Deduplicate by iid, preserving order (highest-confidence first)."""
    seen: set[int] = set()
    result: list[dict] = []
    for mr in mrs:
        iid = int(mr.get("iid", 0))
        if iid and iid not in seen:
            seen.add(iid)
            result.append(mr)
    return result


def _extract_mr_enrichment(
    neighbors: list[dict],
    project_url: str = "",
) -> tuple[list[LinkedIssue], list[str], str | None]:
    """Parse WorkItem, User, and Pipeline nodes from a MergeRequest neighbors response."""
    linked: list[LinkedIssue] = []
    reviewers: list[str] = []
    pipeline_status: str | None = None
    latest_pipeline_time = ""

    for node in neighbors:
        node_type = node.get("type")

        if node_type == "WorkItem":
            try:
                iid = int(node.get("iid", 0))
            except (ValueError, TypeError):
                continue
            if iid > 0:
                wi_url = _node_str(node, "web_url", "url")
                if not wi_url and project_url:
                    wi_url = f"{project_url}/-/issues/{iid}"
                linked.append(LinkedIssue(
                    iid=iid,
                    title=_node_str(node, "title"),
                    web_url=wi_url,
                    state=_node_str(node, "state", default="unknown"),
                ))

        elif node_type == "User":
            username = node.get("username", "")
            if username:
                reviewers.append(str(username))

        elif node_type == "Pipeline":
            created_at = node.get("created_at", "")
            if node.get("status") and created_at >= latest_pipeline_time:
                latest_pipeline_time = created_at
                pipeline_status = str(node.get("status"))

    return linked, reviewers, pipeline_status




class OrbitClient:
    """Async client for GitLab Orbit graph queries (JSON DSL)."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.gitlab_url,
            headers={
                "PRIVATE-TOKEN": config.gitlab_token,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(config.orbit_timeout_seconds),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        self._cache: dict[tuple[str, str], SymbolHistory] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> OrbitClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


    async def get_symbol_histories(
        self, frames: list[StackFrame]
    ) -> list[SymbolHistory]:
        """Query Orbit for all frames in parallel. Never raises — orbit_miss on failure."""
        tasks = [self._get_symbol_history_cached(f) for f in frames]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        histories: list[SymbolHistory] = []
        for frame, result in zip(frames, results, strict=True):
            if isinstance(result, Exception):
                log.error(
                    "symbol_history_exception",
                    function_name=frame.function_name,
                    file_path=frame.file_path,
                    exc=str(result),
                )
                histories.append(self._orbit_miss(frame))
            else:
                histories.append(result)  # type: ignore[arg-type]
        return histories


    async def _get_symbol_history_cached(self, frame: StackFrame) -> SymbolHistory:
        cache_key = (frame.function_name, frame.file_path)
        if cache_key in self._cache:
            log.debug("orbit_cache_hit", function_name=frame.function_name)
            return self._cache[cache_key]

        history = await self._get_symbol_history(frame)
        self._cache[cache_key] = history
        return history

    async def _get_symbol_history(self, frame: StackFrame) -> SymbolHistory:
        log_ = log.bind(function_name=frame.function_name, file_path=frame.file_path)

        mr_nodes, fallback_used = await self._find_mrs_for_file(frame.file_path)

        if not mr_nodes:
            log_.info("orbit_miss")
            return self._orbit_miss(frame)

        caller_count, security_findings = await asyncio.gather(
            self._get_caller_count(frame.function_name),
            self._get_security_findings(frame.file_path),
        )

        recent_mrs_raw = await asyncio.gather(
            *[self._enrich_mr(node) for node in mr_nodes],
            return_exceptions=True,
        )

        enriched: list[MRContext] = []
        for item in recent_mrs_raw:
            if isinstance(item, Exception):
                log_.warning("mr_enrichment_failed", exc=str(item))
            else:
                enriched.append(item)  # type: ignore[arg-type]

        log_.info(
            "orbit_query_complete",
            mr_count=len(enriched),
            caller_count=caller_count,
            security_findings=len(security_findings),
        )

        return SymbolHistory(
            function_name=frame.function_name,
            file_path=frame.file_path,
            recent_mrs=enriched,
            caller_count=caller_count,
            orbit_miss=False,
            fallback_used=fallback_used,
            security_findings=security_findings,
        )

    async def _find_mrs_for_file(self, file_path: str) -> tuple[list[dict], bool]:
        """Multi-strategy MR discovery for a file. Returns (mr_nodes, fallback_used)."""
        # Strategy 1: Direct neighbors of File node (if Orbit has File→MR edges)
        mrs = await self._find_mrs_via_diff_traversal(file_path, path_field="old_path")
        if mrs:
            log.debug("orbit_diff_traversal_old_path_hit", file_path=file_path, count=len(mrs))
            return mrs[:3], False

        mrs = await self._find_mrs_via_diff_traversal(file_path, path_field="new_path")
        if mrs:
            log.debug("orbit_diff_traversal_new_path_hit", file_path=file_path, count=len(mrs))
            return mrs[:3], True

        nodes = await self._get_neighbors("File", {"path": file_path})
        mrs = _filter_merged_mrs(nodes)
        if mrs:
            log.debug("orbit_file_direct_hit", file_path=file_path, count=len(mrs))
            return mrs[:3], False

        # Strategy 2: Neighbors of MergeRequestDiffFile (one hop via diff record)
        nodes = await self._get_neighbors("MergeRequestDiffFile", {"new_path": file_path})
        mrs = _filter_merged_mrs(nodes)
        if mrs:
            log.debug("orbit_diff_file_direct_hit", file_path=file_path, count=len(mrs))
            return mrs[:3], False

        # Strategy 3: MergeRequestDiff intermediate hop
        mr_diffs = [n for n in nodes if n.get("type") == "MergeRequestDiff"]
        if mr_diffs:
            all_mrs: list[dict] = []
            for diff in mr_diffs[:3]:
                diff_id = diff.get("id", "")
                if not diff_id:
                    continue
                diff_nodes = await self._get_neighbors("MergeRequestDiff", {"id": diff_id})
                all_mrs.extend(_filter_merged_mrs(diff_nodes))
            if all_mrs:
                log.debug("orbit_diff_two_hop_hit", file_path=file_path)
                return _dedup_mrs(all_mrs)[:3], False

        # Strategy 4: old_path fallback (renamed files)
        nodes = await self._get_neighbors("MergeRequestDiffFile", {"old_path": file_path})
        mrs = _filter_merged_mrs(nodes)
        if mrs:
            log.debug("orbit_old_path_hit", file_path=file_path, count=len(mrs))
            return mrs[:3], True  # fallback_used = True (renamed file path)

        # Strategy 5: GitLab commits API + Orbit enrichment (reliable fallback)
        mrs = await self._find_mrs_via_commits_api(file_path)
        if mrs:
            log.debug("orbit_commits_api_hit", file_path=file_path, count=len(mrs))
            return mrs[:3], False

        log.info("orbit_no_mr_data", file_path=file_path)
        return [], True

    async def _find_mrs_via_diff_traversal(self, file_path: str, path_field: str) -> list[dict]:
        """Find merged MRs that touched a file using current Orbit relationship syntax."""
        nodes = await self._run_with_retry({
            "query": {
                "query_type": "traversal",
                "nodes": [
                    {
                        "id": "project",
                        "entity": "Project",
                        "filters": {"full_path": self._config.project_path},
                        "columns": ["id", "full_path"],
                    },
                    {
                        "id": "mr",
                        "entity": "MergeRequest",
                        "filters": {"state": "merged"},
                        "columns": [
                            "id",
                            "iid",
                            "title",
                            "description",
                            "state",
                            "merged_at",
                            "source_branch",
                            "target_branch",
                        ],
                    },
                    {
                        "id": "snapshot",
                        "entity": "MergeRequestDiff",
                        "columns": ["id"],
                    },
                    {
                        "id": "file",
                        "entity": "MergeRequestDiffFile",
                        "filters": {path_field: file_path},
                        "columns": ["old_path", "new_path"],
                    },
                ],
                "relationships": [
                    {"type": "IN_PROJECT", "from": "mr", "to": "project"},
                    {"type": "HAS_DIFF", "from": "mr", "to": "snapshot"},
                    {"type": "HAS_FILE", "from": "snapshot", "to": "file"},
                ],
                "limit": 25,
            }
        })
        return _dedup_mrs(_filter_merged_mrs(nodes))

    async def _enrich_mr(self, mr_node: dict) -> MRContext:
        """Build MRContext from a flat Orbit MergeRequest node (single enrichment query)."""
        mr_iid = int(mr_node.get("iid", 0))
        merged_at = _parse_merged_at(mr_node.get("merged_at"))
        needs_rest = not all(
            _node_str(mr_node, key)
            for key in ("title", "web_url", "author_username")
        )
        rest_mr = await self._get_merge_request_rest(mr_iid) if needs_rest else {}

        # One neighbors query returns WorkItem, User, and Pipeline nodes together
        neighbors = await self._get_neighbors("MergeRequest", {"iid": mr_iid})
        project_url = f"{self._config.gitlab_url}/{self._config.project_path}"
        linked, reviewers, pipeline_status = _extract_mr_enrichment(neighbors, project_url)
        if not linked:
            linked = await self._get_mr_closing_issues_rest(mr_iid)

        web_url = _node_str(mr_node, "web_url", "url") or str(rest_mr.get("web_url", ""))
        if not web_url and mr_iid:
            web_url = (
                f"{self._config.gitlab_url}/{self._config.project_path}"
                f"/-/merge_requests/{mr_iid}"
            )

        rest_author = rest_mr.get("author")
        author_username = _node_str(mr_node, "author_username", "author")
        if not author_username and isinstance(rest_author, dict):
            author_username = str(rest_author.get("username", ""))

        return MRContext(
            iid=mr_iid,
            title=_node_str(mr_node, "title") or str(rest_mr.get("title", "")),
            description=_node_str(mr_node, "description") or str(rest_mr.get("description", "")),
            author_username=author_username or "unknown",
            merged_at=merged_at,
            web_url=web_url,
            linked_issues=linked,
            reviewers=reviewers,
            days_since_merge=_days_since(merged_at),
            pipeline_status=pipeline_status,
        )

    async def _get_merge_request_rest(self, mr_iid: int) -> dict:
        """Fetch REST MR fields that Orbit traversal can omit."""
        if mr_iid <= 0:
            return {}
        try:
            encoded_project = self._config.project_path.replace("/", "%2F")
            response = await self._client.get(
                f"/api/v4/projects/{encoded_project}/merge_requests/{mr_iid}"
            )
            if response.status_code != 200:
                log.warning(
                    "mr_rest_fetch_failed",
                    mr_iid=mr_iid,
                    status=response.status_code,
                )
                return {}
            body = response.json()
            return body if isinstance(body, dict) else {}
        except httpx.HTTPError as exc:
            log.warning("mr_rest_fetch_exception", mr_iid=mr_iid, exc=str(exc))
            return {}

    async def _get_mr_closing_issues_rest(self, mr_iid: int) -> list[LinkedIssue]:
        """Fetch issues closed by an MR when Orbit does not return WorkItem edges yet."""
        if mr_iid <= 0:
            return []
        try:
            encoded_project = self._config.project_path.replace("/", "%2F")
            response = await self._client.get(
                f"/api/v4/projects/{encoded_project}/merge_requests/{mr_iid}/closes_issues"
            )
            if response.status_code != 200:
                log.warning(
                    "mr_closing_issues_fetch_failed",
                    mr_iid=mr_iid,
                    status=response.status_code,
                )
                return []
            body = response.json()
            if not isinstance(body, list):
                return []

            issues: list[LinkedIssue] = []
            for item in body[:3]:
                if not isinstance(item, dict):
                    continue
                try:
                    iid = int(item.get("iid", 0))
                except (TypeError, ValueError):
                    continue
                if iid <= 0:
                    continue
                issues.append(LinkedIssue(
                    iid=iid,
                    title=str(item.get("title", "")),
                    web_url=str(item.get("web_url", "")),
                    state=str(item.get("state", "unknown")),
                ))
            return issues
        except Exception as exc:
            log.warning("mr_closing_issues_fetch_exception", mr_iid=mr_iid, exc=str(exc))
            return []

    async def _get_caller_count(self, function_name: str) -> int:
        try:
            nodes = await self._get_neighbors("Definition", {"name": function_name})
            return sum(
                1 for n in nodes
                if n.get("type") == "Definition" and n.get("name") != function_name
            )
        except Exception as exc:
            log.warning("caller_count_query_failed", function_name=function_name, exc=str(exc))
            return 0

    async def _get_security_findings(self, file_path: str) -> list[VulnerabilityFinding]:
        try:
            nodes = await self._run_with_retry({
                "query": {
                    "query_type": "traversal",
                    "nodes": [
                        {
                            "id": "project",
                            "entity": "Project",
                            "filters": {"full_path": self._config.project_path},
                            "columns": ["id", "full_path"],
                        },
                        {
                            "id": "v",
                            "entity": "Vulnerability",
                            "filters": {
                                "state": {"op": "in", "value": ["detected", "confirmed"]},
                            },
                            "columns": ["id", "title", "severity", "state", "report_type"],
                        },
                        {
                            "id": "occ",
                            "entity": "VulnerabilityOccurrence",
                            "filters": {"location": {"op": "contains", "value": file_path}},
                            "columns": ["id", "name", "location", "severity", "report_type"],
                        },
                    ],
                    "relationships": [
                        {"type": "IN_PROJECT", "from": "v", "to": "project"},
                        {"type": "OCCURRENCE_OF", "from": "occ", "to": "v"},
                    ],
                    "limit": 3,
                }
            })
            findings: list[VulnerabilityFinding] = []
            for node in nodes:
                if node.get("type") not in ("Vulnerability", "VulnerabilityOccurrence"):
                    continue
                state = _node_str(node, "state", default="detected")
                if state not in ("detected", "confirmed"):
                    continue
                findings.append(VulnerabilityFinding(
                    name=_node_str(node, "name", "title"),
                    severity=_node_str(node, "severity", default="unknown").lower(),
                    state=state,
                    report_type=_node_str(node, "report_type", default="unknown"),
                    web_url=_node_str(node, "web_url", "url"),
                ))
            return findings
        except Exception as exc:
            log.warning("security_query_failed", file_path=file_path, exc=str(exc))
            return []

    async def _find_mrs_via_commits_api(self, file_path: str) -> list[dict]:
        """GitLab REST commits API: file_path → commits → MRs (fallback when Orbit lacks edges)."""
        try:
            encoded_project = self._config.project_path.replace("/", "%2F")
            commits_r = await self._client.get(
                f"/api/v4/projects/{encoded_project}/repository/commits",
                params={"path": file_path, "ref_name": self._config.default_branch, "per_page": 10},
            )
            if commits_r.status_code != 200:
                return []

            rest_mrs: dict[int, dict] = {}  # iid → REST MR payload
            for commit in commits_r.json()[:5]:
                sha = commit.get("id", "")
                if not sha:
                    continue
                mr_r = await self._client.get(
                    f"/api/v4/projects/{encoded_project}/repository/commits/{sha}/merge_requests"
                )
                if mr_r.status_code != 200:
                    continue
                for mr in mr_r.json():
                    iid = int(mr.get("iid", 0))
                    if iid and mr.get("state") == "merged" and iid not in rest_mrs:
                        rest_mrs[iid] = mr

            if not rest_mrs:
                return []

            combined: list[dict] = []
            for iid, rest_mr in rest_mrs.items():
                orbit_nodes = await self._traverse("MergeRequest", {"iid": iid}, limit=1)
                if orbit_nodes:
                    node = orbit_nodes[0].copy()
                else:
                    node = {"type": "MergeRequest", "iid": iid, "state": "merged"}

                # Supplement with REST fields Orbit omits
                node.setdefault("merged_at", rest_mr.get("merged_at", ""))
                node.setdefault("web_url", rest_mr.get("web_url", ""))
                node.setdefault("title", rest_mr.get("title", ""))
                node.setdefault("description", rest_mr.get("description", ""))
                node.setdefault(
                    "author_username",
                    rest_mr.get("author", {}).get("username", ""),
                )
                combined.append(node)

            return sorted(combined, key=lambda n: n.get("merged_at") or "", reverse=True)
        except Exception as exc:
            log.warning("commits_api_fallback_failed", file_path=file_path, exc=str(exc))
            return []


    async def _traverse(
        self, entity: str, filters: dict, limit: int = 10  # type: ignore[type-arg]
    ) -> list[dict]:  # type: ignore[type-arg]
        """Find nodes matching entity + filters (traversal query type)."""
        return await self._run_with_retry({
            "query": {
                "query_type": "traversal",
                "node": {"id": "n", "entity": entity, "filters": filters},
                "limit": limit,
            }
        })

    async def _get_neighbors(
        self, entity: str, filters: dict  # type: ignore[type-arg]
    ) -> list[dict]:  # type: ignore[type-arg]
        """Return all nodes adjacent to the node(s) matching entity + filters."""
        return await self._run_with_retry({
            "query": {
                "query_type": "neighbors",
                "node": {"id": "n", "entity": entity, "filters": filters},
                "neighbors": {"node": "n"},
            }
        })

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        reraise=True,
    )
    async def _run_with_retry(
        self, payload: dict  # type: ignore[type-arg]
    ) -> list[dict]:  # type: ignore[type-arg]
        """Execute an Orbit JSON DSL query payload with retry.

        Sends the payload to ``POST /api/v4/orbit/query`` and returns the flat
        list of node dicts from the ``result.nodes`` field.

        Return values:
        - Empty list on 4xx errors, Orbit error bodies, or empty results.
        - Raises on 5xx or network failures (tenacity retries 3 times).

        The Orbit API contract guarantees ``result`` is always a dict when the
        request succeeds — ``result.get("nodes", [])`` is always safe.
        """
        t0 = time.monotonic()
        response = await self._client.post("/api/v4/orbit/query", json=payload)

        elapsed = int((time.monotonic() - t0) * 1000)
        log.debug("orbit_http_response", status=response.status_code, elapsed_ms=elapsed)

        log.debug("orbit_response_bytes", size=len(response.content))

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "5"))
            log.warning("orbit_rate_limited", retry_after_seconds=retry_after)
            await asyncio.sleep(retry_after)
            raise httpx.NetworkError("Rate limited — retrying")

        if response.status_code >= 500:
            raise httpx.NetworkError(f"Orbit returned {response.status_code}")

        if response.status_code == 400:
            body = response.json()
            log.error(
                "orbit_query_invalid",
                error=body.get("error") or body.get("message"),
                code=body.get("code"),
            )
            return []

        response.raise_for_status()

        body = response.json()
        if "error" in body or ("code" in body and "message" in body):
            log.error(
                "orbit_query_error",
                error=body.get("error") or body.get("message"),
                code=body.get("code"),
            )
            return []

        result = body.get("result") or {}
        if isinstance(result, dict):
            nodes = result.get("nodes", [])
            return nodes if isinstance(nodes, list) else []
        if isinstance(result, list):
            return [
                row for row in result
                if isinstance(row, dict) and row.get("type")
            ]
        return []

    @staticmethod
    def _orbit_miss(frame: StackFrame) -> SymbolHistory:
        return SymbolHistory(
            function_name=frame.function_name,
            file_path=frame.file_path,
            recent_mrs=[],
            caller_count=0,
            orbit_miss=True,
            fallback_used=False,
        )


    async def check_health(self) -> Result[str]:
        """Verify Orbit is reachable and healthy on the configured GitLab instance."""
        try:
            resp = await self._client.get("/api/v4/orbit/status")
            if resp.status_code != 200:
                return Err(
                    message=f"Orbit status endpoint returned HTTP {resp.status_code}",
                    code="orbit_unhealthy",
                    retryable=False,
                )
            data = resp.json()
            user_available = data.get("user", {}).get("available", False)
            system = data.get("system") or {}
            status = system.get("status", "unknown")
            if not user_available or status != "healthy":
                return Err(
                    message=f"Orbit status is '{status}', user_available={user_available}",
                    code="orbit_unhealthy",
                    retryable=False,
                )
            return Ok(value=status)
        except httpx.HTTPError as exc:
            return Err(message=str(exc), code="orbit_unreachable", retryable=True)
