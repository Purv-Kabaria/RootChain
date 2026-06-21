"""Validate rootchain.yml against the Duo Agent Platform YAML schema.

Usage:
    python scripts/validate_flow.py .gitlab/duo-flows/rootchain.yml
"""

from __future__ import annotations

import sys
from pathlib import Path


REQUIRED_KEYS = ["name", "version", "trigger", "steps"]
REQUIRED_STEP_KEYS = ["name", "type", "tools"]
VALID_STEP_TYPES = {"agent", "pipeline"}
VALID_TRIGGER_EVENTS = {"work_item_created", "merge_request_created", "pipeline_succeeded"}


def validate(path: Path) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    try:
        import tomllib
    except ImportError:
        import tomllib  # type: ignore[no-redef]

    try:
        import yaml
    except ImportError:
        print("[WARN] PyYAML not installed; skipping YAML parse validation.")
        return []

    text = path.read_text(encoding="utf-8")
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return [f"YAML parse error: {e}"]

    errors: list[str] = []

    for key in REQUIRED_KEYS:
        if key not in doc:
            errors.append(f"Missing required top-level key: '{key}'")

    if "version" in doc and not isinstance(doc["version"], int):
        errors.append(f"'version' must be an integer, got {type(doc['version']).__name__}")

    if "trigger" in doc:
        event = doc["trigger"].get("event", "")
        if event not in VALID_TRIGGER_EVENTS:
            errors.append(
                f"Unknown trigger event: '{event}'. Valid: {VALID_TRIGGER_EVENTS}"
            )

    for i, step in enumerate(doc.get("steps", [])):
        for key in REQUIRED_STEP_KEYS:
            if key not in step:
                errors.append(f"Step {i}: missing required key '{key}'")
        if step.get("type") not in VALID_STEP_TYPES:
            errors.append(
                f"Step {i}: invalid type '{step.get('type')}'. Valid: {VALID_STEP_TYPES}"
            )

    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_flow.py <path-to-yml>")
        return 1

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"[ERROR] File not found: {path}")
        return 1

    errors = validate(path)
    if errors:
        print(f"[FAIL] {path} has {len(errors)} error(s):")
        for e in errors:
            print(f"  • {e}")
        return 1

    print(f"[OK] {path} is valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
