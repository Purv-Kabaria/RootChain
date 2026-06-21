"""Orbit REST API client — async, with retries, caching, and fallback queries.

Never string-interpolates user input into Cypher. Always uses parameterized queries.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
import structlog
from tenacity import (
    RetryError,
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
# Query templates (parameterized — never interpolated)
# ---------------------------------------------------------------------------

_PRIMARY_QUERY = """
MATCH (d:Definition {name: $function_name})
      -[:DEFINED_IN]->(f:File {path: $file_path})
      <-[:MODIFIES_FILE]-(mr:MergeRequest)
WHERE mr.merged_at IS NOT NULL
  AND mr.project_full_path STARTS WITH $group_path
RETURN
  mr.iid          AS iid,
  mr.title        AS title,
  mr.description  AS description,
  mr.web_url      AS url,
  mr.merged_at    AS merged_at,
  mr.author_username AS author
ORDER BY mr.merged_at DESC
LIMIT 3
"""

_FALLBACK_QUERY = """
MATCH (f:File {path: $file_path})
      <-[:MODIFIES_FILE]-(mr:MergeRequest)
WHERE mr.merged_at IS NOT NULL
  AND mr.project_full_path STARTS WITH $group_path
RETURN
  mr.iid          AS iid,
  mr.title        AS title,
  mr.description  AS description,
  mr.web_url      AS url,
  mr.merged_at    AS merged_at,
  mr.author_username AS author
ORDER BY mr.merged_at DESC
LIMIT 3
"""

_LINKED_ISSUES_QUERY = """
MATCH (mr:MergeRequest {iid: $mr_iid, project_full_path: $project_path})
      -[:CLOSES|MENTIONED_IN]->(wi:WorkItem)
RETURN
  wi.iid    AS iid,
  wi.title  AS title,
  wi.state  AS state,
  wi.web_url AS url
"""

_REVIEWERS_QUERY = """
MATCH (u:User)-[:REVIEWED]->(mr:MergeRequest {iid: $mr_iid, project_full_path: $project_path})
RETURN u.username AS username
"""

_CALLER_COUNT_QUERY = """
MATCH (caller:Definition)-[:CALLS]->(d:Definition {name: $function_name})
RETURN count(caller) AS caller_count
"""

_SECURITY_QUERY = """
MATCH (f:File {path: $file_path})<-[:AFFECTS_FILE]-(v:Vulnerability)
WHERE v.state IN ["detected", "confirmed"]
RETURN
  v.name        AS name,
  v.severity    AS severity,
  v.state       AS state,
  v.report_type AS report_type,
  v.web_url     AS web_url
ORDER BY
  CASE v.severity
    WHEN "critical" THEN 1
    WHEN "high"     THEN 2
    WHEN "medium"   THEN 3
    ELSE 4
  END
LIMIT 3
"""

_PIPELINE_STATUS_QUERY = """
MATCH (mr:MergeRequest {iid: $mr_iid, project_full_path: $project_path})
      -[:HAS_PIPELINE]->(p:Pipeline)
RETURN
  p.status   AS status,
  p.web_url  AS web_url,
  p.created_at AS created_at
ORDER BY p.created_at DESC
LIMIT 1
"""


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


# ---------------------------------------------------------------------------
# OrbitClient
# ---------------------------------------------------------------------------


class OrbitClient:
    """Async client for GitLab Orbit graph queries."""

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
        # In-process cache: key = (function_name, file_path) → SymbolHistory
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
        """Query Orbit for all frames in parallel. Never raises — returns orbit_miss on failure."""
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

        # 1. Primary query: Definition → File → MergeRequest
        mr_nodes = await self._run_query(
            _PRIMARY_QUERY,
            {
                "function_name": frame.function_name,
                "file_path": frame.file_path,
                "group_path": self._config.group_path,
            },
        )

        fallback_used = False
        if not mr_nodes:
            log_.info("orbit_primary_miss_trying_fallback")
            mr_nodes = await self._run_query(
                _FALLBACK_QUERY,
                {
                    "file_path": frame.file_path,
                    "group_path": self._config.group_path,
                },
            )
            fallback_used = True

        if not mr_nodes:
            log_.info("orbit_miss")
            return self._orbit_miss(frame)

        # 2. Caller count + security findings — run in parallel
        caller_count, security_findings = await asyncio.gather(
            self._get_caller_count(frame.function_name),
            self._get_security_findings(frame.file_path),
        )

        # 3. Enrich each MR with linked issues + reviewers + pipeline status
        recent_mrs = await asyncio.gather(
            *[self._enrich_mr(node) for node in mr_nodes[:3]],
            return_exceptions=True,
        )

        enriched: list[MRContext] = []
        for item in recent_mrs:
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

    async def _enrich_mr(self, mr_node: dict) -> MRContext:  # type: ignore[type-arg]
        props = mr_node.get("properties", {})
        mr_iid = int(props.get("iid", 0))
        merged_at = _parse_merged_at(props.get("merged_at"))

        # Linked work items + reviewers + pipeline status — all in parallel
        linked, reviewers, pipeline_status = await asyncio.gather(
            self._get_linked_issues(mr_iid),
            self._get_reviewers(mr_iid),
            self._get_pipeline_status(mr_iid),
        )

        return MRContext(
            iid=mr_iid,
            title=str(props.get("title", "")),
            description=str(props.get("description", "")),
            author_username=str(props.get("author", props.get("author_username", ""))),
            merged_at=merged_at,
            web_url=str(props.get("url", props.get("web_url", ""))),
            linked_issues=linked,
            reviewers=reviewers,
            days_since_merge=_days_since(merged_at),
            pipeline_status=pipeline_status,
        )

    async def _get_linked_issues(self, mr_iid: int) -> list[LinkedIssue]:
        try:
            nodes = await self._run_query(
                _LINKED_ISSUES_QUERY,
                {
                    "mr_iid": mr_iid,
                    "project_path": self._config.project_path,
                },
            )
            issues = []
            for node in nodes:
                if node.get("type") not in ("WorkItem", None):
                    continue
                p = node.get("properties", {})
                iid_raw = p.get("iid", 0)
                try:
                    iid = int(iid_raw)
                except (ValueError, TypeError):
                    continue
                if iid == 0:
                    continue
                issues.append(
                    LinkedIssue(
                        iid=iid,
                        title=str(p.get("title", "")),
                        web_url=str(p.get("url", p.get("web_url", ""))),
                        state=str(p.get("state", "unknown")),
                    )
                )
            return issues
        except Exception as exc:
            log.warning("linked_issues_query_failed", mr_iid=mr_iid, exc=str(exc))
            return []

    async def _get_reviewers(self, mr_iid: int) -> list[str]:
        try:
            nodes = await self._run_query(
                _REVIEWERS_QUERY,
                {
                    "mr_iid": mr_iid,
                    "project_path": self._config.project_path,
                },
            )
            return [
                str(n.get("properties", {}).get("username", ""))
                for n in nodes
                if n.get("type") in ("User", None)
                and n.get("properties", {}).get("username")
            ]
        except Exception as exc:
            log.warning("reviewers_query_failed", mr_iid=mr_iid, exc=str(exc))
            return []

    async def _get_caller_count(self, function_name: str) -> int:
        try:
            nodes = await self._run_query(
                _CALLER_COUNT_QUERY,
                {"function_name": function_name},
            )
            if nodes:
                raw = nodes[0].get("properties", {}).get("caller_count", 0)
                try:
                    return int(raw)
                except (ValueError, TypeError):
                    return 0
            return 0
        except Exception as exc:
            log.warning("caller_count_query_failed", function_name=function_name, exc=str(exc))
            return 0

    async def _get_security_findings(self, file_path: str) -> list[VulnerabilityFinding]:
        try:
            nodes = await self._run_query(_SECURITY_QUERY, {"file_path": file_path})
            findings = []
            for node in nodes:
                p = node.get("properties", {})
                findings.append(
                    VulnerabilityFinding(
                        name=str(p.get("name", "")),
                        severity=str(p.get("severity", "unknown")).lower(),
                        state=str(p.get("state", "detected")),
                        report_type=str(p.get("report_type", "unknown")),
                        web_url=str(p.get("web_url", "")),
                    )
                )
            return findings
        except Exception as exc:
            log.warning("security_query_failed", file_path=file_path, exc=str(exc))
            return []

    async def _get_pipeline_status(self, mr_iid: int) -> str | None:
        try:
            nodes = await self._run_query(
                _PIPELINE_STATUS_QUERY,
                {"mr_iid": mr_iid, "project_path": self._config.project_path},
            )
            if nodes:
                return str(nodes[0].get("properties", {}).get("status", "")) or None
            return None
        except Exception as exc:
            log.warning("pipeline_status_query_failed", mr_iid=mr_iid, exc=str(exc))
            return None

    async def _run_query(
        self, query: str, params: dict  # type: ignore[type-arg]
    ) -> list[dict]:  # type: ignore[type-arg]
        """Execute an Orbit query with retry. Returns list of nodes on success."""
        return await self._run_with_retry(query, params)

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        reraise=True,
    )
    async def _run_with_retry(
        self, query: str, params: dict  # type: ignore[type-arg]
    ) -> list[dict]:  # type: ignore[type-arg]
        t0 = time.monotonic()
        payload = {
            "query": query.strip(),
            "parameters": params,
            "timeout": self._config.orbit_timeout_seconds * 1000,
        }

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

        response.raise_for_status()

        body = response.json()
        if "error" in body:
            log.error("orbit_query_error", error=body["error"])
            return []

        if "data" not in body:
            log.warning("orbit_response_missing_data_key")
            return []

        return body["data"].get("nodes", [])

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
