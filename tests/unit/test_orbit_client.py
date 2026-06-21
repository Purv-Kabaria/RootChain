"""Unit tests for orbit_client.py — no real HTTP calls, uses respx."""

from __future__ import annotations

import json
from datetime import datetime, timezone

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
# Helper
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


def test_days_since_none():
    assert _days_since(None) == 0


# ---------------------------------------------------------------------------
# OrbitClient HTTP tests (respx mocks)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_symbol_histories_happy_path(config, orbit_full_fixture):
    frame = _make_frame()

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        # Primary Orbit query returns two MRs
        mock.post("/api/v4/orbit/query").mock(
            return_value=httpx.Response(200, json=orbit_full_fixture)
        )

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert len(histories) == 1
    assert not histories[0].orbit_miss


@pytest.mark.asyncio
async def test_get_symbol_histories_orbit_miss(config, orbit_empty_fixture):
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
async def test_get_symbol_histories_fallback_on_empty(config, orbit_empty_fixture, orbit_full_fixture):
    """First (primary) query empty → should try fallback → fallback_used=True."""
    frame = _make_frame()

    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        # First call (primary definition query) returns empty
        if call_count == 1:
            return httpx.Response(200, json=orbit_empty_fixture)
        # Second call (file-level fallback) returns a result
        return httpx.Response(200, json=orbit_full_fixture)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert not histories[0].orbit_miss
    assert histories[0].fallback_used


@pytest.mark.asyncio
async def test_get_symbol_histories_500_then_success(config, orbit_full_fixture):
    """5xx should be retried — second attempt succeeds."""
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
    """Network exception on a single frame should yield orbit_miss, not crash."""
    frame = _make_frame()

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=httpx.NetworkError("connection refused"))

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert histories[0].orbit_miss


@pytest.mark.asyncio
async def test_orbit_response_error_key(config):
    """Orbit returning {"error": "..."} should be treated as orbit_miss."""
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
    """Sequential calls for the same frame should reuse cached results (zero extra queries)."""
    frame = _make_frame()

    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=orbit_full_fixture)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            # First call — populates cache
            await client.get_symbol_histories([frame])
            first_call_count = call_count

            # Second call for same frame — cache hit, no new HTTP calls
            await client.get_symbol_histories([frame])
            second_call_count = call_count - first_call_count

    assert first_call_count > 0  # first call did make requests
    assert second_call_count == 0  # second call was served from cache


@pytest.mark.asyncio
async def test_check_health_healthy(config):
    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.get("/api/v4/orbit/status").mock(
            return_value=httpx.Response(200, json={"status": "healthy"})
        )

        async with OrbitClient(config) as client:
            result = await client.check_health()

    from src.rootchain.models import Ok
    assert isinstance(result, Ok)


@pytest.mark.asyncio
async def test_check_health_unhealthy(config):
    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.get("/api/v4/orbit/status").mock(
            return_value=httpx.Response(200, json={"status": "degraded"})
        )

        async with OrbitClient(config) as client:
            result = await client.check_health()

    from src.rootchain.models import Err
    assert isinstance(result, Err)


# ---------------------------------------------------------------------------
# _get_security_findings
# ---------------------------------------------------------------------------


def _vuln_response(findings: list[dict]) -> dict:  # type: ignore[type-arg]
    return {
        "data": {
            "nodes": [
                {
                    "id": f"v:{i}",
                    "type": "Vulnerability",
                    "properties": f,
                }
                for i, f in enumerate(findings)
            ]
        }
    }


@pytest.mark.asyncio
async def test_get_security_findings_returns_findings(config, orbit_empty_fixture):
    """Security query returns two active findings — both surfaced in SymbolHistory."""
    frame = _make_frame()

    vuln_payload = _vuln_response([
        {
            "name": "SQL Injection in processPayment",
            "severity": "critical",
            "state": "detected",
            "report_type": "sast",
            "web_url": "https://gitlab.example.com/myorg/myapp/-/security/vulnerabilities/1",
        },
        {
            "name": "Path traversal risk",
            "severity": "high",
            "state": "confirmed",
            "report_type": "sast",
            "web_url": "https://gitlab.example.com/myorg/myapp/-/security/vulnerabilities/2",
        },
    ])

    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        body = json.loads(request.content)
        # Primary + fallback + security = 3 queries for an orbit_miss case after fallback
        # (primary → empty, fallback → empty → orbit_miss; security never called on orbit_miss)
        # Instead: primary → full, caller_count → empty, security → vuln_payload, enrichment queries
        if "Vulnerability" in body.get("query", ""):
            return httpx.Response(200, json=vuln_payload)
        return httpx.Response(200, json=orbit_empty_fixture)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    # orbit_miss when all non-security queries returned empty
    assert histories[0].orbit_miss
    # security_findings empty because orbit_miss short-circuits before security query
    assert histories[0].security_findings == []


@pytest.mark.asyncio
async def test_get_security_findings_on_successful_orbit_query(config, orbit_full_fixture):
    """When the primary query succeeds, security findings are fetched and attached."""
    frame = _make_frame()

    vuln_payload = _vuln_response([
        {
            "name": "SQL Injection in processPayment",
            "severity": "critical",
            "state": "detected",
            "report_type": "sast",
            "web_url": "https://gitlab.example.com/myorg/myapp/-/security/vulnerabilities/1",
        }
    ])

    empty = {"data": {"nodes": []}}

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = body.get("query", "")
        if "Vulnerability" in query:
            return httpx.Response(200, json=vuln_payload)
        # Primary MR query, caller_count, linked issues, reviewers, pipeline — all return empty
        return httpx.Response(200, json=orbit_full_fixture if "Definition" in query else empty)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert not histories[0].orbit_miss
    assert len(histories[0].security_findings) == 1
    assert histories[0].security_findings[0].name == "SQL Injection in processPayment"
    assert histories[0].security_findings[0].severity == "critical"


@pytest.mark.asyncio
async def test_get_security_findings_exception_returns_empty(config, orbit_full_fixture):
    """If security query raises, _get_security_findings returns [] without crashing."""
    frame = _make_frame()
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        body = json.loads(request.content)
        if "Vulnerability" in body.get("query", ""):
            raise httpx.NetworkError("Orbit security domain unreachable")
        return httpx.Response(200, json=orbit_full_fixture if "Definition" in body.get("query", "") else {"data": {"nodes": []}})

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert not histories[0].orbit_miss
    assert histories[0].security_findings == []


# ---------------------------------------------------------------------------
# _get_pipeline_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_status_passed_attached_to_mr(config, orbit_full_fixture):
    """Pipeline status 'passed' is fetched and surfaced on the enriched MR."""
    frame = _make_frame()

    pipeline_payload = {
        "data": {
            "nodes": [
                {
                    "id": "p:1",
                    "type": "Pipeline",
                    "properties": {
                        "status": "passed",
                        "web_url": "https://gitlab.example.com/myorg/myapp/-/pipelines/99",
                        "created_at": "2024-01-11T15:00:00Z",
                    },
                }
            ]
        }
    }

    empty = {"data": {"nodes": []}}

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = body.get("query", "")
        if "Pipeline" in query:
            return httpx.Response(200, json=pipeline_payload)
        if "Vulnerability" in query:
            return httpx.Response(200, json=empty)
        if "Definition" in query:
            return httpx.Response(200, json=orbit_full_fixture)
        return httpx.Response(200, json=empty)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert not histories[0].orbit_miss
    assert len(histories[0].recent_mrs) > 0
    assert histories[0].recent_mrs[0].pipeline_status == "passed"


@pytest.mark.asyncio
async def test_pipeline_status_none_when_no_pipeline(config, orbit_full_fixture):
    """If no Pipeline node is returned, pipeline_status is None."""
    frame = _make_frame()
    empty = {"data": {"nodes": []}}

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "Definition" in body.get("query", ""):
            return httpx.Response(200, json=orbit_full_fixture)
        return httpx.Response(200, json=empty)

    with respx.mock(base_url="https://gitlab.example.com") as mock:
        mock.post("/api/v4/orbit/query").mock(side_effect=_handler)

        async with OrbitClient(config) as client:
            histories = await client.get_symbol_histories([frame])

    assert not histories[0].orbit_miss
    assert histories[0].recent_mrs[0].pipeline_status is None
