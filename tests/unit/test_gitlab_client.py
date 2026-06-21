"""Unit tests for gitlab_client.py — no real HTTP calls, uses respx."""

from __future__ import annotations

import httpx
import pytest
import respx

from src.rootchain.gitlab_client import GitLabClient, _encode
from src.rootchain.models import Err, Ok


# ---------------------------------------------------------------------------
# _encode helper
# ---------------------------------------------------------------------------


def test_encode_simple():
    assert _encode("myorg/myapp") == "myorg%2Fmyapp"


def test_encode_nested():
    assert _encode("group/sub/project") == "group%2Fsub%2Fproject"


# ---------------------------------------------------------------------------
# add_note
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_note_success(config):
    with respx.mock(base_url="https://gitlab.example.com/api/v4") as mock:
        mock.post("/projects/myorg%2Fmyapp/issues/42/notes").mock(
            return_value=httpx.Response(201, json={"id": 999, "body": "test"})
        )
        async with GitLabClient(config) as client:
            result = await client.add_note("myorg/myapp", 42, "test comment")

    assert isinstance(result, Ok)
    assert result.value == 999


@pytest.mark.asyncio
async def test_add_note_403_returns_err(config):
    with respx.mock(base_url="https://gitlab.example.com/api/v4") as mock:
        mock.post("/projects/myorg%2Fmyapp/issues/42/notes").mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )
        async with GitLabClient(config) as client:
            result = await client.add_note("myorg/myapp", 42, "test")

    assert isinstance(result, Err)
    assert result.code == "gitlab_forbidden"
    assert not result.retryable


@pytest.mark.asyncio
async def test_add_note_500_retries_and_fails(config):
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(500)

    with respx.mock(base_url="https://gitlab.example.com/api/v4") as mock:
        mock.post("/projects/myorg%2Fmyapp/issues/42/notes").mock(side_effect=_handler)
        async with GitLabClient(config) as client:
            result = await client.add_note("myorg/myapp", 42, "test")

    assert isinstance(result, Err)
    assert call_count == config.orbit_max_retries


@pytest.mark.asyncio
async def test_add_note_429_retries(config):
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(201, json={"id": 5})

    with respx.mock(base_url="https://gitlab.example.com/api/v4") as mock:
        mock.post("/projects/myorg%2Fmyapp/issues/42/notes").mock(side_effect=_handler)
        async with GitLabClient(config) as client:
            result = await client.add_note("myorg/myapp", 42, "test")

    assert isinstance(result, Ok)


# ---------------------------------------------------------------------------
# add_label
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_label_success(config):
    with respx.mock(base_url="https://gitlab.example.com/api/v4") as mock:
        mock.put("/projects/myorg%2Fmyapp/issues/42").mock(
            return_value=httpx.Response(200, json={"iid": 42, "labels": ["rootchain-analyzed"]})
        )
        async with GitLabClient(config) as client:
            result = await client.add_label("myorg/myapp", 42, "rootchain-analyzed")

    assert isinstance(result, Ok)
    assert result.value == 42


@pytest.mark.asyncio
async def test_add_label_403_not_retryable(config):
    with respx.mock(base_url="https://gitlab.example.com/api/v4") as mock:
        mock.put("/projects/myorg%2Fmyapp/issues/42").mock(
            return_value=httpx.Response(403)
        )
        async with GitLabClient(config) as client:
            result = await client.add_label("myorg/myapp", 42, "rootchain-analyzed")

    assert isinstance(result, Err)
    assert not result.retryable


# ---------------------------------------------------------------------------
# get_issue_labels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_issue_labels_success(config):
    with respx.mock(base_url="https://gitlab.example.com/api/v4") as mock:
        mock.get("/projects/myorg%2Fmyapp/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={"iid": 42, "labels": ["sentry-alert", "Sentry"]},
            )
        )
        async with GitLabClient(config) as client:
            result = await client.get_issue_labels("myorg/myapp", 42)

    assert isinstance(result, Ok)
    assert "sentry-alert" in result.value


@pytest.mark.asyncio
async def test_get_issue_labels_403(config):
    with respx.mock(base_url="https://gitlab.example.com/api/v4") as mock:
        mock.get("/projects/myorg%2Fmyapp/issues/42").mock(
            return_value=httpx.Response(403)
        )
        async with GitLabClient(config) as client:
            result = await client.get_issue_labels("myorg/myapp", 42)

    assert isinstance(result, Err)
    assert result.code == "gitlab_forbidden"


@pytest.mark.asyncio
async def test_get_issue_labels_network_error(config):
    with respx.mock(base_url="https://gitlab.example.com/api/v4") as mock:
        mock.get("/projects/myorg%2Fmyapp/issues/42").mock(
            side_effect=httpx.NetworkError("connection refused")
        )
        async with GitLabClient(config) as client:
            result = await client.get_issue_labels("myorg/myapp", 42)

    assert isinstance(result, Err)
    assert result.retryable


# ---------------------------------------------------------------------------
# _post_with_retry — network error path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_note_network_error_returns_err(config):
    from src.rootchain.config import Config

    one_shot = Config(**{**config.__dict__, "orbit_max_retries": 1})
    with respx.mock(base_url="https://gitlab.example.com/api/v4") as mock:
        mock.post("/projects/myorg%2Fmyapp/issues/42/notes").mock(
            side_effect=httpx.NetworkError("connection refused")
        )
        async with GitLabClient(one_shot) as client:
            result = await client.add_note("myorg/myapp", 42, "test")

    assert isinstance(result, Err)
    assert result.code == "gitlab_network_error"
    assert result.retryable


# ---------------------------------------------------------------------------
# _put_with_retry — 429, 500, and network error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_label_429_retries_and_succeeds(config):
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"iid": 42})

    with respx.mock(base_url="https://gitlab.example.com/api/v4") as mock:
        mock.put("/projects/myorg%2Fmyapp/issues/42").mock(side_effect=_handler)
        async with GitLabClient(config) as client:
            result = await client.add_label("myorg/myapp", 42, "rootchain-analyzed")

    assert isinstance(result, Ok)
    assert call_count == 2


@pytest.mark.asyncio
async def test_add_label_500_returns_err(config):
    from src.rootchain.config import Config

    one_shot = Config(**{**config.__dict__, "orbit_max_retries": 1})
    with respx.mock(base_url="https://gitlab.example.com/api/v4") as mock:
        mock.put("/projects/myorg%2Fmyapp/issues/42").mock(
            return_value=httpx.Response(500)
        )
        async with GitLabClient(one_shot) as client:
            result = await client.add_label("myorg/myapp", 42, "rootchain-analyzed")

    assert isinstance(result, Err)
    assert result.code == "gitlab_http_error"


@pytest.mark.asyncio
async def test_add_label_network_error_returns_err(config):
    from src.rootchain.config import Config

    one_shot = Config(**{**config.__dict__, "orbit_max_retries": 1})
    with respx.mock(base_url="https://gitlab.example.com/api/v4") as mock:
        mock.put("/projects/myorg%2Fmyapp/issues/42").mock(
            side_effect=httpx.NetworkError("timeout")
        )
        async with GitLabClient(one_shot) as client:
            result = await client.add_label("myorg/myapp", 42, "rootchain-analyzed")

    assert isinstance(result, Err)
    assert result.code == "gitlab_network_error"
    assert result.retryable
