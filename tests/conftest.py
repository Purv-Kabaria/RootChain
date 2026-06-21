"""Shared test fixtures for RootChain."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.rootchain.config import Config
from src.rootchain.models import (
    BlameChain,
    BlameEntry,
    Language,
    LinkedIssue,
    MRContext,
    SentryEvent,
    StackFrame,
    SymbolHistory,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def config() -> Config:
    """Minimal config for unit tests — no real env vars needed."""
    return Config(
        gitlab_token="glpat-test-token",
        gitlab_url="https://gitlab.example.com",
        group_path="myorg",
        project_path="myorg/myapp",
        orbit_timeout_seconds=30,
        orbit_max_retries=3,
        orbit_retry_base_seconds=2,
        max_frames=5,
        include_library_frames=False,
        confidence_threshold=0.4,
        recency_weight=0.50,
        depth_weight=0.35,
        blast_weight=0.15,
        recency_half_life_days=30,
        add_label="rootchain-analyzed",
        mention_authors=True,
        mention_reviewers=False,
        max_mention_users=3,
    )


@pytest.fixture()
def python_issue_fixture() -> dict:  # type: ignore[type-arg]
    return json.loads((FIXTURES / "sentry_python.json").read_text())


@pytest.fixture()
def node_issue_fixture() -> dict:  # type: ignore[type-arg]
    return json.loads((FIXTURES / "sentry_node.json").read_text())


@pytest.fixture()
def go_issue_fixture() -> dict:  # type: ignore[type-arg]
    return json.loads((FIXTURES / "sentry_go.json").read_text())


@pytest.fixture()
def minified_js_fixture() -> dict:  # type: ignore[type-arg]
    return json.loads((FIXTURES / "sentry_minified_js.json").read_text())


@pytest.fixture()
def ruby_issue_fixture() -> dict:  # type: ignore[type-arg]
    return json.loads((FIXTURES / "sentry_ruby.json").read_text())


@pytest.fixture()
def java_issue_fixture() -> dict:  # type: ignore[type-arg]
    return json.loads((FIXTURES / "sentry_java.json").read_text())


@pytest.fixture()
def orbit_full_fixture() -> dict:  # type: ignore[type-arg]
    return json.loads((FIXTURES / "orbit_response_full.json").read_text())


@pytest.fixture()
def orbit_empty_fixture() -> dict:  # type: ignore[type-arg]
    return json.loads((FIXTURES / "orbit_response_empty.json").read_text())


@pytest.fixture()
def sample_frame() -> StackFrame:
    return StackFrame(
        file_path="payments/processor.py",
        function_name="processPayment",
        line_number=142,
        language=Language.PYTHON,
        is_library=False,
        frame_depth=1,
        raw_line="payments/processor.py:142 in processPayment",
    )


@pytest.fixture()
def sample_mr() -> MRContext:
    return MRContext(
        iid=342,
        title="Add retry logic to payment processor",
        description="Implements exponential backoff. Closes #89.",
        author_username="alice",
        merged_at=datetime(2024, 1, 11, 14, 23, 0, tzinfo=timezone.utc),
        web_url="https://gitlab.example.com/myorg/myapp/-/merge_requests/342",
        linked_issues=[
            LinkedIssue(
                iid=89,
                title="Add retry logic for gateway timeouts",
                web_url="https://gitlab.example.com/myorg/myapp/-/issues/89",
                state="closed",
            )
        ],
        reviewers=["dave"],
        days_since_merge=4,
    )


@pytest.fixture()
def sample_history(sample_frame: StackFrame, sample_mr: MRContext) -> SymbolHistory:
    return SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[sample_mr],
        caller_count=5,
        orbit_miss=False,
        fallback_used=False,
    )


@pytest.fixture()
def sample_event(sample_frame: StackFrame) -> SentryEvent:
    return SentryEvent(
        error_type="TypeError",
        error_message="'NoneType' object is not subscriptable",
        culprit="payments/processor.py:142 in processPayment",
        environment="production",
        frames=[sample_frame],
        sentry_issue_url="https://sentry.io/organizations/myorg/issues/1234567/",
        raw_frame_count=4,
    )
