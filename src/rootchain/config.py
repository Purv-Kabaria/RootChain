"""Config dataclass driven entirely by environment variables.

All os.getenv() calls happen here and only here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _require_env(name: str) -> str:
    """Return env var value or raise a clear error if missing."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable {name!r} is not set. "
            "See .env.example for the full list of required variables."
        )
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).lower()
    return raw in ("1", "true", "yes")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"Environment variable {name!r} must be an integer, got {raw!r}")


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        return float(raw)
    except ValueError:
        raise RuntimeError(f"Environment variable {name!r} must be a float, got {raw!r}")


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration. Constructed once via Config.from_env()."""

    # Required
    gitlab_token: str
    gitlab_url: str
    group_path: str
    project_path: str

    # Orbit
    orbit_timeout_seconds: int = 30
    orbit_max_retries: int = 3
    orbit_retry_base_seconds: int = 2

    # Parsing
    max_frames: int = 5
    include_library_frames: bool = False

    # Scoring weights (must sum to 1.0, validated below)
    confidence_threshold: float = 0.4
    recency_weight: float = 0.50
    depth_weight: float = 0.35
    blast_weight: float = 0.15
    recency_half_life_days: int = 30

    # Output
    add_label: str = "rootchain-analyzed"
    mention_authors: bool = True
    mention_reviewers: bool = False
    max_mention_users: int = 3

    # Webhook receiver
    webhook_secret: str = ""
    webhook_port: int = 8080

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    @classmethod
    def from_env(cls) -> "Config":
        """Read all configuration from environment variables."""
        cfg = cls(
            gitlab_token=_require_env("ROOTCHAIN_GITLAB_TOKEN"),
            gitlab_url=os.getenv("ROOTCHAIN_GITLAB_URL", "https://gitlab.com").rstrip("/"),
            group_path=_require_env("ROOTCHAIN_GROUP_PATH"),
            project_path=_require_env("ROOTCHAIN_PROJECT_PATH"),
            orbit_timeout_seconds=_int_env("ROOTCHAIN_ORBIT_TIMEOUT_SECONDS", 30),
            orbit_max_retries=_int_env("ROOTCHAIN_ORBIT_MAX_RETRIES", 3),
            orbit_retry_base_seconds=_int_env("ROOTCHAIN_ORBIT_RETRY_BASE_SECONDS", 2),
            max_frames=_int_env("ROOTCHAIN_MAX_FRAMES", 5),
            include_library_frames=_bool_env("ROOTCHAIN_INCLUDE_LIBRARY_FRAMES", False),
            confidence_threshold=_float_env("ROOTCHAIN_CONFIDENCE_THRESHOLD", 0.4),
            recency_weight=_float_env("ROOTCHAIN_RECENCY_WEIGHT", 0.50),
            depth_weight=_float_env("ROOTCHAIN_DEPTH_WEIGHT", 0.35),
            blast_weight=_float_env("ROOTCHAIN_BLAST_WEIGHT", 0.15),
            recency_half_life_days=_int_env("ROOTCHAIN_RECENCY_HALF_LIFE_DAYS", 30),
            add_label=os.getenv("ROOTCHAIN_ADD_LABEL", "rootchain-analyzed"),
            mention_authors=_bool_env("ROOTCHAIN_MENTION_AUTHORS", True),
            mention_reviewers=_bool_env("ROOTCHAIN_MENTION_REVIEWERS", False),
            max_mention_users=_int_env("ROOTCHAIN_MAX_MENTION_USERS", 3),
            webhook_secret=os.getenv("ROOTCHAIN_WEBHOOK_SECRET", ""),
            webhook_port=_int_env("ROOTCHAIN_WEBHOOK_PORT", 8080),
            log_level=os.getenv("ROOTCHAIN_LOG_LEVEL", "INFO").upper(),
            log_format=os.getenv("ROOTCHAIN_LOG_FORMAT", "json").lower(),
        )

        total_weight = cfg.recency_weight + cfg.depth_weight + cfg.blast_weight
        if abs(total_weight - 1.0) > 0.001:
            raise RuntimeError(
                f"Confidence weights must sum to 1.0, got {total_weight:.3f}. "
                "Check ROOTCHAIN_RECENCY_WEIGHT, ROOTCHAIN_DEPTH_WEIGHT, ROOTCHAIN_BLAST_WEIGHT."
            )

        return cfg

    @property
    def orbit_url(self) -> str:
        return f"{self.gitlab_url}/api/v4/orbit/query"

    @property
    def gitlab_api_url(self) -> str:
        return f"{self.gitlab_url}/api/v4"
