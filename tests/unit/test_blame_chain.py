"""Unit tests for blame_chain.py."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.rootchain.blame_chain import (
    _confidence_label,
    _deduplicate_entries,
    build_blame_chain,
    calculate_confidence,
)
from src.rootchain.models import (
    BlameEntry,
    Language,
    LinkedIssue,
    MRContext,
    SentryEvent,
    StackFrame,
    SymbolHistory,
)


# ---------------------------------------------------------------------------
# calculate_confidence
# ---------------------------------------------------------------------------


def test_confidence_orbit_miss(config, sample_frame):
    history = SymbolHistory(
        function_name="fn",
        file_path="f.py",
        recent_mrs=[],
        caller_count=0,
        orbit_miss=True,
        fallback_used=False,
    )
    score, reason = calculate_confidence(sample_frame, history, config)
    assert score == 0.0
    assert "No Orbit data" in reason


def test_confidence_no_mr(config, sample_frame):
    history = SymbolHistory(
        function_name="fn",
        file_path="f.py",
        recent_mrs=[],
        caller_count=0,
        orbit_miss=False,
        fallback_used=False,
    )
    score, reason = calculate_confidence(sample_frame, history, config)
    assert score == 0.0
    assert "No MR history" in reason


def test_confidence_recent_mr_high(config, sample_frame, sample_mr):
    """Very recent MR at frame depth 1 with callers → high confidence."""
    recent_mr = sample_mr.model_copy(update={"days_since_merge": 1})
    history = SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[recent_mr],
        caller_count=8,
        orbit_miss=False,
        fallback_used=False,
    )
    score, _ = calculate_confidence(sample_frame, history, config)
    assert score >= 0.7


def test_confidence_fallback_penalty(config, sample_frame, sample_mr):
    """File-level fallback should reduce confidence by 30%."""
    mr = sample_mr.model_copy(update={"days_since_merge": 1})
    history_primary = SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[mr],
        caller_count=8,
        orbit_miss=False,
        fallback_used=False,
    )
    history_fallback = SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[mr],
        caller_count=8,
        orbit_miss=False,
        fallback_used=True,
    )
    score_primary, _ = calculate_confidence(sample_frame, history_primary, config)
    score_fallback, _ = calculate_confidence(sample_frame, history_fallback, config)
    assert abs(score_fallback - score_primary * 0.7) < 0.001


def test_confidence_deep_frame_lower(config, sample_mr):
    """Frame at depth 5 should have lower depth score than depth 1."""
    frame1 = StackFrame(
        file_path="f.py",
        function_name="fn",
        line_number=10,
        language=Language.PYTHON,
        is_library=False,
        frame_depth=1,
        raw_line="f.py:10 in fn",
    )
    frame5 = frame1.model_copy(update={"frame_depth": 5})

    mr = sample_mr.model_copy(update={"days_since_merge": 1})
    hist = SymbolHistory(
        function_name="fn",
        file_path="f.py",
        recent_mrs=[mr],
        caller_count=5,
        orbit_miss=False,
        fallback_used=False,
    )

    score1, _ = calculate_confidence(frame1, hist, config)
    score5, _ = calculate_confidence(frame5, hist, config)
    assert score1 > score5


def test_confidence_reason_contains_days(config, sample_frame, sample_mr):
    history = SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[sample_mr],
        caller_count=5,
        orbit_miss=False,
        fallback_used=False,
    )
    _, reason = calculate_confidence(sample_frame, history, config)
    assert "MR merged" in reason
    assert "d ago" in reason


# ---------------------------------------------------------------------------
# _confidence_label
# ---------------------------------------------------------------------------


def test_label_high():
    assert _confidence_label(0.75) == "HIGH"


def test_label_medium():
    assert _confidence_label(0.55) == "MEDIUM"
    assert _confidence_label(0.40) == "MEDIUM"


def test_label_low():
    assert _confidence_label(0.39) == "LOW"
    assert _confidence_label(0.0) == "LOW"


# ---------------------------------------------------------------------------
# _deduplicate_entries
# ---------------------------------------------------------------------------


def _make_entry(mr_iid: int, confidence: float, sample_frame, sample_mr) -> BlameEntry:
    mr = sample_mr.model_copy(update={"iid": mr_iid})
    history = SymbolHistory(
        function_name="fn",
        file_path="f.py",
        recent_mrs=[mr],
        caller_count=0,
        orbit_miss=False,
        fallback_used=False,
    )
    return BlameEntry(
        frame=sample_frame,
        history=history,
        primary_mr=mr,
        confidence=confidence,
        confidence_label="MEDIUM",
        confidence_reason="test",
    )


def test_dedup_removes_lower_confidence(sample_frame, sample_mr):
    entry_high = _make_entry(342, 0.8, sample_frame, sample_mr)
    entry_low = _make_entry(342, 0.5, sample_frame, sample_mr)

    deduped = _deduplicate_entries([entry_low, entry_high])
    assert len(deduped) == 1
    assert deduped[0].confidence == 0.8


def test_dedup_keeps_different_mrs(sample_frame, sample_mr):
    entry1 = _make_entry(342, 0.8, sample_frame, sample_mr)
    entry2 = _make_entry(301, 0.5, sample_frame, sample_mr)

    deduped = _deduplicate_entries([entry1, entry2])
    assert len(deduped) == 2


def test_dedup_sorted_descending(sample_frame, sample_mr):
    entries = [
        _make_entry(1, 0.3, sample_frame, sample_mr),
        _make_entry(2, 0.9, sample_frame, sample_mr),
        _make_entry(3, 0.6, sample_frame, sample_mr),
    ]
    deduped = _deduplicate_entries(entries)
    confidences = [e.confidence for e in deduped]
    assert confidences == sorted(confidences, reverse=True)


# ---------------------------------------------------------------------------
# build_blame_chain
# ---------------------------------------------------------------------------


def test_build_chain_primary_suspect(config, sample_event, sample_history):
    chain = build_blame_chain(sample_event, [sample_history], config)
    assert chain.primary_suspect is not None
    assert chain.frames_analyzed == 1


def test_build_chain_orbit_miss_no_suspect(config, sample_event):
    miss_history = SymbolHistory(
        function_name="processPayment",
        file_path="payments/processor.py",
        recent_mrs=[],
        caller_count=0,
        orbit_miss=True,
        fallback_used=False,
    )
    chain = build_blame_chain(sample_event, [miss_history], config)
    assert chain.primary_suspect is None
    assert chain.orbit_misses == 1


def test_build_chain_below_threshold(config, sample_frame, sample_mr):
    # MR merged 500 days ago at depth 5 → very low confidence
    old_mr = sample_mr.model_copy(update={"days_since_merge": 500})
    deep_frame = sample_frame.model_copy(update={"frame_depth": 5})
    history = SymbolHistory(
        function_name=deep_frame.function_name,
        file_path=deep_frame.file_path,
        recent_mrs=[old_mr],
        caller_count=0,
        orbit_miss=False,
        fallback_used=False,
    )
    event = SentryEvent(
        error_type="TypeError",
        error_message="msg",
        culprit=None,
        environment=None,
        frames=[deep_frame],
        sentry_issue_url=None,
    )
    chain = build_blame_chain(event, [history], config)
    assert chain.primary_suspect is None


def test_build_chain_deduplicates(config, sample_frame, sample_mr):
    """Two frames pointing to same MR should produce one chain entry."""
    frame2 = sample_frame.model_copy(
        update={"function_name": "otherFn", "frame_depth": 2}
    )
    event = SentryEvent(
        error_type="TypeError",
        error_message="msg",
        culprit=None,
        environment=None,
        frames=[sample_frame, frame2],
        sentry_issue_url=None,
    )
    history = SymbolHistory(
        function_name=sample_frame.function_name,
        file_path=sample_frame.file_path,
        recent_mrs=[sample_mr],
        caller_count=5,
        orbit_miss=False,
        fallback_used=False,
    )
    history2 = history.model_copy(update={"function_name": "otherFn"})

    chain = build_blame_chain(event, [history, history2], config)
    mr_iids = [e.primary_mr.iid for e in chain.entries if e.primary_mr]
    assert len(mr_iids) == len(set(mr_iids))
