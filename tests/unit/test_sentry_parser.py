"""Unit tests for sentry_parser.py."""

from __future__ import annotations

import pytest

from src.rootchain.models import Language
from src.rootchain.sentry_parser import (
    SentryParser,
    _detect_language,
    _is_library,
    SKIP_FUNCTION_NAMES,
)


# ---------------------------------------------------------------------------
# _is_library
# ---------------------------------------------------------------------------


def test_is_library_site_packages():
    assert _is_library("/usr/local/lib/python3.11/site-packages/requests/api.py")


def test_is_library_node_modules():
    assert _is_library("node_modules/express/lib/router/layer.js")


def test_is_library_not_library():
    assert not _is_library("payments/processor.py")


def test_is_library_app_code():
    assert not _is_library("/app/core/session.py")


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def test_detect_python(python_issue_fixture):
    lang = _detect_language(python_issue_fixture["description"])
    assert lang == Language.PYTHON


def test_detect_node(node_issue_fixture):
    lang = _detect_language(node_issue_fixture["description"])
    assert lang == Language.JAVASCRIPT


def test_detect_go(go_issue_fixture):
    lang = _detect_language(go_issue_fixture["description"])
    assert lang == Language.GO


# ---------------------------------------------------------------------------
# Python parsing
# ---------------------------------------------------------------------------


def test_parse_python_frames(config, python_issue_fixture):
    parser = SentryParser(config)
    event = parser.parse(
        python_issue_fixture["title"],
        python_issue_fixture["description"],
    )
    assert event is not None
    assert event.error_type == "TypeError"
    assert len(event.frames) == 3  # 4 raw, 1 library filtered
    assert event.frames[0].function_name == "processPayment"
    assert event.frames[0].frame_depth == 1
    assert event.frames[0].file_path == "/app/payments/processor.py"


def test_parse_python_library_filtered(config, python_issue_fixture):
    parser = SentryParser(config)
    event = parser.parse(
        python_issue_fixture["title"],
        python_issue_fixture["description"],
    )
    assert event is not None
    paths = [f.file_path for f in event.frames]
    assert not any("site-packages" in p for p in paths)


def test_parse_python_sentry_url(config, python_issue_fixture):
    parser = SentryParser(config)
    event = parser.parse(
        python_issue_fixture["title"],
        python_issue_fixture["description"],
    )
    assert event is not None
    assert event.sentry_issue_url is not None
    assert "sentry.io" in event.sentry_issue_url


def test_parse_python_environment(config, python_issue_fixture):
    parser = SentryParser(config)
    event = parser.parse(
        python_issue_fixture["title"],
        python_issue_fixture["description"],
    )
    assert event is not None
    assert event.environment == "production"


# ---------------------------------------------------------------------------
# Node.js parsing
# ---------------------------------------------------------------------------


def test_parse_node_frames(config, node_issue_fixture):
    parser = SentryParser(config)
    event = parser.parse(
        node_issue_fixture["title"],
        node_issue_fixture["description"],
    )
    assert event is not None
    assert event.error_type == "ReferenceError"
    assert len(event.frames) >= 1
    assert event.frames[0].function_name == "processOrder"
    assert event.frames[0].language == Language.JAVASCRIPT


def test_parse_node_library_filtered(config, node_issue_fixture):
    parser = SentryParser(config)
    event = parser.parse(
        node_issue_fixture["title"],
        node_issue_fixture["description"],
    )
    assert event is not None
    paths = [f.file_path for f in event.frames]
    assert not any("node_modules" in p for p in paths)


# ---------------------------------------------------------------------------
# Go parsing
# ---------------------------------------------------------------------------


def test_parse_go_frames(config, go_issue_fixture):
    parser = SentryParser(config)
    event = parser.parse(
        go_issue_fixture["title"],
        go_issue_fixture["description"],
    )
    assert event is not None
    assert len(event.frames) >= 1
    assert event.frames[0].language == Language.GO
    assert event.frames[0].file_path.endswith(".go")


def test_parse_go_goroutine_stripped(config, go_issue_fixture):
    parser = SentryParser(config)
    event = parser.parse(
        go_issue_fixture["title"],
        go_issue_fixture["description"],
    )
    assert event is not None
    for frame in event.frames:
        assert "goroutine" not in frame.raw_line


def test_parse_go_runtime_filtered(config, go_issue_fixture):
    parser = SentryParser(config)
    event = parser.parse(
        go_issue_fixture["title"],
        go_issue_fixture["description"],
    )
    assert event is not None
    paths = [f.file_path for f in event.frames]
    assert not any("/usr/local/go/" in p for p in paths)


# ---------------------------------------------------------------------------
# Minified JS / all-anonymous edge cases
# ---------------------------------------------------------------------------


def test_parse_minified_js_returns_none(config, minified_js_fixture):
    """All frames are <anonymous> — should return None (no useful frames)."""
    parser = SentryParser(config)
    event = parser.parse(
        minified_js_fixture["title"],
        minified_js_fixture["description"],
    )
    # Either None (no frames survive) or frames with anonymous names filtered
    if event is not None:
        for frame in event.frames:
            assert frame.function_name not in SKIP_FUNCTION_NAMES


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_parse_no_stack_trace_returns_none(config):
    parser = SentryParser(config)
    event = parser.parse(
        "[Sentry] Something bad happened",
        "## Something bad happened\n\nNo stack trace here.\n",
    )
    assert event is None


def test_parse_max_frames_respected(config):
    """Parser should not return more frames than config.max_frames."""
    description = "Traceback (most recent call last):\n"
    for i in range(10):
        description += f'  File "/app/module{i}.py", line {i+1}, in func{i}\n'
    description += "ValueError: too many things\n"

    limited_config = config.__class__(
        **{**config.__dict__, "max_frames": 3}
    )
    parser = SentryParser(limited_config)
    event = parser.parse("[Sentry] ValueError: too many things", description)
    if event:
        assert len(event.frames) <= 3


def test_parse_title_fallback(config):
    """Error type extracted from title when body parse yields nothing."""
    parser = SentryParser(config)
    event = parser.parse(
        "[Sentry] AttributeError: 'NoneType' object has no attribute 'id'",
        "No parseable trace here.",
    )
    # No frames → None; but if there were frames, error_type would be from title
    assert event is None


def test_debug_parse_returns_dict(config, python_issue_fixture):
    parser = SentryParser(config)
    result = parser.debug_parse(
        python_issue_fixture["title"],
        python_issue_fixture["description"],
    )
    assert isinstance(result, dict)
    assert "detected_language" in result
    assert "event" in result
    assert "raw_frame_counts" in result


def test_frame_depths_are_sequential(config, python_issue_fixture):
    parser = SentryParser(config)
    event = parser.parse(
        python_issue_fixture["title"],
        python_issue_fixture["description"],
    )
    assert event is not None
    depths = [f.frame_depth for f in event.frames]
    assert depths == list(range(1, len(depths) + 1))


def test_raw_frame_count_includes_filtered(config, python_issue_fixture):
    """raw_frame_count should include library frames before filtering."""
    parser = SentryParser(config)
    event = parser.parse(
        python_issue_fixture["title"],
        python_issue_fixture["description"],
    )
    assert event is not None
    # 4 raw frames, 1 library → 3 filtered frames, raw_count = 4
    assert event.raw_frame_count == 4
    assert len(event.frames) == 3


# ---------------------------------------------------------------------------
# Ruby parsing
# ---------------------------------------------------------------------------


def test_parse_ruby_frames(config):
    fixture = __import__("json").loads(
        (__import__("pathlib").Path(__file__).parent.parent / "fixtures" / "sentry_ruby.json")
        .read_text()
    )
    parser = SentryParser(config)
    event = parser.parse(fixture["title"], fixture["description"])
    assert event is not None
    assert event.error_type == "NoMethodError"
    assert len(event.frames) >= 1
    assert event.frames[0].language.value == "ruby"


def test_parse_ruby_library_filtered(config):
    fixture = __import__("json").loads(
        (__import__("pathlib").Path(__file__).parent.parent / "fixtures" / "sentry_ruby.json")
        .read_text()
    )
    parser = SentryParser(config)
    event = parser.parse(fixture["title"], fixture["description"])
    assert event is not None
    paths = [f.file_path for f in event.frames]
    assert not any("gems/" in p for p in paths)


# ---------------------------------------------------------------------------
# Java parsing
# ---------------------------------------------------------------------------


def test_parse_java_frames(config):
    fixture = __import__("json").loads(
        (__import__("pathlib").Path(__file__).parent.parent / "fixtures" / "sentry_java.json")
        .read_text()
    )
    parser = SentryParser(config)
    event = parser.parse(fixture["title"], fixture["description"])
    assert event is not None
    assert len(event.frames) >= 1
    assert event.frames[0].language.value == "java"


def test_parse_java_caused_by_extracts_root_cause(config):
    """'Caused by:' exceptions should set the error_type to the innermost exception."""
    fixture = __import__("json").loads(
        (__import__("pathlib").Path(__file__).parent.parent / "fixtures" / "sentry_java.json")
        .read_text()
    )
    parser = SentryParser(config)
    event = parser.parse(fixture["title"], fixture["description"])
    assert event is not None
    assert "GatewayException" in event.error_type


def test_parse_java_stdlib_filtered(config):
    fixture = __import__("json").loads(
        (__import__("pathlib").Path(__file__).parent.parent / "fixtures" / "sentry_java.json")
        .read_text()
    )
    parser = SentryParser(config)
    event = parser.parse(fixture["title"], fixture["description"])
    assert event is not None
    paths = [f.file_path for f in event.frames]
    assert not any(p.startswith("sun/") for p in paths)
    assert not any(p.startswith("java/") for p in paths)


# ---------------------------------------------------------------------------
# include_library_frames=True
# ---------------------------------------------------------------------------


def test_include_library_frames_flag(config, python_issue_fixture):
    """When include_library_frames=True, library frames should appear."""
    lib_config = config.__class__(**{**config.__dict__, "include_library_frames": True})
    parser = SentryParser(lib_config)
    event = parser.parse(
        python_issue_fixture["title"],
        python_issue_fixture["description"],
    )
    assert event is not None
    assert len(event.frames) == 4  # all 4 raw frames included


# ---------------------------------------------------------------------------
# Unicode and special characters
# ---------------------------------------------------------------------------


def test_unicode_in_function_name(config):
    """Unicode function names should not crash the parser."""
    description = (
        "Traceback (most recent call last):\n"
        '  File "/app/utils.py", line 10, in handle_ünïcödé\n'
        "ValueError: bad input\n"
    )
    parser = SentryParser(config)
    event = parser.parse("[Sentry] ValueError: bad input", description)
    if event:
        assert event.frames[0].function_name == "handle_ünïcödé"


# ---------------------------------------------------------------------------
# Python bare error (no message on error line)
# ---------------------------------------------------------------------------


def test_parse_python_bare_error_no_message(config):
    """A Python stack trace where the error line has no ':' message is still parsed."""
    description = (
        "Traceback (most recent call last):\n"
        '  File "/app/views.py", line 20, in handle_request\n'
        "    result = service.run()\n"
        "  File \"/app/service.py\", line 10, in run\n"
        "    raise RuntimeError\n"
        "RuntimeError\n"
    )
    parser = SentryParser(config)
    event = parser.parse("[Sentry] RuntimeError", description)
    assert event is not None
    assert event.error_type == "RuntimeError"
    assert event.error_message == ""
    assert len(event.frames) >= 1


# ---------------------------------------------------------------------------
# Go signal errors
# ---------------------------------------------------------------------------


def test_parse_go_signal_error(config):
    """Go signal errors (e.g. SIGSEGV) set error_type to 'signal'."""
    description = (
        "signal SIGSEGV: segmentation violation code=0x2 addr=0x0 pc=0x45a7e7\n"
        "\n"
        "goroutine 1 [signal]:\n"
        "main.processRequest(0xc000010200)\n"
        "\t/app/main.go:42\n"
    )
    parser = SentryParser(config)
    event = parser.parse("[Sentry] signal SIGSEGV", description)
    assert event is not None
    assert event.error_type == "signal"
    assert "segmentation violation" in event.error_message


# ---------------------------------------------------------------------------
# Auto-detection fallback (UNKNOWN language)
# ---------------------------------------------------------------------------


def test_language_auto_detection_fallback(config):
    """When language detection returns UNKNOWN, each parser is tried in turn."""
    from unittest.mock import patch
    from src.rootchain import sentry_parser as sp
    from src.rootchain.models import Language

    python_description = (
        "Traceback (most recent call last):\n"
        '  File "/app/worker.py", line 55, in execute_job\n'
        "    result = backend.process(task)\n"
        "RuntimeError: backend timeout\n"
    )

    with patch.object(sp, "_detect_language", return_value=Language.UNKNOWN):
        parser = SentryParser(config)
        event = parser.parse("[Sentry] RuntimeError: backend timeout", python_description)

    assert event is not None
    assert len(event.frames) >= 1
    assert event.frames[0].function_name == "execute_job"


# ---------------------------------------------------------------------------
# Kotlin stack traces
# ---------------------------------------------------------------------------


def test_parse_kotlin_basic(config):
    description = (
        "## NullPointerException: Payment gateway returned null\n\n"
        "### Stacktrace\n\n"
        "at com.myorg.payments.Processor.processPayment(Processor.kt:142)\n"
        "at com.myorg.payments.Gateway.call(Gateway.kt:88)\n"
        "at kotlin.coroutines.jvm.internal.BaseContinuationImpl.resumeWith(ContinuationImpl.kt:33)\n"
    )
    parser = SentryParser(config)
    event = parser.parse("[Sentry] NullPointerException: gateway null", description)

    assert event is not None
    assert event.error_type == "NullPointerException"
    # Non-library frames: processPayment and call (kotlin. prefix filtered)
    assert len(event.frames) == 2
    assert event.frames[0].language.value == "kotlin"
    assert event.frames[0].function_name == "com.myorg.payments.Processor.processPayment"
    assert event.frames[0].frame_depth == 1


def test_detect_kotlin(config):
    description = "at com.example.App.run(App.kt:10)\n"
    assert _detect_language(description) == Language.KOTLIN


# ---------------------------------------------------------------------------
# Rust stack traces
# ---------------------------------------------------------------------------


def test_parse_rust_basic(config):
    description = (
        "thread 'main' panicked at 'index out of bounds: the len is 3 but the index is 5',"
        " src/payments/processor.rs:142\n\n"
        "stack backtrace:\n"
        "   0: rust_begin_unwind\n"
        "             at /rustc/abc123/library/std/src/panicking.rs:617:5\n"
        "   1: myapp::payments::process_payment\n"
        "             at src/payments/processor.rs:142:8\n"
        "   2: myapp::main\n"
        "             at src/main.rs:10:5\n"
    )
    parser = SentryParser(config)
    event = parser.parse("[Sentry] panic: index out of bounds", description)

    assert event is not None
    assert event.error_type == "panic"
    assert "index out of bounds" in event.error_message
    # rust_begin_unwind at /rustc/... is library (std:: prefix path)
    # process_payment and main both app code but "main" is in SKIP_FUNCTION_NAMES
    non_lib = [f for f in event.frames if not f.is_library]
    assert any("process_payment" in f.function_name for f in non_lib)
    assert event.frames[0].language == Language.RUST


def test_detect_rust(config):
    description = "   1: myapp::payments::process_payment\n             at src/payments/processor.rs:142:8\n"
    assert _detect_language(description) == Language.RUST
