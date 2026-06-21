"""Orbit REST API client — async, with retries, caching, and fallback queries.

Uses the Orbit JSON DSL (POST /api/v4/orbit/query) with query_type values:
traversal, neighbors, aggregation, path_finding.
Never string-interpolates user input into queries.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

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
    Err, LinkedIssue, MRContext, Ok, Result, StackFrame, SymbolHistory, VulnerabilityFinding,
)

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Response normalization helpers
# ---------------------------------------------------------------------------


def _parse_merged_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _days_since(dt: datetime | None) -> int:
    if dt is None:
        return 0
    return (datetime.now(timezone.utc) - dt).days


def _node_str(node: dict, *keys: str, default: str = "") -> str:
    """Extract first matching key from a flat Orbit response node."""
    for key in keys:
        val = node.get(key)
        if val is not None:
            return str(val)
    return default


def _filter_merged_mrs(nodes: list[dict]) -> list[dict]:
    """Extract merged MergeRequest nodes from a flat node list, sorted by merge date desc."""
    mrs = [n for n in nodes if n.get("type") == "MergeRequest" and n.get("merged_at")]
    return sorted(mrs, key=lambda n: n.get("merged_at", ""), reverse=True)


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
                linked.append(LinkedIssue(
                    iid=iid,
                    title=_node_str(node, "title"),
                    web_url=_node_str(node, "web_url", "url"),
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


# ---------------------------------------------------------------------------
# OrbitClient
# ---------------------------------------------------------------------------


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

    async def __aenter__(self) -> "OrbitClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_symbol_histories(
        self, frames: list[StackFrame]
    ) -> list[SymbolHistory]:
        """Query Orbit for all frames in parallel. Never raises — orbit_miss on failure."""
        tasks = [self._get_symbol_history_cached(f) for f in frames]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        histories: list[SymbolHistory] = []
        for frame, result in zip(frames, results):
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

    # ------------------------------------------------------------------
    # Internal query methods
    # ------------------------------------------------------------------

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

        log.info("orbit_no_mr_data", file_path=file_path)
        return [], True

    async def _enrich_mr(self, mr_node: dict) -> MRContext:
        """Build MRContext from a flat Orbit MergeRequest node (single enrichment query)."""
        mr_iid = int(mr_node.get("iid", 0))
        merged_at = _parse_merged_at(mr_node.get("merged_at"))

        # One neighbors query returns WorkItem, User, and Pipeline nodes together
        neighbors = await self._get_neighbors("MergeRequest", {"iid": mr_iid})
        linked, reviewers, pipeline_status = _extract_mr_enrichment(neighbors)

        return MRContext(
            iid=mr_iid,
            title=_node_str(mr_node, "title"),
            description=_node_str(mr_node, "description"),
            author_username=_node_str(mr_node, "author_username", "author", default="unknown"),
            merged_at=merged_at,
            web_url=_node_str(mr_node, "web_url", "url"),
            linked_issues=linked,
            reviewers=reviewers,
            days_since_merge=_days_since(merged_at),
            pipeline_status=pipeline_status,
        )

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
            nodes = await self._traverse("Vulnerability", {"file_path": file_path}, limit=3)
            findings: list[VulnerabilityFinding] = []
            for node in nodes:
                state = _node_str(node, "state", default="detected")
                if state not in ("detected", "confirmed"):
                    continue
                findings.append(VulnerabilityFinding(
                    name=_node_str(node, "name"),
                    severity=_node_str(node, "severity", default="unknown").lower(),
                    state=state,
                    report_type=_node_str(node, "report_type", default="unknown"),
                    web_url=_node_str(node, "web_url", "url"),
                ))
            return findings
        except Exception as exc:
            log.warning("security_query_failed", file_path=file_path, exc=str(exc))
            return []

    # ------------------------------------------------------------------
    # JSON DSL primitives
    # ------------------------------------------------------------------

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
        """Execute an Orbit JSON DSL query payload with retry. Returns flat node list."""
        t0 = time.monotonic()
        response = await self._client.post("/api/v4/orbit/query", json=payload)

        elapsed = int((time.monotonic() - t0) * 1000)
        log.debug("orbit_http_response", status=response.status_code, elapsed_ms=elapsed)

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

        return body.get("result", {}).get("nodes", [])

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

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

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
            status = data.get("status", "unknown")
            if status != "healthy":
                return Err(
                    message=f"Orbit status is '{status}', expected 'healthy'",
                    code="orbit_unhealthy",
                    retryable=False,
                )
            return Ok(value=status)
        except httpx.HTTPError as exc:
            return Err(message=str(exc), code="orbit_unreachable", retryable=True)
