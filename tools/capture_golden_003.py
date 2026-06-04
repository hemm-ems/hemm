"""Capture the pre-refactor Backend-A golden baseline (feature 003, T001).

The golden fixtures under ``testdata/golden/003_backend_a/`` are the ONLY parity
reference for the generic-entities refactor. This tool MUST be run before any
edit to ``solvers/milp_central.py``; re-running it after the refactor would
silently overwrite the oracle, so it is a deliberate manual tool, never wired
into CI.

    uv run python tools/capture_golden_003.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# The canonical solve helper lives next to the tests it serves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from _parity import capture_golden  # noqa: E402


def main() -> None:
    for path in capture_golden():
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
