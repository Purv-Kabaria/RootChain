"""Unit tests for orchestrator.py — all external calls mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.rootchain.models import Ok, Err
from src.rootchain.orchestrator import run_analysis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_histories(orbit_miss: bool = False):
    from src.rootchain.models import SymbolHistory
    return [
        SymbolHistory(
            function_name="processPayment",
            file_path="payments/processor.py",
            recent_mrs=[],
            caller_count=0,
            orbit_miss=orbit_miss,
            fallback_used=False,
        )
    ]


PYTHON_DESCRIPTION = """\
## TypeError: 'NoneType' object is not subscriptable
**Environment:** production
### Stacktrace
```
  File "/app/payments/processor.py", line 142, in processPayment
    result_id = gateway_response['id']
TypeError: 'NoneType' object is not subscriptable
```
"""


# ---------------------------------------------------------------------------
# Idempotency guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_guard_skips_already_analyzed(config):
    """If the issue already has rootchain-analyzed label, nothing should happen."""
    with (
        patch("src.rootchain.orchestrator.GitLabClient") as MockGL,
        patch("src.rootchain.orchestrator.OrbitClient") as MockOrbit,
    ):
        mock_gl = AsyncMock()
        MockGL.return_value.__aenter__ = AsyncMock(return_value=mock_gl)
        MockGL.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_orbit = AsyncMock()
        MockOrbit.return_value.__aenter__ = AsyncMock(return_value=mock_orbit)
        MockOrbit.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_analysis(
            project_path="myorg/myapp",
            issue_iid=42,
            issue_title="[Sentry] TypeError",
            issue_description=PYTHON_DESCRIPTION,
            issue_labels=["rootchain-analyzed"],
            config=config,
        )

        mock_gl.add_note.assert_not_called()
        mock_gl.add_label.assert_not_called()
        mock_orbit.get_symbol_histories.assert_not_called()


# ---------------------------------------------------------------------------
# No stack trace path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_stack_trace_posts_comment(config):
    """Issues without a parseable trace get a 'no stack trace' comment."""
    with (
        patch("src.rootchain.orchestrator.GitLabClient") as MockGL,
        patch("src.rootchain.orchestrator.OrbitClient") as MockOrbit,
    ):
        mock_gl = AsyncMock()
        mock_gl.add_note = AsyncMock(return_value=Ok(value=100))
        mock_gl.add_label = AsyncMock(return_value=Ok(value=42))
        MockGL.return_value.__aenter__ = AsyncMock(return_value=mock_gl)
        MockGL.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_orbit = AsyncMock()
        MockOrbit.return_value.__aenter__ = AsyncMock(return_value=mock_orbit)
        MockOrbit.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_analysis(
            project_path="myorg/myapp",
            issue_iid=42,
            issue_title="[Sentry] SomeError",
            issue_description="No stack trace here at all.",
            issue_labels=["sentry-alert"],
            config=config,
        )

        mock_gl.add_note.assert_called_once()
        call_args = mock_gl.add_note.call_args
        assert "No parseable stack trace" in call_args.args[2]
        mock_gl.add_label.assert_called_once()
        mock_orbit.get_symbol_histories.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_posts_analysis(config):
    """Full happy path: note posted + label added."""
    with (
        patch("src.rootchain.orchestrator.GitLabClient") as MockGL,
        patch("src.rootchain.orchestrator.OrbitClient") as MockOrbit,
    ):
        mock_gl = AsyncMock()
        mock_gl.add_note = AsyncMock(return_value=Ok(value=200))
        mock_gl.add_label = AsyncMock(return_value=Ok(value=42))
        MockGL.return_value.__aenter__ = AsyncMock(return_value=mock_gl)
        MockGL.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_orbit = AsyncMock()
        mock_orbit.get_symbol_histories = AsyncMock(return_value=_make_histories(orbit_miss=True))
        MockOrbit.return_value.__aenter__ = AsyncMock(return_value=mock_orbit)
        MockOrbit.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_analysis(
            project_path="myorg/myapp",
            issue_iid=42,
            issue_title="[Sentry] TypeError",
            issue_description=PYTHON_DESCRIPTION,
            issue_labels=["sentry-alert"],
            config=config,
        )

        mock_gl.add_note.assert_called_once()
        mock_gl.add_label.assert_called_once_with("myorg/myapp", 42, "rootchain-analyzed")


# ---------------------------------------------------------------------------
# note_post_failed — label should still NOT be added
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_note_failure_skips_label(config):
    """If posting the note fails, don't attempt to add the label."""
    with (
        patch("src.rootchain.orchestrator.GitLabClient") as MockGL,
        patch("src.rootchain.orchestrator.OrbitClient") as MockOrbit,
    ):
        mock_gl = AsyncMock()
        mock_gl.add_note = AsyncMock(
            return_value=Err(message="Forbidden", code="gitlab_forbidden", retryable=False)
        )
        mock_gl.add_label = AsyncMock(return_value=Ok(value=42))
        MockGL.return_value.__aenter__ = AsyncMock(return_value=mock_gl)
        MockGL.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_orbit = AsyncMock()
        mock_orbit.get_symbol_histories = AsyncMock(return_value=_make_histories(orbit_miss=True))
        MockOrbit.return_value.__aenter__ = AsyncMock(return_value=mock_orbit)
        MockOrbit.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_analysis(
            project_path="myorg/myapp",
            issue_iid=42,
            issue_title="[Sentry] TypeError",
            issue_description=PYTHON_DESCRIPTION,
            issue_labels=["sentry-alert"],
            config=config,
        )

        mock_gl.add_note.assert_called_once()
        mock_gl.add_label.assert_not_called()


# ---------------------------------------------------------------------------
# Orbit returns data → analysis comment contains MR reference
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analysis_comment_contains_mr_link(config, sample_history):
    """When Orbit returns real data, the note body should contain an MR link."""
    with (
        patch("src.rootchain.orchestrator.GitLabClient") as MockGL,
        patch("src.rootchain.orchestrator.OrbitClient") as MockOrbit,
    ):
        mock_gl = AsyncMock()
        mock_gl.add_note = AsyncMock(return_value=Ok(value=200))
        mock_gl.add_label = AsyncMock(return_value=Ok(value=42))
        MockGL.return_value.__aenter__ = AsyncMock(return_value=mock_gl)
        MockGL.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_orbit = AsyncMock()
        mock_orbit.get_symbol_histories = AsyncMock(return_value=[sample_history])
        MockOrbit.return_value.__aenter__ = AsyncMock(return_value=mock_orbit)
        MockOrbit.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_analysis(
            project_path="myorg/myapp",
            issue_iid=42,
            issue_title="[Sentry] TypeError",
            issue_description=PYTHON_DESCRIPTION,
            issue_labels=["sentry-alert"],
            config=config,
        )

        call_body = mock_gl.add_note.call_args.args[2]
        assert "!342" in call_body
        assert "@alice" in call_body
