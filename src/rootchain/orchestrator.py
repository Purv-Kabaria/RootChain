"""Entry point: wire all modules together. Contains no business logic.

All business logic lives in the individual modules this file calls.
"""

from __future__ import annotations

import asyncio
import sys

import structlog

from .blame_chain import build_blame_chain
from .config import Config
from .gitlab_client import GitLabClient
from .issue_formatter import (
    format_all_library_frames_comment,
    format_blame_comment,
    format_no_stack_trace_comment,
)
from .models import Err, Ok
from .orbit_client import OrbitClient
from .sentry_parser import SentryParser

log = structlog.get_logger()


def _configure_logging(config: Config) -> None:
    import logging

    import structlog

    level = getattr(logging, config.log_level, logging.INFO)
    logging.basicConfig(level=level, stream=sys.stderr)

    processors: list = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if config.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


async def run_analysis(
    *,
    project_path: str,
    issue_iid: int,
    issue_title: str,
    issue_description: str,
    issue_labels: list[str],
    config: Config,
    dry_run: bool = False,
) -> None:
    """Run the full RootChain analysis pipeline for a single GitLab issue.

    dry_run=True parses, queries Orbit, builds the comment, but does NOT
    post to GitLab. The rendered comment is written to stdout instead.
    """
    bound_log = log.bind(project_path=project_path, issue_iid=issue_iid, dry_run=dry_run)

    # Idempotency guard
    if config.add_label in issue_labels:
        bound_log.info("already_analyzed_skipping")
        return

    async with GitLabClient(config) as gitlab:
        async with OrbitClient(config) as orbit:
            await _analyze(
                project_path=project_path,
                issue_iid=issue_iid,
                issue_title=issue_title,
                issue_description=issue_description,
                config=config,
                gitlab=gitlab,
                orbit=orbit,
                bound_log=bound_log,
                dry_run=dry_run,
            )


async def _analyze(
    *,
    project_path: str,
    issue_iid: int,
    issue_title: str,
    issue_description: str,
    config: Config,
    gitlab: GitLabClient,
    orbit: OrbitClient,
    bound_log,  # type: ignore[type-arg]
    dry_run: bool = False,
) -> None:
    parser = SentryParser(config)
    event = parser.parse(issue_title, issue_description)

    if event is None:
        bound_log.warning("no_parseable_stack_trace")
        comment = format_no_stack_trace_comment(issue_title)
        if dry_run:
            print(comment)
            return
        await _post_and_label(gitlab, project_path, issue_iid, comment, config, bound_log)
        return

    # Filter: if all frames are library code (shouldn't happen after parser filtering, but guard)
    if not event.frames:
        bound_log.warning("all_frames_filtered")
        raw_count = issue_description.count("File \"")
        comment = format_all_library_frames_comment(raw_count)
        if dry_run:
            print(comment)
            return
        await _post_and_label(gitlab, project_path, issue_iid, comment, config, bound_log)
        return

    bound_log.info("frames_to_analyze", count=len(event.frames))

    histories = await orbit.get_symbol_histories(list(event.frames))

    chain = build_blame_chain(event, histories, config)

    comment = format_blame_comment(chain, event, config, project_path)

    if dry_run:
        print(comment)
        bound_log.info("dry_run_complete", frames_analyzed=chain.frames_analyzed)
        return

    await _post_and_label(gitlab, project_path, issue_iid, comment, config, bound_log)


async def _post_and_label(
    gitlab: GitLabClient,
    project_path: str,
    issue_iid: int,
    comment: str,
    config: Config,
    bound_log,  # type: ignore[type-arg]
) -> None:
    note_result = await gitlab.add_note(project_path, issue_iid, comment)
    match note_result:
        case Ok(value=note_id):
            bound_log.info("note_posted", note_id=note_id)
        case Err(message=msg, code=code):
            bound_log.error("note_post_failed", message=msg, code=code)
            return

    label_result = await gitlab.add_label(project_path, issue_iid, config.add_label)
    match label_result:
        case Ok():
            bound_log.info("label_added", label=config.add_label)
        case Err(message=msg, code=code):
            bound_log.error("label_add_failed", message=msg, code=code)


def main() -> None:
    """CLI entry point for standalone operation (not inside Duo flow)."""
    import argparse
    import os

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="RootChain — trace Sentry errors to SDLC origin")
    parser.add_argument("--project-path", required=True)
    parser.add_argument("--issue-iid", type=int, required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and query Orbit but print the comment to stdout instead of posting it",
    )
    args = parser.parse_args()

    config = Config.from_env()
    _configure_logging(config)

    # Fetch issue from GitLab to get title, description, labels
    async def _fetch_and_run() -> None:
        async with GitLabClient(config) as gitlab:
            import httpx
            async with httpx.AsyncClient(
                base_url=config.gitlab_api_url,
                headers={"PRIVATE-TOKEN": config.gitlab_token},
            ) as client:
                from urllib.parse import quote
                resp = await client.get(
                    f"/projects/{quote(args.project_path, safe='')}/issues/{args.issue_iid}"
                )
                resp.raise_for_status()
                issue = resp.json()

        await run_analysis(
            project_path=args.project_path,
            issue_iid=args.issue_iid,
            issue_title=issue["title"],
            issue_description=issue.get("description", ""),
            issue_labels=issue.get("labels", []),
            config=config,
            dry_run=args.dry_run,
        )

    asyncio.run(_fetch_and_run())


if __name__ == "__main__":
    main()
