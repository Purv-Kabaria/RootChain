"""GitLab REST API client for adding notes and labels to issues.

No business logic. Only I/O: POST notes, PUT labels.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

from .config import Config
from .models import Err, Ok, Result

log = structlog.get_logger()


class GitLabClient:
    """Async client for GitLab issue operations (comments and labels)."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.gitlab_api_url,
            headers={
                "PRIVATE-TOKEN": config.gitlab_token,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "GitLabClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def add_note(
        self, project_path: str, issue_iid: int, body: str
    ) -> Result[int]:
        """POST a comment on an issue. Returns the note id on success."""
        url = f"/projects/{_encode(project_path)}/issues/{issue_iid}/notes"
        return await self._post_with_retry(url, {"body": body}, label="add_note")

    async def add_label(
        self, project_path: str, issue_iid: int, label: str
    ) -> Result[int]:
        """Add a label to an issue without removing existing labels."""
        url = f"/projects/{_encode(project_path)}/issues/{issue_iid}"
        return await self._put_with_retry(url, {"add_labels": label}, label="add_label")

    async def get_issue_labels(
        self, project_path: str, issue_iid: int
    ) -> Result[list[str]]:
        """Return the current label set of an issue."""
        url = f"/projects/{_encode(project_path)}/issues/{issue_iid}"
        try:
            resp = await self._client.get(url)
            if resp.status_code == 403:
                return Err(
                    message="Token missing `api` scope or lacks project access. "
                    "Check ROOTCHAIN_GITLAB_TOKEN.",
                    code="gitlab_forbidden",
                    retryable=False,
                )
            resp.raise_for_status()
            return Ok(value=resp.json().get("labels", []))
        except httpx.HTTPError as exc:
            return Err(message=str(exc), code="gitlab_http_error", retryable=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _post_with_retry(
        self, url: str, payload: dict, label: str  # type: ignore[type-arg]
    ) -> Result[int]:
        for attempt in range(1, self._config.orbit_max_retries + 1):
            try:
                resp = await self._client.post(url, json=payload)
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", "5"))
                    log.warning("gitlab_rate_limited", endpoint=url, wait=wait)
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code == 403:
                    return Err(
                        message="Token missing `api` scope. Check ROOTCHAIN_GITLAB_TOKEN.",
                        code="gitlab_forbidden",
                        retryable=False,
                    )
                resp.raise_for_status()
                data = resp.json()
                log.info(f"gitlab_{label}_ok", url=url, id=data.get("id"))
                return Ok(value=int(data.get("id", 0)))
            except httpx.HTTPStatusError as exc:
                log.error(f"gitlab_{label}_http_error", attempt=attempt, status=exc.response.status_code)
                if attempt == self._config.orbit_max_retries:
                    return Err(
                        message=str(exc),
                        code="gitlab_http_error",
                        retryable=exc.response.status_code >= 500,
                    )
            except httpx.HTTPError as exc:
                log.error(f"gitlab_{label}_network_error", attempt=attempt, exc=str(exc))
                if attempt == self._config.orbit_max_retries:
                    return Err(message=str(exc), code="gitlab_network_error", retryable=True)
                await asyncio.sleep(2**attempt)
        return Err(message="Max retries exceeded", code="gitlab_max_retries", retryable=True)

    async def _put_with_retry(
        self, url: str, payload: dict, label: str  # type: ignore[type-arg]
    ) -> Result[int]:
        for attempt in range(1, self._config.orbit_max_retries + 1):
            try:
                resp = await self._client.put(url, json=payload)
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", "5"))
                    log.warning("gitlab_rate_limited", endpoint=url, wait=wait)
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code == 403:
                    return Err(
                        message="Token missing `api` scope. Check ROOTCHAIN_GITLAB_TOKEN.",
                        code="gitlab_forbidden",
                        retryable=False,
                    )
                resp.raise_for_status()
                data = resp.json()
                log.info(f"gitlab_{label}_ok", url=url, iid=data.get("iid"))
                return Ok(value=int(data.get("iid", 0)))
            except httpx.HTTPStatusError as exc:
                log.error(f"gitlab_{label}_http_error", attempt=attempt, status=exc.response.status_code)
                if attempt == self._config.orbit_max_retries:
                    return Err(
                        message=str(exc),
                        code="gitlab_http_error",
                        retryable=exc.response.status_code >= 500,
                    )
            except httpx.HTTPError as exc:
                log.error(f"gitlab_{label}_network_error", attempt=attempt, exc=str(exc))
                if attempt == self._config.orbit_max_retries:
                    return Err(message=str(exc), code="gitlab_network_error", retryable=True)
                await asyncio.sleep(2**attempt)
        return Err(message="Max retries exceeded", code="gitlab_max_retries", retryable=True)


def _encode(project_path: str) -> str:
    """URL-encode a project path for GitLab REST API endpoints."""
    from urllib.parse import quote

    return quote(project_path, safe="")
