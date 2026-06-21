"""All Pydantic v2 data models for RootChain. No imports from other src files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Result type for fallible operations
# ---------------------------------------------------------------------------


@dataclass
class Ok(Generic[T]):
    """Successful result wrapping a value."""

    value: T


@dataclass
class Err:
    """Failed result with diagnostics."""

    message: str
    code: str
    retryable: bool = False


type Result[T] = Ok[T] | Err


# ---------------------------------------------------------------------------
# Language enum
# ---------------------------------------------------------------------------


class Language(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    GO = "go"
    RUBY = "ruby"
    JAVA = "java"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Sentry parsing models
# ---------------------------------------------------------------------------


class StackFrame(BaseModel):
    """A single frame from a Sentry stack trace."""

    model_config = ConfigDict(frozen=True)

    file_path: str
    function_name: str
    line_number: int
    language: Language
    is_library: bool
    frame_depth: int  # 1 = closest to the error
    raw_line: str


class SentryEvent(BaseModel):
    """Parsed Sentry event extracted from a GitLab issue description."""

    model_config = ConfigDict(frozen=True)

    error_type: str
    error_message: str
    culprit: str | None
    environment: str | None
    frames: list[StackFrame]
    sentry_issue_url: str | None
    raw_frame_count: int = 0  # total frames before library filtering


# ---------------------------------------------------------------------------
# Orbit query result models
# ---------------------------------------------------------------------------


class LinkedIssue(BaseModel):
    """A GitLab work item (issue) linked to a merge request."""

    model_config = ConfigDict(frozen=True)

    iid: int
    title: str
    web_url: str
    state: str  # "opened" | "closed"


class VulnerabilityFinding(BaseModel):
    """An active security vulnerability from Orbit's security domain affecting a file."""

    model_config = ConfigDict(frozen=True)

    name: str
    severity: str  # "critical" | "high" | "medium" | "low" | "info" | "unknown"
    state: str     # "detected" | "confirmed" | "dismissed" | "resolved"
    report_type: str  # "sast" | "dast" | "dependency_scanning" | etc.
    web_url: str


class MRContext(BaseModel):
    """A merge request with full context: linked issues, reviewers, recency."""

    model_config = ConfigDict(frozen=True)

    iid: int
    title: str
    description: str
    author_username: str
    merged_at: datetime | None
    web_url: str
    linked_issues: list[LinkedIssue]
    reviewers: list[str]
    days_since_merge: int
    pipeline_status: str | None = None  # "passed" | "failed" | "running" | None


class SymbolHistory(BaseModel):
    """Orbit query result for a single stack frame symbol."""

    model_config = ConfigDict(frozen=True)

    function_name: str
    file_path: str
    recent_mrs: list[MRContext]
    caller_count: int
    orbit_miss: bool  # True when Orbit returned no results at all
    fallback_used: bool  # True when file-level fallback was used instead of definition-level
    security_findings: list[VulnerabilityFinding] = []  # Active CVEs/vulns in this file


# ---------------------------------------------------------------------------
# Blame chain models
# ---------------------------------------------------------------------------


class BlameEntry(BaseModel):
    """One ranked entry in the blame chain, pairing a frame with its Orbit history."""

    model_config = ConfigDict(frozen=True)

    frame: StackFrame
    history: SymbolHistory
    primary_mr: MRContext | None
    confidence: float
    confidence_label: Literal["HIGH", "MEDIUM", "LOW"]
    confidence_reason: str


class BlameChain(BaseModel):
    """The full ranked blame chain for a Sentry event."""

    model_config = ConfigDict(frozen=True)

    entries: list[BlameEntry]
    primary_suspect: BlameEntry | None
    frames_analyzed: int
    frames_total: int
    orbit_misses: int
    generated_at: datetime
