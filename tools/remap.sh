#!/usr/bin/env bash
# Regenerate docs/CODEBASE_MAP.md with Codex, headless and quiet.
#
# Codex does the heavy lifting; the orchestration session sees only the verifier
# verdict. ALL Codex narration goes to .remap/run-<ts>.log (never stdout), the
# final agent message to .remap/last-msg.txt, the compact verdict to
# .remap/verdict.txt. Invoked from `make remap`; also safe to cron.
set -euo pipefail

WORKSPACE="/Users/jan/dev/repos/hemm"
OUT="${WORKSPACE}/docs/CODEBASE_MAP.md"
ART="${WORKSPACE}/.remap"
TS="$(date +%Y%m%d-%H%M%S)"
LOG="${ART}/run-${TS}.log"
LASTMSG="${ART}/last-msg.txt"
VERDICT="${ART}/verdict.txt"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$ART"
cd "$WORKSPACE"

read -r -d '' PROMPT <<EOF || true
Regenerate the HEMM codebase map. Explore this two-repo workspace and OVERWRITE
${OUT} with a fresh, accurate map. Do NOT stage or commit anything.

Workspace layout (workspace root is a git repo; the two children are nested,
independently-versioned git repos):
- hemm/   — core, "home base": pure-Python (import hemm_core), plus specs/,
            .specify/, and gate tooling in tools/.
- ha-hemm/ — Home Assistant custom integration (domain hemm),
            custom_components/hemm/, tests/integration/, depends on the core.

Produce exactly these top-level sections, in this order, as a Markdown document
that starts with a single "# HEMM Codebase Map" H1:
  1. Workspace Topology
  2. The Primitive Component Model (the architectural heart: manifest.to_components
     -> source/sink/storage/converter/node; both solver backends build from
     primitives, no named-type dispatch)
  3. Module Guide — hemm_core (core repo)
  4. Module Guide — ha-hemm (integration repo, custom_components/hemm/)
  5. Runtime + Actuator / Verification Engine
  6. Service API (services.py)
  7. Specs & FR Status (hemm/specs/) — derive statuses from req-tagged tests
  8. The Gate (cross-repo traceability tooling, hemm/tools/)
  9. Container / Sim / Warp Test Setup (ha-hemm/tests/)
  10. Conventions & Gotchas
  11. Navigation Guide

Be concrete: name real modules, classes, and file paths. Verify claims against
the code rather than restating prior docs. Write only ${OUT} — no other files.
EOF

# workspace-write lets Codex read both child repos and write the single map file.
# -C roots the sandbox at the workspace; -o captures the final summary apart from
# the streaming transcript. The workspace root is intentionally NOT a git repo
# (the two children are independent repos), so --skip-git-repo-check is required
# or Codex refuses to run outside a trusted git directory. < /dev/null keeps it
# from blocking on stdin in a detached/background run. Output redirected off stdout.
set +e
codex exec "$PROMPT" \
  --sandbox workspace-write \
  --skip-git-repo-check \
  -C "$WORKSPACE" \
  -o "$LASTMSG" \
  >"$LOG" 2>&1 </dev/null
CODEX_RC=$?
set -e

if [ "$CODEX_RC" -ne 0 ]; then
  printf 'REMAP FAIL  codex exec exited %s  — see %s\n' "$CODEX_RC" "$LOG" | tee "$VERDICT"
  exit 1
fi

# Deterministic, token-free correctness check. Its single line is the verdict.
python3 "${HERE}/remap_verify.py" --map "$OUT" | tee "$VERDICT"
RC=${PIPESTATUS[0]}
printf 'log: %s\n' "$LOG"
exit "$RC"
