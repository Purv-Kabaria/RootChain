"""Integration tests — require a real GitLab instance with Orbit enabled.

These tests are skipped unless ROOTCHAIN_INTEGRATION_TESTS=1 is set.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("ROOTCHAIN_INTEGRATION_TESTS") != "1",
    reason="Set ROOTCHAIN_INTEGRATION_TESTS=1 to run integration tests",
)


@pytest.mark.asyncio
async def test_orbit_reachable():
    from src.rootchain.config import Config
    from src.rootchain.orbit_client import OrbitClient

    config = Config.from_env()
    async with OrbitClient(config) as client:
        result = await client.check_health()

    from src.rootchain.models import Ok
    assert isinstance(result, Ok), f"Orbit health check failed: {result}"


@pytest.mark.asyncio
async def test_full_pipeline_with_real_issue():
    """End-to-end test: analyze a real GitLab issue.

    Requires ROOTCHAIN_TEST_ISSUE_IID env var (an existing issue iid with a
    Sentry-format description in the configured project).
    """
    issue_iid_str = os.getenv("ROOTCHAIN_TEST_ISSUE_IID")
    if not issue_iid_str:
        pytest.skip("Set ROOTCHAIN_TEST_ISSUE_IID to run this test")

    from src.rootchain.config import Config
    from src.rootchain.gitlab_client import GitLabClient
    from src.rootchain.orchestrator import run_analysis
    import httpx
    from urllib.parse import quote

    config = Config.from_env()

    async with httpx.AsyncClient(
        base_url=config.gitlab_api_url,
        headers={"PRIVATE-TOKEN": config.gitlab_token},
    ) as http:
        resp = await http.get(
            f"/projects/{quote(config.project_path, safe='')}/issues/{issue_iid_str}"
        )
        resp.raise_for_status()
        issue = resp.json()

    await run_analysis(
        project_path=config.project_path,
        issue_iid=int(issue_iid_str),
        issue_title=issue["title"],
        issue_description=issue.get("description", ""),
        issue_labels=issue.get("labels", []),
        config=config,
    )
