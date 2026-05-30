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
Cover: topology, key modules, Phase 7 actuator/verification engine, FR statuses from
hemm/specs/, gate tooling, container test setup. The file is gitignored in both repos
— do not stage or commit.
EOF

exec claude -p "$PROMPT" --add-dir "$WORKSPACE/hemm" --add-dir "$WORKSPACE/ha-hemm"
