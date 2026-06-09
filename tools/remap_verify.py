#!/usr/bin/env python3
"""Deterministic, zero-token correctness check for a regenerated CODEBASE_MAP.md.

Run after `tools/remap.sh` (Codex) rewrites the map. Emits ONE compact PASS/FAIL
line and exits 0/1 — so the orchestration session can confirm a remap without
ever reading the map or the Codex transcript.

Usage:
    python3 tools/remap_verify.py [--map PATH]

Checks: file exists & non-trivial; size didn't collapse vs the committed
baseline; required anchor headings present; markdown structure intact; no
failure/leak phrases (Codex inability reports or narration leaked into the file).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# tools/ -> hemm/ -> workspace root
WORKSPACE = Path(__file__).resolve().parents[2]
DEFAULT_MAP = WORKSPACE / "docs" / "CODEBASE_MAP.md"

# --- tunables ---------------------------------------------------------------
MIN_BYTES = 8_000
MAX_SHRINK_FRAC = 0.40          # FAIL if the map lost > 40% of its lines
MIN_SECTIONS = 8                # number of `## ` headings expected
# Required anchors (case-insensitive substring of a heading line). N/len reported.
ANCHORS = [
    "Topology",
    "Primitive Component Model",
    "Actuator",
    "FR Status",
    "Gate",
    "Container",
    "Navigation",
]
# If any of these appear, Codex narration / an inability report leaked into the map.
FAIL_PHRASES = [
    "i couldn't",
    "i was unable",
    "i'm unable",
    "permission denied",
    "failed to write",
    "as an ai",
    "<stdin>",
    "i don't have access",
]
# ---------------------------------------------------------------------------


def git_baseline_lines(map_path: Path) -> int | None:
    """Line count of the committed map (HEAD), or None if untracked/unavailable."""
    rel = map_path.relative_to(WORKSPACE) if map_path.is_relative_to(WORKSPACE) else map_path
    try:
        out = subprocess.run(
            ["git", "show", f"HEAD:{rel.as_posix()}"],
            cwd=WORKSPACE, check=True, capture_output=True, text=True, timeout=10,
        )
        return out.stdout.count("\n")
    except Exception:
        return None


def git_numstat(map_path: Path) -> str:
    """`+added/-deleted` vs HEAD for the map, or '' if unavailable."""
    rel = map_path.relative_to(WORKSPACE) if map_path.is_relative_to(WORKSPACE) else map_path
    try:
        out = subprocess.run(
            ["git", "diff", "--numstat", "--", rel.as_posix()],
            cwd=WORKSPACE, check=True, capture_output=True, text=True, timeout=10,
        )
        line = out.stdout.strip().splitlines()
        if not line:
            return "Δlines=0"
        added, deleted, *_ = line[0].split("\t")
        return f"Δlines=+{added}/-{deleted}"
    except Exception:
        return ""


def fail(msg: str) -> int:
    print(f"REMAP FAIL  {msg}  — see .remap/run-*.log")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP)
    args = ap.parse_args()
    map_path: Path = args.map

    if not map_path.is_file():
        return fail(f"missing {map_path}")

    text = map_path.read_text(encoding="utf-8", errors="replace")
    size = map_path.stat().st_size
    lines = text.splitlines()
    heading_lines = [ln for ln in lines if ln.startswith("#")]
    sections = sum(1 for ln in lines if ln.startswith("## "))
    has_h1 = any(ln.startswith("# ") for ln in lines)

    if size < MIN_BYTES:
        return fail(f"too small ({size}B < {MIN_BYTES}B)")
    if not has_h1:
        return fail("no H1 heading")
    if sections < MIN_SECTIONS:
        return fail(f"only {sections} sections (< {MIN_SECTIONS})")

    low = text.lower()
    leaked = [p for p in FAIL_PHRASES if p in low]
    if leaked:
        return fail(f"leak phrase: {leaked[0]!r}")

    headings_low = "\n".join(heading_lines).lower()
    matched = [a for a in ANCHORS if a.lower() in headings_low]
    if len(matched) < len(ANCHORS):
        missing = [a for a in ANCHORS if a not in matched]
        return fail(f"anchors={len(matched)}/{len(ANCHORS)} (missing: {', '.join(missing)})")

    baseline = git_baseline_lines(map_path)
    if baseline is not None and baseline > 0:
        if len(lines) < baseline * (1 - MAX_SHRINK_FRAC):
            return fail(f"shrank {len(lines)} < {baseline} lines (> {int(MAX_SHRINK_FRAC*100)}%)")

    delta = git_numstat(map_path)
    print(
        f"REMAP PASS  {size/1024:.1f}KB  sections={sections}  "
        f"anchors={len(matched)}/{len(ANCHORS)}"
        + (f"  {delta}" if delta else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
