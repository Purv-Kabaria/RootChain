"""Optional FastAPI webhook receiver.

Use this if the native Sentry–GitLab integration is unavailable.
Receives Sentry webhooks, creates GitLab issues, then triggers RootChain.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys

import structlog
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, Response

# Add src to path when running directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rootchain.config import Config
from src.rootchain.orchestrator import run_analysis

log = structlog.get_logger()

app = FastAPI(title="RootChain Webhook Receiver", version="0.1.0")

_config: Config | None = None


def _get_config() -> Config:
    global _config
    if _config is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        _config = Config.from_env()
    return _config


def _verify_sentry_signature(body: bytes, signature: str | None, secret: str) -> bool:
    """Validate the HMAC-SHA256 signature from Sentry."""
    if not signature or not secret:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/health")
async def health() -> dict:  # type: ignore[type-arg]
    return {"status": "ok", "version": "0.1.0"}


@app.post("/webhook/sentry")
async def sentry_webhook(
    request: Request,
    x_sentry_hook_signature: str | None = Header(default=None),
    x_rootchain_secret: str | None = Header(default=None),
) -> Response:
    """Receive a Sentry issue webhook and trigger RootChain analysis."""
    config = _get_config()
    body = await request.body()

    # Validate signature
    secret = config.webhook_secret or x_rootchain_secret or ""
    sig = x_sentry_hook_signature or ""
    if secret and not _verify_sentry_signature(body, sig, secret):
        log.warning("webhook_signature_invalid")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    action = payload.get("action", "")
    if action not in ("created", "triggered"):
        return Response(status_code=204)

    event_data = payload.get("data", {}).get("issue", {})
    if not event_data:
        return Response(status_code=204)

    issue_title = f"[Sentry] {event_data.get('title', 'Unknown error')}"
    issue_description = _build_description(event_data)

    # Create GitLab issue
    import httpx
    async with httpx.AsyncClient(
        base_url=config.gitlab_api_url,
        headers={"PRIVATE-TOKEN": config.gitlab_token, "Content-Type": "application/json"},
    ) as client:
        from urllib.parse import quote
        resp = await client.post(
            f"/projects/{quote(config.project_path, safe='')}/issues",
            json={
                "title": issue_title,
                "description": issue_description,
                "labels": "sentry-alert,Sentry",
            },
        )
        if not resp.is_success:
            log.error("gitlab_issue_creation_failed", status=resp.status_code)
            raise HTTPException(status_code=502, detail="Failed to create GitLab issue")

        issue = resp.json()
        issue_iid = issue["iid"]

    # Trigger RootChain asynchronously (fire and forget — respond quickly to Sentry)
    import asyncio
    asyncio.create_task(
        run_analysis(
            project_path=config.project_path,
            issue_iid=issue_iid,
            issue_title=issue_title,
            issue_description=issue_description,
            issue_labels=["sentry-alert", "Sentry"],
            config=config,
        )
    )

    log.info("webhook_processed", issue_iid=issue_iid, sentry_action=action)
    return Response(status_code=200, content='{"ok": true}', media_type="application/json")


def _build_description(event: dict) -> str:  # type: ignore[type-arg]
    """Build a GitLab issue description from a Sentry webhook event payload."""
    title = event.get("title", "")
    culprit = event.get("culprit", "")
    sentry_url = event.get("permalink", "")
    env = event.get("tags", {}).get("environment", "production")
    times_seen = event.get("times_seen", 0)

    stacktrace = ""
    entries = event.get("entries", [])
    for entry in entries:
        if entry.get("type") == "exception":
            values = entry.get("data", {}).get("values", [])
            for val in values:
                exc_type = val.get("type", "")
                exc_value = val.get("value", "")
                frames = val.get("stacktrace", {}).get("frames", [])
                stacktrace += f"\n{exc_type}: {exc_value}\n\nTraceback (most recent call last):\n"
                for frame in reversed(frames):
                    filename = frame.get("filename", "")
                    lineno = frame.get("lineno", 0)
                    func = frame.get("function", "")
                    stacktrace += f'  File "{filename}", line {lineno}, in {func}\n'

    return f"""## {title}

**Sentry Issue:** {sentry_url}

**Culprit:** `{culprit}`

**Times seen:** {times_seen}
**Environment:** {env}

### Stacktrace

```
{stacktrace.strip()}
```
"""


if __name__ == "__main__":
    cfg = _get_config()
    uvicorn.run(app, host="0.0.0.0", port=cfg.webhook_port)
