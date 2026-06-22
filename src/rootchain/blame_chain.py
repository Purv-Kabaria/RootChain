"""Build and score the blame chain from Orbit symbol histories."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from .config import Config
from .models import (
    BlameChain,
    BlameEntry,
    MRContext,
    SentryEvent,
    StackFrame,
    SymbolHistory,
)

log = structlog.get_logger()




def calculate_confidence(
    frame: StackFrame,
    history: SymbolHistory,
    config: Config,
) -> tuple[float, str]:
    """Compute a 0.0–1.0 confidence score for a blame entry.

    Returns (score, human_readable_reason).
    """
    if history.orbit_miss:
        return 0.0, "No Orbit data available"

    primary_mr = history.recent_mrs[0] if history.recent_mrs else None
    if primary_mr is None:
        return 0.0, "No MR history found"

    days_since = primary_mr.days_since_merge
    half_life = config.recency_half_life_days
    recency = 1.0 / (1.0 + days_since / half_life)

    depth = 1.0 / frame.frame_depth
    blast = min(history.caller_count / 10.0, 1.0)

    score = (
        recency * config.recency_weight
        + depth * config.depth_weight
        + blast * config.blast_weight
    )

    if history.fallback_used:
        score *= 0.7

    reason = (
        f"MR merged {days_since}d ago (recency={recency:.2f}), "
        f"frame depth {frame.frame_depth} (depth={depth:.2f}), "
        f"{history.caller_count} callers (blast={blast:.2f})"
    )
    if history.fallback_used:
        reason += " [file-level fallback, ×0.7]"

    return round(score, 3), reason


def _confidence_label(score: float) -> str:
    if score >= 0.7:
        return "HIGH"
    if score >= 0.4:
        return "MEDIUM"
    return "LOW"




def _deduplicate_entries(entries: list[BlameEntry]) -> list[BlameEntry]:
    """When two entries reference the same MR iid, keep the higher-confidence one."""
    seen: dict[int, BlameEntry] = {}
    no_mr: list[BlameEntry] = []

    for entry in entries:
        if entry.primary_mr is None:
            no_mr.append(entry)
            continue
        mr_iid = entry.primary_mr.iid
        if mr_iid not in seen or entry.confidence > seen[mr_iid].confidence:
            seen[mr_iid] = entry

    deduped = list(seen.values()) + no_mr
    return sorted(deduped, key=lambda e: e.confidence, reverse=True)




def build_blame_chain(
    event: SentryEvent,
    histories: list[SymbolHistory],
    config: Config,
) -> BlameChain:
    """Construct a ranked BlameChain from a SentryEvent and its Orbit histories.

    histories must be in the same order as event.frames.
    """
    if len(event.frames) != len(histories):
        raise ValueError(
            f"frames ({len(event.frames)}) and histories ({len(histories)}) must have the same length"
        )

    entries: list[BlameEntry] = []

    for frame, history in zip(event.frames, histories):
        confidence, reason = calculate_confidence(frame, history, config)
        label = _confidence_label(confidence)
        primary_mr: MRContext | None = history.recent_mrs[0] if history.recent_mrs else None

        entries.append(
            BlameEntry(
                frame=frame,
                history=history,
                primary_mr=primary_mr,
                confidence=confidence,
                confidence_label=label,  # type: ignore[arg-type]
                confidence_reason=reason,
            )
        )

        log.debug(
            "blame_entry_scored",
            function_name=frame.function_name,
            confidence=confidence,
            label=label,
            orbit_miss=history.orbit_miss,
        )

    deduped = _deduplicate_entries(entries)

    primary_suspect: BlameEntry | None = None
    for entry in deduped:
        if entry.confidence >= config.confidence_threshold:
            primary_suspect = entry
            break

    orbit_misses = sum(1 for h in histories if h.orbit_miss)

    log.info(
        "blame_chain_built",
        entries=len(deduped),
        primary_suspect=primary_suspect.primary_mr.iid if (primary_suspect and primary_suspect.primary_mr) else None,
        orbit_misses=orbit_misses,
    )

    return BlameChain(
        entries=deduped,
        primary_suspect=primary_suspect,
        frames_analyzed=len(event.frames),
        frames_total=event.raw_frame_count or len(event.frames),
        orbit_misses=orbit_misses,
        generated_at=datetime.now(timezone.utc),
    )
