"""Unit tests for config.py."""

from __future__ import annotations

import os

import pytest

from src.rootchain.config import Config, _bool_env, _float_env, _int_env, _require_env


# ---------------------------------------------------------------------------
# _require_env
# ---------------------------------------------------------------------------


def test_require_env_present(monkeypatch):
    monkeypatch.setenv("TEST_VAR", "hello")
    assert _require_env("TEST_VAR") == "hello"


def test_require_env_missing(monkeypatch):
    monkeypatch.delenv("TEST_VAR", raising=False)
    with pytest.raises(RuntimeError, match="TEST_VAR"):
        _require_env("TEST_VAR")


def test_require_env_empty(monkeypatch):
    monkeypatch.setenv("TEST_VAR", "")
    with pytest.raises(RuntimeError, match="TEST_VAR"):
        _require_env("TEST_VAR")


# ---------------------------------------------------------------------------
# _bool_env / _int_env / _float_env
# ---------------------------------------------------------------------------


def test_bool_env_true_variants(monkeypatch):
    for v in ("1", "true", "TRUE", "yes", "YES"):
        monkeypatch.setenv("B", v)
        assert _bool_env("B", False) is True


def test_bool_env_false_variants(monkeypatch):
    for v in ("0", "false", "no", "FALSE"):
        monkeypatch.setenv("B", v)
        assert _bool_env("B", True) is False


def test_bool_env_default(monkeypatch):
    monkeypatch.delenv("B", raising=False)
    assert _bool_env("B", True) is True


def test_int_env_valid(monkeypatch):
    monkeypatch.setenv("N", "42")
    assert _int_env("N", 0) == 42


def test_int_env_invalid(monkeypatch):
    monkeypatch.setenv("N", "abc")
    with pytest.raises(RuntimeError, match="integer"):
        _int_env("N", 0)


def test_float_env_valid(monkeypatch):
    monkeypatch.setenv("F", "0.35")
    assert abs(_float_env("F", 0.0) - 0.35) < 1e-9


def test_float_env_invalid(monkeypatch):
    monkeypatch.setenv("F", "not-a-float")
    with pytest.raises(RuntimeError, match="float"):
        _float_env("F", 0.0)


# ---------------------------------------------------------------------------
# Config.from_env
# ---------------------------------------------------------------------------


def test_from_env_happy_path(monkeypatch):
    monkeypatch.setenv("ROOTCHAIN_GITLAB_TOKEN", "glpat-abc")
    monkeypatch.setenv("ROOTCHAIN_GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("ROOTCHAIN_GROUP_PATH", "my-org")
    monkeypatch.setenv("ROOTCHAIN_PROJECT_PATH", "my-org/my-app")
    # Clear optional vars to use defaults
    for var in [
        "ROOTCHAIN_ORBIT_TIMEOUT_SECONDS",
        "ROOTCHAIN_MAX_FRAMES",
        "ROOTCHAIN_RECENCY_WEIGHT",
        "ROOTCHAIN_DEPTH_WEIGHT",
        "ROOTCHAIN_BLAST_WEIGHT",
    ]:
        monkeypatch.delenv(var, raising=False)

    cfg = Config.from_env()

    assert cfg.gitlab_token == "glpat-abc"
    assert cfg.gitlab_url == "https://gitlab.example.com"
    assert cfg.group_path == "my-org"
    assert cfg.project_path == "my-org/my-app"
    assert cfg.max_frames == 5
    assert cfg.orbit_timeout_seconds == 30


def test_from_env_missing_token(monkeypatch):
    monkeypatch.delenv("ROOTCHAIN_GITLAB_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="ROOTCHAIN_GITLAB_TOKEN"):
        Config.from_env()


def test_from_env_missing_group_path(monkeypatch):
    monkeypatch.setenv("ROOTCHAIN_GITLAB_TOKEN", "glpat-abc")
    monkeypatch.delenv("ROOTCHAIN_GROUP_PATH", raising=False)
    monkeypatch.delenv("ROOTCHAIN_PROJECT_PATH", raising=False)
    with pytest.raises(RuntimeError, match="ROOTCHAIN_GROUP_PATH"):
        Config.from_env()


def test_from_env_weight_validation_fails(monkeypatch):
    monkeypatch.setenv("ROOTCHAIN_GITLAB_TOKEN", "t")
    monkeypatch.setenv("ROOTCHAIN_GITLAB_URL", "https://g.com")
    monkeypatch.setenv("ROOTCHAIN_GROUP_PATH", "g")
    monkeypatch.setenv("ROOTCHAIN_PROJECT_PATH", "g/p")
    monkeypatch.setenv("ROOTCHAIN_RECENCY_WEIGHT", "0.9")
    monkeypatch.setenv("ROOTCHAIN_DEPTH_WEIGHT", "0.9")
    monkeypatch.setenv("ROOTCHAIN_BLAST_WEIGHT", "0.9")

    with pytest.raises(RuntimeError, match="weights must sum to 1.0"):
        Config.from_env()


def test_from_env_trailing_slash_stripped(monkeypatch):
    monkeypatch.setenv("ROOTCHAIN_GITLAB_TOKEN", "t")
    monkeypatch.setenv("ROOTCHAIN_GITLAB_URL", "https://gitlab.com/")
    monkeypatch.setenv("ROOTCHAIN_GROUP_PATH", "g")
    monkeypatch.setenv("ROOTCHAIN_PROJECT_PATH", "g/p")
    for w in ["ROOTCHAIN_RECENCY_WEIGHT", "ROOTCHAIN_DEPTH_WEIGHT", "ROOTCHAIN_BLAST_WEIGHT"]:
        monkeypatch.delenv(w, raising=False)

    cfg = Config.from_env()
    assert not cfg.gitlab_url.endswith("/")


# ---------------------------------------------------------------------------
# Config properties
# ---------------------------------------------------------------------------


def test_orbit_url(config):
    assert config.orbit_url == "https://gitlab.example.com/api/v4/orbit/query"


def test_gitlab_api_url(config):
    assert config.gitlab_api_url == "https://gitlab.example.com/api/v4"
