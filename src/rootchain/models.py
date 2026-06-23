"""All Pydantic v2 data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Generic, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


@dataclass
class Ok(Generic[T]):
    value: T


@dataclass
class Err:
    message: str
    code: str
    retryable: bool = False


Result: TypeAlias = Ok[T] | Err


class Language(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    GO = "go"
    RUBY = "ruby"
    JAVA = "java"
    KOTLIN = "kotlin"
    RUST = "rust"
    UNKNOWN = "unknown"


class StackFrame(BaseModel):
    model_config = ConfigDict(frozen=True)

    file_path: str
    function_name: str
    line_number: int
    language: Language
    is_library: bool
    frame_depth: int  # 1 = closest to the error
    raw_line: str


class SentryEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    error_type: str
    error_message: str
    culprit: str | None
    environment: str | None
    frames: list[StackFrame]
    sentry_issue_url: str | None
    raw_frame_count: int = 0


class LinkedIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    iid: int
    title: str
    web_url: str
    state: str  # "opened" | "closed"


class VulnerabilityFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    severity: str  # "critical" | "high" | "medium" | "low" | "info" | "unknown"
    state: str     # "detected" | "confirmed" | "dismissed" | "resolved"
    report_type: str
    web_url: str


class MRContext(BaseModel):
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
    model_config = ConfigDict(frozen=True)

    function_name: str
    file_path: str
    recent_mrs: list[MRContext]
    caller_count: int
    orbit_miss: bool
    fallback_used: bool
    security_findings: list[VulnerabilityFinding] = []


class BlameEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    frame: StackFrame
    history: SymbolHistory
    primary_mr: MRContext | None
    confidence: float
    confidence_label: Literal["HIGH", "MEDIUM", "LOW"]
    confidence_reason: str


class BlameChain(BaseModel):
    model_config = ConfigDict(frozen=True)

    entries: list[BlameEntry]
    primary_suspect: BlameEntry | None
    frames_analyzed: int
    frames_total: int
    orbit_misses: int
    generated_at: datetime
