"""Unit tests for orbit_client.py — no real HTTP calls, uses respx."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from src.rootchain.models import Language, StackFrame
from src.rootchain.orbit_client import (
    OrbitClient,
    _days_since,
    _parse_merged_at,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_frame(func: str = "processPayment", path: str = "payments/processor.py") -> StackFrame:
    return StackFrame(
        file_path=path,
        function_name=func,
        line_number=142,
        language=Language.PYTHON,
        is_library=False,
        frame_depth=1,
        raw_line=f"{path}:142 in {func}",
    )


def _orbit_entity(request: httpx.Request) -> str:
    """Extract the Orbit DSL entity from a POST /api/v4/orbit/query request."""
    body = json.loads(request.content)
    query = body.get("query", {})
    entity = query.get("node", {}).get("entity", "")
    if entity:
        return entity
    return ",".join(
        str(node.get("entity", ""))
        for node in query.get("nodes", [])
        if node.get("entity")
    )


def _orbit_path_field(request: httpx.Request) -> str:
    """Return which MergeRequestDiffFile path field a traversal request uses."""
    body = json.loads(request.content)
    for node in body.get("query", {}).get("nodes", []):
        if node.get("entity") == "MergeRequestDiffFile":
            filters = node.get("filters", {})
            if "old_path" in filters:
                return "old_path"
            if "new_path" in filters:
                return "new_path"
    return ""


def _vuln_nodes(findings: list[dict]) -> dict:  # type: ignore[type-arg]
    """Build an Orbit response containing Vulnerability nodes (flat properties)."""
    return {
        "result": {
            "nodes": [
                {"id": f"v:{i}", "type": "Vulnerability", **f}
                for i, f in enumerate(findings)
            ],
            "edges": [],
        }
    }


def _pipeline_nodes(pipelines: list[dict]) -> dict:  # type: ignore[type-arg]
    """Build an Orbit response containing Pipeline nodes (flat properties)."""
    return {
        "result": {
            "nodes": [
                {"id": f"p:{i}", "type": "Pipeline", **p}
                for i, p in enumerate(pipelines)
            ],
            "edges": [],
        }
    }


# ---------------------------------------------------------------------------
# _parse_merged_at
# ---------------------------------------------------------------------------


def test_parse_merged_at_utc():
    dt = _parse_merged_at("2024-01-11T14:23:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2024


def test_parse_merged_at_none():
    assert _parse_merged_at(None) is None


def test_parse_merged_at_invalid():
    assert _parse_merged_at("not-a-date") is None


def test_parse_merged_at_space_separated_utc():
    dt = _parse_merged_at("2026-06-22 19:45:49.546783")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2026


def test_days_since_none():
    assert _days_since(None) == 0


# ---------------------------------------------------------------------------
# OrbitClient HTTP tests (respx mocks)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_symbol_histories_happy_path(config, orbit_full_fixture):
    """Strategy 1 (File neighbors) succeeds → orbit_miss=False."""
    frame = _make_frame()

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(
            return_value=httpx.Response(200, json=orbit_full_fixture)
        )

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert len(histories) == 1
    assert not histories[0].orbit_miss


@pytest.mark.asyncio
async def test_get_symbol_histories_orbit_miss(config, orbit_empty_fixture):
    """All strategies return empty → orbit_miss=True."""
    frame = _make_frame()

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(
            return_value=httpx.Response(200, json=orbit_empty_fixture)
        )

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert len(histories) == 1
    assert histories[0].orbit_miss


@pytest.mark.asyncio
async def test_get_symbol_histories_fallback_on_empty(
    config, orbit_empty_fixture, orbit_full_fixture
):
    """Strategy 1 (File) empty → Strategy 2 (MergeRequestDiffFile) returns MRs."""
    frame = _make_frame()

    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        entity = _orbit_entity(request)
        # Strategy 1: File neighbors → empty
        if entity == "File":
            return httpx.Response(200, json=orbit_empty_fixture)
        # Strategy 2: MergeRequestDiffFile neighbors → has MRs
        if entity == "MergeRequestDiffFile":
            return httpx.Response(200, json=orbit_full_fixture)
        return httpx.Response(200, json=orbit_empty_fixture)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert not histories[0].orbit_miss
    assert len(histories[0].recent_mrs) > 0


@pytest.mark.asyncio
async def test_get_symbol_histories_current_diff_traversal_old_path(config, orbit_empty_fixture):
    """Current Orbit lookup uses Project -> MR -> Diff -> DiffFile old_path traversal."""
    frame = _make_frame(path="src/rootchain/orchestrator.py")
    traversal_payload = {
        "result": {
            "nodes": [
                {
                    "type": "MergeRequest",
                    "id": "498840448",
                    "iid": "3",
                    "title": "feat: add configurable analysis timeout to orchestrator pipeline",
                    "state": "merged",
                    "merged_at": "2026-06-22 19:45:49.546783",
                },
                {
                    "type": "MergeRequestDiffFile",
                    "id": "3239967325946421559",
                    "old_path": "src/rootchain/orchestrator.py",
                    "new_path": "",
                },
            ],
            "edges": [],
        }
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        if _orbit_path_field(request) == "old_path":
            return httpx.Response(200, json=traversal_payload)
        return httpx.Response(200, json=orbit_empty_fixture)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)
        mock.get("/api/v4/projects/myorg%2Fmyapp/merge_requests/3").mock(
            return_value=httpx.Response(
                200,
                json={
                    "iid": 3,
                    "title": "feat: add configurable analysis timeout to orchestrator pipeline",
                    "web_url": "https://gitlab.example.com/myorg/myapp/-/merge_requests/3",
                    "author": {"username": "alice"},
                },
            )
        )

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert not histories[0].orbit_miss
    assert histories[0].recent_mrs[0].iid == 3
    assert histories[0].recent_mrs[0].author_username == "alice"
    assert histories[0].recent_mrs[0].merged_at is not None
    assert histories[0].recent_mrs[0].merged_at.tzinfo is not None


@pytest.mark.asyncio
async def test_get_symbol_histories_500_then_success(config, orbit_full_fixture):
    """5xx triggers tenacity retry — second attempt succeeds."""
    frame = _make_frame()
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(500)
        return httpx.Response(200, json=orbit_full_fixture)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert not histories[0].orbit_miss


@pytest.mark.asyncio
async def test_get_symbol_histories_exception_returns_orbit_miss(config):
    """Network exception on a frame yields orbit_miss rather than crashing."""
    frame = _make_frame()

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(
            side_effect=httpx.NetworkError("connection refused")
        )

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert histories[0].orbit_miss


@pytest.mark.asyncio
async def test_orbit_null_result_returns_empty_nodes(config):
    """Orbit returning {"result": null} must not raise AttributeError."""
    frame = _make_frame()

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(
            return_value=httpx.Response(200, json={"result": None})
        )

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert histories[0].orbit_miss


@pytest.mark.asyncio
async def test_orbit_response_error_key(config):
    """Orbit returning {"error": "..."} body is treated as orbit_miss."""
    frame = _make_frame()

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(
            return_value=httpx.Response(200, json={"error": "syntax error in query"})
        )

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert histories[0].orbit_miss


@pytest.mark.asyncio
async def test_cache_reuses_result(config, orbit_full_fixture):
    """Second call for the same frame hits cache — no extra HTTP requests."""
    frame = _make_frame()

    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=orbit_full_fixture)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            await client.get_symbol_histories([frame])
            first_call_count = call_count

            await client.get_symbol_histories([frame])
            second_call_count = call_count - first_call_count

    assert first_call_count > 0
    assert second_call_count == 0


@pytest.mark.asyncio
async def test_check_health_healthy(config):
    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.get("/api/v4/orbit/status").mock(
            return_value=httpx.Response(
                200,
                json={"user": {"available": True}, "system": {"status": "healthy"}},
            )
        )

        async with OrbitClient(config) as client:
            result = await client.check_health()

    from src.rootchain.models import Ok
    assert isinstance(result, Ok)


@pytest.mark.asyncio
async def test_check_health_unhealthy(config):
    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.get("/api/v4/orbit/status").mock(
            return_value=httpx.Response(
                200,
                json={"user": {"available": True}, "system": {"status": "degraded"}},
            )
        )

        async with OrbitClient(config) as client:
            result = await client.check_health()

    from src.rootchain.models import Err
    assert isinstance(result, Err)


# ---------------------------------------------------------------------------
# Security findings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_security_findings_returns_findings(config, orbit_empty_fixture):
    """When orbit_miss, security findings are empty (not queried)."""
    frame = _make_frame()

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(
            return_value=httpx.Response(200, json=orbit_empty_fixture)
        )

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert histories[0].orbit_miss
    assert histories[0].security_findings == []


@pytest.mark.asyncio
async def test_get_security_findings_on_successful_orbit_query(
    config, orbit_full_fixture, orbit_empty_fixture
):
    """When MRs are found, security findings from Vulnerability traversal are attached."""
    frame = _make_frame()

    vuln_payload = _vuln_nodes([{
        "name": "SQL Injection in processPayment",
        "severity": "critical",
        "state": "detected",
        "report_type": "sast",
        "web_url": "https://gitlab.example.com/myorg/myapp/-/security/vulnerabilities/1",
    }])

    def _handler(request: httpx.Request) -> httpx.Response:
        entity = _orbit_entity(request)
        if "Vulnerability" in entity:
            return httpx.Response(200, json=vuln_payload)
        if entity == "File":
            return httpx.Response(200, json=orbit_full_fixture)
        return httpx.Response(200, json=orbit_empty_fixture)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert not histories[0].orbit_miss
    assert len(histories[0].security_findings) == 1
    assert histories[0].security_findings[0].name == "SQL Injection in processPayment"
    assert histories[0].security_findings[0].severity == "critical"


@pytest.mark.asyncio
async def test_get_security_findings_exception_returns_empty(
    config, orbit_full_fixture, orbit_empty_fixture
):
    """Network error on security query returns [] without crashing."""
    frame = _make_frame()

    def _handler(request: httpx.Request) -> httpx.Response:
        entity = _orbit_entity(request)
        if "Vulnerability" in entity:
            raise httpx.NetworkError("Orbit security domain unreachable")
        if entity == "File":
            return httpx.Response(200, json=orbit_full_fixture)
        return httpx.Response(200, json=orbit_empty_fixture)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert not histories[0].orbit_miss
    assert histories[0].security_findings == []


# ---------------------------------------------------------------------------
# Pipeline status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_status_passed_attached_to_mr(
    config, orbit_full_fixture, orbit_empty_fixture
):
    """Pipeline 'passed' surfaced on the enriched MR via MergeRequest neighbors."""
    frame = _make_frame()

    enrichment_payload = _pipeline_nodes([{
        "status": "passed",
        "web_url": "https://gitlab.example.com/myorg/myapp/-/pipelines/99",
        "created_at": "2024-01-11T15:00:00Z",
    }])

    def _handler(request: httpx.Request) -> httpx.Response:
        entity = _orbit_entity(request)
        if entity == "MergeRequest":
            return httpx.Response(200, json=enrichment_payload)
        if entity == "File":
            return httpx.Response(200, json=orbit_full_fixture)
        return httpx.Response(200, json=orbit_empty_fixture)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert not histories[0].orbit_miss
    assert len(histories[0].recent_mrs) > 0
    assert histories[0].recent_mrs[0].pipeline_status == "passed"


@pytest.mark.asyncio
async def test_pipeline_status_none_when_no_pipeline(
    config, orbit_full_fixture, orbit_empty_fixture
):
    """No Pipeline node in enrichment → pipeline_status is None."""
    frame = _make_frame()

    def _handler(request: httpx.Request) -> httpx.Response:
        entity = _orbit_entity(request)
        if entity == "File":
            return httpx.Response(200, json=orbit_full_fixture)
        return httpx.Response(200, json=orbit_empty_fixture)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert not histories[0].orbit_miss
    assert histories[0].recent_mrs[0].pipeline_status is None
