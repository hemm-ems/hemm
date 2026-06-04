#!/usr/bin/env bash
# Regenerate docs/CODEBASE_MAP.md via the cartographer skill, headless.
# Invoked from `make remap`; also safe to cron.
set -euo pipefail

WORKSPACE="/Users/jan/dev/repos/hemm"
OUT="${WORKSPACE}/docs/CODEBASE_MAP.md"

cd "$WORKSPACE"

read -r -d '' PROMPT <<EOF || true
Run the cartographer skill (cartographer-marketplace:cartographer) on this two-repo workspace.
Map both repos: hemm/ (core, home base — pure Python, specs/, .specify/, tools/) and
ha-hemm/ (HA integration, custom_components/hemm/, tests/integration/).
Write the result to ${OUT}, replacing current contents.
Cover: topology, key modules, the primitive component model (manifest.to_components ->
source/sink/storage/converter/node; both solver backends build from primitives, no
named-type dispatch), the actuator/verification engine, FR statuses from hemm/specs/,
gate tooling, container test setup. The file is gitignored in both repos
— do not stage or commit.
EOF

# Headless run needs write permission, or the cartographer skill generates the map
# in-context but its Write calls are denied (it then reports success without
# persisting). acceptEdits auto-accepts only file edits (the one thing a doc-regen
# needs) without bypassing other permission checks.
exec claude -p "$PROMPT" \
  --permission-mode acceptEdits \
  --add-dir "$WORKSPACE/hemm" --add-dir "$WORKSPACE/ha-hemm"
