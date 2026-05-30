# Codex round {{ROUND}} of max 2 — {{GOAL_ONELINE}}

## Goal
{{GOAL}}

## Repo + sandbox rules
- Workspace: `{{REPO_ROOT}}` (workspace-write sandbox).
- Touch ONLY the files listed under "Target files". Do not rename, move, or reformat unrelated code.
- Use strict explicit-path `git add <path> [<path>...]`. Never `git add -A` / `git add .`.
- If `.git/index.lock` blocks the commit, leave the tree uncommitted and report — do not retry destructively.
- Do not run `make gate`, container tests, or anything network-bound. Unit tests only.

## Target files
{{FILES}}

## Current state
```
{{GIT_STATUS}}
```

```
{{GIT_DIFFSTAT}}
```

## Required change
{{CHANGE_DESC}}

## Verification (must pass before commit)
```
{{VERIFY}}
```

## Out of scope (do NOT touch)
{{OUT_OF_SCOPE}}

## Round cap
This is round {{ROUND}} of a hard maximum of 2. If verification does not pass on round 2,
report the failing output verbatim and stop — the orchestrator will finish inline.
