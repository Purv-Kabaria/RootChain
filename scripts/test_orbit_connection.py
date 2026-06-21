"""Smoke test: verify Orbit is reachable and enabled on the configured group.

Usage:
    export ROOTCHAIN_GITLAB_TOKEN=glpat-xxx
    export ROOTCHAIN_GROUP_PATH=your-group
    python scripts/test_orbit_connection.py
"""

from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.rootchain.config import Config
from src.rootchain.models import Ok, Err
from src.rootchain.orbit_client import OrbitClient


async def main() -> int:
    try:
        config = Config.from_env()
    except RuntimeError as e:
        print(f"[ERROR] Config error: {e}")
        return 1

    print(f"Testing Orbit connection to {config.gitlab_url} ...")
    print(f"Group path: {config.group_path}")

    async with OrbitClient(config) as client:
        result = await client.check_health()

    match result:
        case Ok(value=status):
            print(f"[OK] Orbit status: {status}")
        case Err(message=msg, code=code):
            print(f"[FAIL] Orbit health check failed: {msg} (code={code})")
            return 1

    print("\nRunning a test Orbit query ...")
    from src.rootchain.models import StackFrame, Language

    test_frame = StackFrame(
        file_path="README.md",
        function_name="test_connection",
        line_number=1,
        language=Language.UNKNOWN,
        is_library=False,
        frame_depth=1,
        raw_line="README.md:1 in test_connection",
    )

    async with OrbitClient(config) as client:
        histories = await client.get_symbol_histories([test_frame])

    h = histories[0]
    if h.orbit_miss:
        print("[OK] Orbit reachable — no results for test symbol (expected for README.md).")
    else:
        print(f"[OK] Orbit returned {len(h.recent_mrs)} MR(s) for the test symbol.")

    print("\nOrbit connection smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
