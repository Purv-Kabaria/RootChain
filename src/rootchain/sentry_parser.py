"""Parse stack traces from GitLab issue descriptions.

Handles Sentry, GitLab error tracking, CI failures, crash reports, and manually
pasted tracebacks across Python, Node.js, Go, Ruby, Java, Kotlin, and Rust.
"""

from __future__ import annotations

import re

import structlog

from .config import Config
from .models import Language, SentryEvent, StackFrame

log = structlog.get_logger()

LIBRARY_PREFIXES = (
    # Python
    "site-packages/",
    "/usr/lib/",
    "/usr/local/lib/",
    ".pyenv/",
    "lib/python",
    # Go runtime
    "/usr/local/go/",
    "runtime/",
    "builtin/",
    # JavaScript
    "node_modules/",
    "dist/",
    # Ruby
    "gems/",
    "rubygems/",
    # Java (dot-notation class names AND slash-converted paths)
    "java.",
    "java/",
    "javax.",
    "javax/",
    "sun.",
    "sun/",
    "com.sun.",
    "com/sun/",
    "com.google.",
    "com/google/",
    "org.springframework.",
    "org/springframework/",
    "org.apache.",
    "org/apache/",
    "org.junit.",
    "org/junit/",
    "kotlin.",
    "kotlin/",
    # Rust standard library
    "std::",
    "core::",
    "alloc::",
    "tokio::",
    "hyper::",
    "actix_",
    "futures_",
    # Generic
    "vendor/",
    "/opt/homebrew/",
    "/opt/local/",
)

# Function names that carry no debugging signal
SKIP_FUNCTION_NAMES = frozenset(
    ["<module>", "<anonymous>", "<lambda>", "main", "__main__", ""]
)

_PY_FRAME = re.compile(
    r'File "(?P<path>[^"]+)",\s+line (?P<line>\d+),\s+in (?P<func>\S+)'
)
_PY_ERROR = re.compile(
    r"^(?P<type>[\w.]+(?:Error|Exception|Warning|Interrupt|Exit)):\s*(?P<msg>.+)$"
)
_PY_ERROR_BARE = re.compile(
    r"^(?P<type>[\w.]+(?:Error|Exception|Warning|Interrupt|Exit))\s*$"
)

_NODE_FRAME = re.compile(
    r"at (?P<func>[\w.<>$\[\]]+(?:\s+\[as \w+\])?)\s+\((?P<path>[^:)]+):(?P<line>\d+):\d+\)"
)
_NODE_ANON_FRAME = re.compile(
    r"at (?P<path>[^:)]+\.(?:js|ts|mjs|cjs)):(?P<line>\d+):\d+"
)
_NODE_ERROR = re.compile(
    r"^(?P<type>[\w]+(?:Error|Exception)):\s*(?P<msg>.+)$"
)

_GO_FILE_FRAME = re.compile(
    r"^\s+(?P<path>[^\s]+\.go):(?P<line>\d+)(?:\s+\+0x[0-9a-f]+)?$"
)
_GO_FUNC_FRAME = re.compile(r"^(?P<func>[\w/.()*\[\]]+)\(")
_GO_GOROUTINE = re.compile(r"^goroutine \d+ \[")
_GO_PANIC = re.compile(r"^panic:\s*(?P<msg>.+)$")
_GO_SIGNAL = re.compile(r"^signal \w+: (?P<msg>.+)$")

_RUBY_FRAME = re.compile(
    r"(?P<path>[^:\s][^:]*):(?P<line>\d+):in `(?P<func>[^']+)'"
)
_RUBY_ERROR = re.compile(r"^(?P<type>[\w:]+(?:Error|Exception)):\s*(?P<msg>.+)$")

_JAVA_FRAME = re.compile(
    r"at (?P<class>[\w.$]+)\.(?P<func>[\w<>$]+)\((?P<file>[\w.]+):(?P<line>\d+)\)"
)
_JAVA_CAUSED_BY = re.compile(
    r"^Caused by:\s*(?P<type>[\w.]+(?:Exception|Error)):\s*(?P<msg>.+)$"
)
_JAVA_ERROR = re.compile(r"^(?P<type>[\w.]+(?:Exception|Error)):\s*(?P<msg>.+)$")

# Kotlin: same JVM format as Java, identified by .kt file extension
_KOTLIN_FILE = re.compile(r"\([\w.]+\.kt:\d+\)")

# Rust: two-line frames from RUST_BACKTRACE=full or panic output
_RUST_FUNC_FRAME = re.compile(r"^\s*\d+:\s+(?P<func>[\w::<>,\s\[\]&*+]+?)(?:\s+at\s+|$)")
_RUST_FILE_FRAME = re.compile(r"^\s+at\s+(?P<path>[^:\s]+\.rs):(?P<line>\d+)")
_RUST_PANIC = re.compile(
    r"^thread '.*?' panicked at '(?P<msg>[^']+)',\s*(?P<path>[^:]+\.rs):(?P<line>\d+)"
)
_RUST_PANIC_NEW = re.compile(
    r"^thread '.*?' panicked at (?P<path>[^:\n]+\.rs):(?P<line>\d+):\d+\n(?P<msg>.+)"
)




def _is_library(path: str) -> bool:
    """Return True if the file path belongs to a library or runtime."""
    return any(path.startswith(pfx) or pfx in path for pfx in LIBRARY_PREFIXES)


def _detect_language(description: str) -> Language:
    """Heuristically detect the stack trace language from the issue body."""
    if _PY_FRAME.search(description):
        return Language.PYTHON
    if _NODE_FRAME.search(description):
        return Language.JAVASCRIPT
    if _KOTLIN_FILE.search(description) and _JAVA_FRAME.search(description):
        return Language.KOTLIN
    if _JAVA_FRAME.search(description):
        return Language.JAVA
    if _RUBY_FRAME.search(description) and ":in `" in description:
        return Language.RUBY
    if _GO_GOROUTINE.search(description) or re.search(r"\.go:\d+", description):
        return Language.GO
    if re.search(r"\.rs:\d+", description) or _RUST_PANIC.search(description):
        return Language.RUST
    return Language.UNKNOWN


def _parse_python(
    description: str, config: Config
) -> tuple[str, str, str | None, list[StackFrame], int]:
    """Return (error_type, error_message, culprit, frames, raw_count) for Python traces."""
    error_type = "UnknownError"
    error_message = ""
    culprit: str | None = None

    for line in description.splitlines():
        m = _PY_ERROR.match(line.strip())
        if m:
            error_type, error_message = m.group("type"), m.group("msg")
            break
        m2 = _PY_ERROR_BARE.match(line.strip())
        if m2:
            error_type = m2.group("type")
            break

    raw_frames: list[tuple[str, int, str]] = [
        (m.group("path"), int(m.group("line")), m.group("func"))
        for m in _PY_FRAME.finditer(description)
    ]
    raw_count = len(raw_frames)

    if raw_frames:
        first = raw_frames[0]
        culprit = f"{first[0]}:{first[1]} in {first[2]}"

    frames = _build_frames(raw_frames, Language.PYTHON, config)
    return error_type, error_message, culprit, frames, raw_count


def _parse_node(
    description: str, config: Config
) -> tuple[str, str, str | None, list[StackFrame], int]:
    error_type = "UnknownError"
    error_message = ""
    culprit: str | None = None

    for line in description.splitlines():
        m = _NODE_ERROR.match(line.strip())
        if m:
            error_type, error_message = m.group("type"), m.group("msg")
            break

    raw_frames: list[tuple[str, int, str]] = [
        (m.group("path"), int(m.group("line")), m.group("func").split(" [as ")[0].strip())
        for m in _NODE_FRAME.finditer(description)
    ]

    if not raw_frames:
        raw_frames = [
            (m.group("path"), int(m.group("line")), "<anonymous>")
            for m in _NODE_ANON_FRAME.finditer(description)
        ]

    raw_count = len(raw_frames)

    if raw_frames:
        culprit = f"{raw_frames[0][0]}:{raw_frames[0][1]}"

    frames = _build_frames(raw_frames, Language.JAVASCRIPT, config)
    return error_type, error_message, culprit, frames, raw_count


def _parse_go(
    description: str, config: Config
) -> tuple[str, str, str | None, list[StackFrame], int]:
    error_type = "panic"
    error_message = ""
    culprit: str | None = None

    for line in description.splitlines():
        m = _GO_PANIC.match(line.strip())
        if m:
            error_message = m.group("msg")
            break
        m2 = _GO_SIGNAL.match(line.strip())
        if m2:
            error_type = "signal"
            error_message = m2.group("msg")
            break

    # Strip goroutine header lines, then pair func + file lines
    lines = [ln for ln in description.splitlines() if not _GO_GOROUTINE.match(ln)]

    raw_frames: list[tuple[str, int, str]] = []
    i = 0
    while i < len(lines):
        func_m = _GO_FUNC_FRAME.match(lines[i].strip())
        if func_m and i + 1 < len(lines):
            file_m = _GO_FILE_FRAME.match(lines[i + 1])
            if file_m:
                raw_frames.append(
                    (
                        file_m.group("path"),
                        int(file_m.group("line")),
                        func_m.group("func"),
                    )
                )
                i += 2
                continue
        i += 1

    raw_count = len(raw_frames)

    if raw_frames:
        culprit = f"{raw_frames[0][0]}:{raw_frames[0][1]}"

    frames = _build_frames(raw_frames, Language.GO, config)
    return error_type, error_message, culprit, frames, raw_count


def _parse_ruby(
    description: str, config: Config
) -> tuple[str, str, str | None, list[StackFrame], int]:
    error_type = "UnknownError"
    error_message = ""
    culprit: str | None = None

    for line in description.splitlines():
        m = _RUBY_ERROR.match(line.strip())
        if m:
            error_type, error_message = m.group("type"), m.group("msg")
            break

    raw_frames: list[tuple[str, int, str]] = [
        (m.group("path"), int(m.group("line")), m.group("func"))
        for m in _RUBY_FRAME.finditer(description)
        if ":in `" in m.group(0)
    ]
    raw_count = len(raw_frames)

    if raw_frames:
        culprit = f"{raw_frames[0][0]}:{raw_frames[0][1]}"

    frames = _build_frames(raw_frames, Language.RUBY, config)
    return error_type, error_message, culprit, frames, raw_count


def _parse_java(
    description: str, config: Config
) -> tuple[str, str, str | None, list[StackFrame], int]:
    error_type = "UnknownException"
    error_message = ""
    culprit: str | None = None

    # Use the root cause from the innermost "Caused by:" (last one wins)
    caused_by_error: tuple[str, str] | None = None
    for line in description.splitlines():
        m = _JAVA_CAUSED_BY.match(line.strip())
        if m:
            caused_by_error = (m.group("type"), m.group("msg"))
        elif not caused_by_error:
            m2 = _JAVA_ERROR.match(line.strip())
            if m2:
                error_type = m2.group("type")
                error_message = m2.group("msg")

    if caused_by_error:
        error_type, error_message = caused_by_error

    raw_frames: list[tuple[str, int, str]] = []
    for m in _JAVA_FRAME.finditer(description):
        class_name = m.group("class")
        func = m.group("func")
        file = m.group("file")
        line = int(m.group("line"))
        path = class_name.replace(".", "/") + "/" + file
        raw_frames.append((path, line, f"{class_name}.{func}"))

    raw_count = len(raw_frames)

    if raw_frames:
        culprit = f"{raw_frames[0][0]}:{raw_frames[0][1]}"

    frames = _build_frames(raw_frames, Language.JAVA, config)
    return error_type, error_message, culprit, frames, raw_count


def _parse_kotlin(
    description: str, config: Config
) -> tuple[str, str, str | None, list[StackFrame], int]:
    """Kotlin JVM traces share Java format — re-tag frames with Language.KOTLIN."""
    error_type, error_message, culprit, java_frames, raw_count = _parse_java(
        description, config
    )
    frames = [
        StackFrame(
            file_path=f.file_path,
            function_name=f.function_name,
            line_number=f.line_number,
            language=Language.KOTLIN,
            is_library=f.is_library,
            frame_depth=f.frame_depth,
            raw_line=f.raw_line,
        )
        for f in java_frames
    ]
    return error_type, error_message, culprit, frames, raw_count


def _parse_rust(
    description: str, config: Config
) -> tuple[str, str, str | None, list[StackFrame], int]:
    error_type = "panic"
    error_message = ""
    culprit: str | None = None

    # Extract panic message (two formats: old and Rust 1.73+)
    m = _RUST_PANIC.search(description)
    if m:
        error_message = m.group("msg")
    else:
        m2 = _RUST_PANIC_NEW.search(description)
        if m2:
            error_message = m2.group("msg").strip()

    # Parse two-line frames: "N: func_name\n   at path/file.rs:line"
    lines = description.splitlines()
    raw_frames: list[tuple[str, int, str]] = []
    i = 0
    while i < len(lines):
        func_m = _RUST_FUNC_FRAME.match(lines[i])
        if func_m:
            func = func_m.group("func").strip()
            if i + 1 < len(lines):
                file_m = _RUST_FILE_FRAME.match(lines[i + 1])
                if file_m:
                    raw_frames.append(
                        (file_m.group("path"), int(file_m.group("line")), func)
                    )
                    i += 2
                    continue
        i += 1

    raw_count = len(raw_frames)

    if raw_frames:
        culprit = f"{raw_frames[0][0]}:{raw_frames[0][1]}"

    frames = _build_frames(raw_frames, Language.RUST, config)
    return error_type, error_message, culprit, frames, raw_count


def _build_frames(
    raw: list[tuple[str, int, str]], language: Language, config: Config
) -> list[StackFrame]:
    """Convert raw (path, line, func) tuples into filtered StackFrame objects."""
    frames: list[StackFrame] = []
    depth = 0

    for path, line_no, func in raw:
        is_lib = _is_library(path)
        skip_func = func in SKIP_FUNCTION_NAMES

        if not config.include_library_frames and (is_lib or skip_func):
            continue

        depth += 1
        frames.append(
            StackFrame(
                file_path=path,
                function_name=func,
                line_number=line_no,
                language=language,
                is_library=is_lib,
                frame_depth=depth,
                raw_line=f"{path}:{line_no} in {func}",
            )
        )

        if depth >= config.max_frames:
            break

    return frames



_PARSE_FNS = {
    Language.PYTHON: _parse_python,
    Language.JAVASCRIPT: _parse_node,
    Language.GO: _parse_go,
    Language.RUBY: _parse_ruby,
    Language.JAVA: _parse_java,
    Language.KOTLIN: _parse_kotlin,
    Language.RUST: _parse_rust,
}


class SentryParser:
    """Parse Sentry-formatted GitLab issue descriptions into structured models."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def parse(self, issue_title: str, issue_description: str) -> SentryEvent | None:
        """Parse a GitLab issue into a SentryEvent.

        Returns None if no parseable stack trace is found.
        """
        bound = structlog.get_logger().bind(issue_title=issue_title)

        language = _detect_language(issue_description)
        bound.debug("language_detected", language=language.value)

        sentry_url = self._extract_sentry_url(issue_description)
        environment = self._extract_field(issue_description, "Environment")

        if language in _PARSE_FNS:
            error_type, error_message, culprit, frames, raw_count = _PARSE_FNS[language](
                issue_description, self._config
            )
        else:
            # Generic fallback: try each parser until one yields frames
            error_type, error_message, culprit, frames, raw_count = (
                "UnknownError",
                "",
                None,
                [],
                0,
            )
            for fn in _PARSE_FNS.values():
                et, em, cu, fr, rc = fn(issue_description, self._config)
                if fr:
                    error_type, error_message, culprit, frames, raw_count = (
                        et,
                        em,
                        cu,
                        fr,
                        rc,
                    )
                    break

        if not error_type or error_type in ("UnknownError", "UnknownException"):
            title_type, title_msg = self._parse_title(issue_title)
            if title_type not in ("UnknownError", "UnknownException"):
                error_type = title_type
                if not error_message:
                    error_message = title_msg

        if not frames:
            bound.warning("no_frames_found", language=language.value, raw_count=raw_count)
            return None

        bound.info(
            "sentry_event_parsed",
            error_type=error_type,
            frames_found=len(frames),
            raw_frame_count=raw_count,
            language=language.value,
        )

        return SentryEvent(
            error_type=error_type,
            error_message=error_message,
            culprit=culprit,
            environment=environment,
            frames=frames,
            sentry_issue_url=sentry_url,
            raw_frame_count=raw_count,
        )

    @staticmethod
    def _extract_sentry_url(description: str) -> str | None:
        m = re.search(r"https://sentry\.io/[^\s\)\"]+", description)
        return m.group(0) if m else None

    @staticmethod
    def _extract_field(description: str, field: str) -> str | None:
        m = re.search(rf"\*\*{re.escape(field)}:\*\*\s*(.+)", description)
        return m.group(1).strip() if m else None

    @staticmethod
    def _parse_title(title: str) -> tuple[str, str]:
        """Extract error type and message from '[Sentry] ErrorType: message' title."""
        clean = re.sub(r"^\[(?:Sentry|Error)\]\s*", "", title).strip()
        if ": " in clean:
            parts = clean.split(": ", 1)
            return parts[0].strip(), parts[1].strip()
        return clean, ""

    def debug_parse(self, issue_title: str, issue_description: str) -> dict:  # type: ignore[type-arg]
        """Return a rich debug dict for diagnosing parse failures locally."""
        language = _detect_language(issue_description)
        event = self.parse(issue_title, issue_description)
        return {
            "detected_language": language.value,
            "event": event.model_dump() if event else None,
            "raw_frame_counts": {
                "python": len(_PY_FRAME.findall(issue_description)),
                "node": len(_NODE_FRAME.findall(issue_description)),
                "java": len(_JAVA_FRAME.findall(issue_description)),
                "kotlin": sum(1 for m in _JAVA_FRAME.finditer(issue_description) if _KOTLIN_FILE.search(m.group(0))),
                "ruby": len(_RUBY_FRAME.findall(issue_description)),
                "rust": len(_RUST_FILE_FRAME.findall(issue_description)),
            },
        }
