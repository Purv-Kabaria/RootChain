"""Unit tests for issue_formatter.py."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.rootchain.blame_chain import build_blame_chain
from src.rootchain.issue_formatter import (
    format_all_library_frames_comment,
    format_blame_comment,
    format_no_stack_trace_comment,
)
from src.rootchain.models import SentryEvent


def test_format_blame_comment_has_heading(
    config, sample_event, sample_history
):
    from src.rootchain.blame_chain import build_blame_chain
    chain = build_blame_chain(sample_event, [sample_history], config)
    comment = format_blame_comment(chain, sample_event, config, "myorg/myapp")

    assert "## 🔗 RootChain SDLC Blame Analysis" in comment


def test_format_blame_comment_has_table(
    config, sample_event, sample_history
):
    chain = build_blame_chain(sample_event, [sample_history], config)
    comment = format_blame_comment(chain, sample_event, config, "myorg/myapp")

    assert "### Stack Trace → SDLC Chain" in comment
    assert "| # |" in comment


def test_format_blame_comment_mr_link(
    config, sample_event, sample_history
):
    chain = build_blame_chain(sample_event, [sample_history], config)
    comment = format_blame_comment(chain, sample_event, config, "myorg/myapp")

    # MR iid 342 should be hyperlinked
    assert "[!342]" in comment


def test_format_blame_comment_wi_link(
    config, sample_event, sample_history
):
    chain = build_blame_chain(sample_event, [sample_history], config)
    comment = format_blame_comment(chain, sample_event, config, "myorg/myapp")

    assert "[#89:" in comment


def test_format_blame_comment_has_sub_footer(
    config, sample_event, sample_history
):
    chain = build_blame_chain(sample_event, [sample_history], config)
    comment = format_blame_comment(chain, sample_event, config, "myorg/myapp")

    assert "<sub>" in comment
    assert "RootChain" in comment
    assert "Disable for this project" in comment
    assert "Report false positive" in comment


def test_format_blame_comment_mention_author(
    config, sample_event, sample_history
):
    chain = build_blame_chain(sample_event, [sample_history], config)
    comment = format_blame_comment(chain, sample_event, config, "myorg/myapp")

    assert "@alice" in comment


def test_format_blame_comment_no_mention_when_disabled(
    config, sample_event, sample_history
):
    no_mention_config = config.__class__(
        **{**config.__dict__, "mention_authors": False}
    )
    chain = build_blame_chain(sample_event, [sample_history], no_mention_config)
    comment = format_blame_comment(chain, sample_event, no_mention_config, "myorg/myapp")

    assert "Loop in:" not in comment


def test_format_blame_comment_high_confidence_emoji(
    config, sample_event, sample_history
):
    chain = build_blame_chain(sample_event, [sample_history], config)
    # primary suspect should have high confidence (recent + shallow)
    comment = format_blame_comment(chain, sample_event, config, "myorg/myapp")
    # At least one confidence indicator should be present
    assert any(emoji in comment for emoji in ["🔴", "🟡", "🟢"])


def test_format_no_stack_trace():
    comment = format_no_stack_trace_comment("[Sentry] SomeError: oops")
    assert "No parseable stack trace" in comment
    assert "RootChain" in comment


def test_format_all_library_frames():
    comment = format_all_library_frames_comment(7)
    assert "7" in comment
    assert "library" in comment.lower()
    assert "RootChain" in comment


def test_format_no_primary_suspect(config, sample_frame):
    """When confidence is 0 for all entries, comment should say so."""
    from src.rootchain.models import SymbolHistory, SentryEvent
    miss_history = SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[],
        caller_count=0,
        orbit_miss=True,
        fallback_used=False,
    )
    event = SentryEvent(
        error_type="TypeError",
        error_message="msg",
        culprit=None,
        environment=None,
        frames=[sample_frame],
        sentry_issue_url=None,
    )
    chain = build_blame_chain(event, [miss_history], config)
    comment = format_blame_comment(chain, event, config, "myorg/myapp")

    assert "Could not identify a primary suspect" in comment


def test_mr_link_no_mr_found(config, sample_frame):
    """_mr_link shows '_No MR found_' when orbit_miss is False but recent_mrs is empty."""
    from src.rootchain.models import SymbolHistory, SentryEvent

    no_mr_history = SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[],
        caller_count=0,
        orbit_miss=False,
        fallback_used=False,
    )
    event = SentryEvent(
        error_type="TypeError",
        error_message="msg",
        culprit=None,
        environment=None,
        frames=[sample_frame],
        sentry_issue_url=None,
    )
    chain = build_blame_chain(event, [no_mr_history], config)
    comment = format_blame_comment(chain, event, config, "myorg/myapp")

    assert "_No MR found_" in comment


def test_intent_cell_long_title_truncated(config, sample_frame):
    """MR title longer than 60 chars (no linked issues) is truncated with ellipsis."""
    from datetime import datetime, timezone
    from src.rootchain.models import MRContext, SymbolHistory, SentryEvent

    long_mr = MRContext(
        iid=100,
        title="A" * 70,
        description="",
        author_username="bob",
        merged_at=datetime(2024, 12, 1, tzinfo=timezone.utc),
        web_url="https://gitlab.example.com/myorg/myapp/-/merge_requests/100",
        linked_issues=[],
        reviewers=[],
        days_since_merge=5,
    )
    history = SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[long_mr],
        caller_count=2,
        orbit_miss=False,
        fallback_used=False,
    )
    event = SentryEvent(
        error_type="TypeError",
        error_message="msg",
        culprit=None,
        environment=None,
        frames=[sample_frame],
        sentry_issue_url=None,
    )
    chain = build_blame_chain(event, [history], config)
    comment = format_blame_comment(chain, event, config, "myorg/myapp")

    assert "…" in comment


def test_analysis_no_linked_issues_uses_mr_title(config, sample_frame):
    """When primary MR has no linked issues, analysis uses the MR title."""
    from datetime import datetime, timezone
    from src.rootchain.models import MRContext, SymbolHistory, SentryEvent

    mr_no_issues = MRContext(
        iid=200,
        title="Refactor payment flow",
        description="",
        author_username="eve",
        merged_at=datetime(2024, 12, 1, tzinfo=timezone.utc),
        web_url="https://gitlab.example.com/myorg/myapp/-/merge_requests/200",
        linked_issues=[],
        reviewers=[],
        days_since_merge=5,
    )
    history = SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[mr_no_issues],
        caller_count=3,
        orbit_miss=False,
        fallback_used=False,
    )
    event = SentryEvent(
        error_type="TypeError",
        error_message="msg",
        culprit=None,
        environment=None,
        frames=[sample_frame],
        sentry_issue_url=None,
    )
    chain = build_blame_chain(event, [history], config)
    comment = format_blame_comment(chain, event, config, "myorg/myapp")

    assert "has no linked issue" in comment


def test_analysis_below_threshold_not_all_misses(config, sample_frame):
    """When confidence is below threshold but not orbit_miss, analysis says low confidence."""
    from datetime import datetime, timezone
    from src.rootchain.models import MRContext, SymbolHistory, SentryEvent

    old_mr = MRContext(
        iid=1,
        title="Initial commit",
        description="",
        author_username="charlie",
        merged_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        web_url="https://gitlab.example.com/myorg/myapp/-/merge_requests/1",
        linked_issues=[],
        reviewers=[],
        days_since_merge=1500,
    )
    history = SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[old_mr],
        caller_count=0,
        orbit_miss=False,
        fallback_used=True,
    )
    high_threshold_config = config.__class__(
        **{**config.__dict__, "confidence_threshold": 0.99}
    )
    event = SentryEvent(
        error_type="TypeError",
        error_message="msg",
        culprit=None,
        environment=None,
        frames=[sample_frame],
        sentry_issue_url=None,
    )
    chain = build_blame_chain(event, [history], high_threshold_config)
    comment = format_blame_comment(chain, event, high_threshold_config, "myorg/myapp")

    assert "could not identify a primary suspect" in comment.lower()
    assert "could not find Orbit data" not in comment


def test_mention_reviewers_included(config, sample_event, sample_history):
    """When mention_reviewers=True, reviewer usernames appear in the comment."""
    reviewer_config = config.__class__(
        **{**config.__dict__, "mention_reviewers": True}
    )
    chain = build_blame_chain(sample_event, [sample_history], reviewer_config)
    comment = format_blame_comment(chain, sample_event, reviewer_config, "myorg/myapp")

    assert "@dave" in comment


def test_pipeline_status_badge_passed_in_mr_link(config, sample_frame, sample_event):
    """pipeline_status='passed' shows ✅ CI passed badge in the MR link column."""
    from src.rootchain.models import MRContext, SymbolHistory

    mr_with_pipeline = MRContext(
        iid=342,
        title="Add retry logic",
        description="",
        author_username="alice",
        merged_at=datetime(2024, 1, 11, 14, 23, 0, tzinfo=timezone.utc),
        web_url="https://gitlab.example.com/myorg/myapp/-/merge_requests/342",
        linked_issues=[],
        reviewers=[],
        days_since_merge=4,
        pipeline_status="passed",
    )
    history = SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[mr_with_pipeline],
        caller_count=3,
        orbit_miss=False,
        fallback_used=False,
    )
    chain = build_blame_chain(sample_event, [history], config)
    comment = format_blame_comment(chain, sample_event, config, "myorg/myapp")

    assert "✅ CI passed" in comment


def test_pipeline_status_badge_failed(config, sample_frame, sample_event):
    """pipeline_status='failed' shows ❌ CI failed badge."""
    from src.rootchain.models import MRContext, SymbolHistory

    mr_failed = MRContext(
        iid=342,
        title="Risky refactor",
        description="",
        author_username="bob",
        merged_at=datetime(2024, 1, 11, 14, 23, 0, tzinfo=timezone.utc),
        web_url="https://gitlab.example.com/myorg/myapp/-/merge_requests/342",
        linked_issues=[],
        reviewers=[],
        days_since_merge=4,
        pipeline_status="failed",
    )
    history = SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[mr_failed],
        caller_count=2,
        orbit_miss=False,
        fallback_used=False,
    )
    chain = build_blame_chain(sample_event, [history], config)
    comment = format_blame_comment(chain, sample_event, config, "myorg/myapp")

    assert "❌ CI failed" in comment


def test_pipeline_status_none_no_badge(config, sample_event, sample_history):
    """When pipeline_status is None, no CI badge appears in the comment."""
    chain = build_blame_chain(sample_event, [sample_history], config)
    comment = format_blame_comment(chain, sample_event, config, "myorg/myapp")

    assert "CI passed" not in comment
    assert "CI failed" not in comment


def test_security_section_shown_when_findings_present(config, sample_frame, sample_event):
    """When SymbolHistory has security_findings, the Security Context section appears."""
    from src.rootchain.models import MRContext, SymbolHistory, VulnerabilityFinding

    mr = MRContext(
        iid=342,
        title="Add retry logic",
        description="",
        author_username="alice",
        merged_at=datetime(2024, 1, 11, 14, 23, 0, tzinfo=timezone.utc),
        web_url="https://gitlab.example.com/myorg/myapp/-/merge_requests/342",
        linked_issues=[],
        reviewers=[],
        days_since_merge=4,
    )
    vuln = VulnerabilityFinding(
        name="SQL Injection in processPayment",
        severity="critical",
        state="detected",
        report_type="sast",
        web_url="https://gitlab.example.com/myorg/myapp/-/security/vulnerabilities/1",
    )
    history = SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[mr],
        caller_count=5,
        orbit_miss=False,
        fallback_used=False,
        security_findings=[vuln],
    )
    chain = build_blame_chain(sample_event, [history], config)
    comment = format_blame_comment(chain, sample_event, config, "myorg/myapp")

    assert "### ⚠️ Security Context" in comment
    assert "SQL Injection in processPayment" in comment
    assert "CRITICAL" in comment
    assert "SAST" in comment


def test_security_section_absent_when_no_findings(config, sample_event, sample_history):
    """When no security_findings, the Security Context section does not appear."""
    chain = build_blame_chain(sample_event, [sample_history], config)
    comment = format_blame_comment(chain, sample_event, config, "myorg/myapp")

    assert "### ⚠️ Security Context" not in comment


# ---------------------------------------------------------------------------
# _error_type_hint
# ---------------------------------------------------------------------------


def test_error_type_hint_null(config, sample_frame, sample_history):
    """NullPointerException triggers the null/nil hint."""
    from src.rootchain.models import SentryEvent
    event = SentryEvent(
        error_type="NullPointerException",
        error_message="null",
        culprit=None, environment=None,
        frames=[sample_frame], sentry_issue_url=None,
    )
    chain = build_blame_chain(event, [sample_history], config)
    comment = format_blame_comment(chain, event, config, "myorg/myapp")
    assert "nil/null dereference" in comment


def test_error_type_hint_index(config, sample_frame, sample_history):
    """IndexError triggers boundary condition hint."""
    from src.rootchain.models import SentryEvent
    event = SentryEvent(
        error_type="IndexError",
        error_message="list index out of range",
        culprit=None, environment=None,
        frames=[sample_frame], sentry_issue_url=None,
    )
    chain = build_blame_chain(event, [sample_history], config)
    comment = format_blame_comment(chain, event, config, "myorg/myapp")
    assert "boundary condition" in comment


def test_error_type_hint_timeout(config, sample_frame, sample_history):
    """TimeoutError triggers I/O hot-path hint."""
    from src.rootchain.models import SentryEvent
    event = SentryEvent(
        error_type="TimeoutError",
        error_message="timed out",
        culprit=None, environment=None,
        frames=[sample_frame], sentry_issue_url=None,
    )
    chain = build_blame_chain(event, [sample_history], config)
    comment = format_blame_comment(chain, event, config, "myorg/myapp")
    assert "timeout budget" in comment


def test_error_type_hint_permission(config, sample_frame, sample_history):
    """PermissionError triggers auth guard hint."""
    from src.rootchain.models import SentryEvent
    event = SentryEvent(
        error_type="PermissionError",
        error_message="access denied",
        culprit=None, environment=None,
        frames=[sample_frame], sentry_issue_url=None,
    )
    chain = build_blame_chain(event, [sample_history], config)
    comment = format_blame_comment(chain, event, config, "myorg/myapp")
    assert "auth guard" in comment


def test_error_type_hint_memory(config, sample_frame, sample_history):
    """OOMError triggers allocation hint."""
    from src.rootchain.models import SentryEvent
    event = SentryEvent(
        error_type="OOMError",
        error_message="out of memory",
        culprit=None, environment=None,
        frames=[sample_frame], sentry_issue_url=None,
    )
    chain = build_blame_chain(event, [sample_history], config)
    comment = format_blame_comment(chain, event, config, "myorg/myapp")
    assert "allocation" in comment


def test_error_type_hint_panic(config, sample_frame, sample_history):
    """panic triggers unsafe blocks hint."""
    from src.rootchain.models import SentryEvent
    event = SentryEvent(
        error_type="panic",
        error_message="segfault",
        culprit=None, environment=None,
        frames=[sample_frame], sentry_issue_url=None,
    )
    chain = build_blame_chain(event, [sample_history], config)
    comment = format_blame_comment(chain, event, config, "myorg/myapp")
    assert "unsafe block" in comment


def test_error_type_hint_generic(config, sample_frame, sample_history):
    """Unknown error type uses generic fallback hint."""
    from src.rootchain.models import SentryEvent
    event = SentryEvent(
        error_type="CustomBusinessError",
        error_message="something weird",
        culprit=None, environment=None,
        frames=[sample_frame], sentry_issue_url=None,
    )
    chain = build_blame_chain(event, [sample_history], config)
    comment = format_blame_comment(chain, event, config, "myorg/myapp")
    assert "CustomBusinessError" in comment
