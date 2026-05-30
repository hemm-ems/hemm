#!/usr/bin/env python3
"""Render a Codex round brief from the standard template.

Embeds `git status --porcelain` and `git diff --stat` for the listed files
(never full diffs — keeps the brief small). Enforces a 2-round hard cap.

Usage:
    python3 tools/codex_brief.py \\
        --goal "fix SC-005 constraint leak" \\
        --goal-oneline "SC-005 leak fix" \\
        --files custom_components/hemm/actuator.py:120-150 \\
        --change "remove leftover phase7 forbidden_window in _reset_phase7_helpers" \\
        --verify "make test-container-sc SC=SC-005" \\
        --out-of-scope "actuator engine logic; audit log format" \\
        --round 1 \\
        --repo /Users/jan/dev/repos/hemm/ha-hemm
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "codex_brief.md"


def run(cmd: list[str], cwd: Path) -> str:
    try:
        out = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True, timeout=10)
        return (out.stdout + out.stderr).strip() or "(empty)"
    except Exception as exc:
        return f"(failed: {exc})"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--goal", required=True, help="2-3 sentence what+why")
    p.add_argument("--goal-oneline", default="", help="short headline (defaults to goal[:60])")
    p.add_argument(
        "--files",
        required=True,
        nargs="+",
        help="paths, optionally with :START-END line range",
    )
    p.add_argument("--change", required=True, help="concrete change description")
    p.add_argument("--verify", required=True, help="exact command that must pass")
    p.add_argument("--out-of-scope", default="(nothing flagged)")
    p.add_argument("--round", type=int, required=True, choices=[1, 2])
    p.add_argument("--repo", default=".", help="repo root for git context")
    args = p.parse_args()

    if args.round > 2:
        print("ERROR: hard cap is 2 rounds — finish inline", file=sys.stderr)
        return 2

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print(f"ERROR: {repo} is not a git repo", file=sys.stderr)
        return 2

    file_paths = [f.split(":")[0] for f in args.files]
    status = run(["git", "status", "--porcelain"], repo)
    diffstat = run(["git", "diff", "--stat", "--", *file_paths], repo)

    files_block = "\n".join(f"- `{f}`" for f in args.files)
    oneline = args.goal_oneline or args.goal.strip().splitlines()[0][:60]

    body = TEMPLATE.read_text()
    out = (
        body.replace("{{ROUND}}", str(args.round))
        .replace("{{GOAL_ONELINE}}", oneline)
        .replace("{{GOAL}}", args.goal.strip())
        .replace("{{REPO_ROOT}}", str(repo))
        .replace("{{FILES}}", files_block)
        .replace("{{GIT_STATUS}}", status)
        .replace("{{GIT_DIFFSTAT}}", diffstat)
        .replace("{{CHANGE_DESC}}", args.change.strip())
        .replace("{{VERIFY}}", args.verify.strip())
        .replace("{{OUT_OF_SCOPE}}", args.out_of_scope.strip())
    )
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
