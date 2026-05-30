# AGENT.md

Norms for everyone working on HEMM — human or model. Shared norms are kept in sync between `hemm` (core) and `ha-hemm` (integration) so the rules don't drift; the core is the home base and additionally owns the specs/gate sections below.

## Repo layout

HEMM lives in two repos under one parent directory:

```
~/dev/hemm/
├── hemm/              # core (this repo or its sibling)
└── ha-hemm/           # HA integration (this repo or its sibling)
```

Claude Code is run on the parent directory `~/dev/hemm/`. Cross-repo edits in one session.

During development the integration imports the core via editable install:

```bash
cd ha-hemm
uv pip install -e ../hemm
```

For releases, `manifest.json` in `ha-hemm` pins a PyPI version of `hemm`.

## Tests

The canonical test commands are Make targets. Don't guess, don't run pytest directly:

| Command | When to use |
|---------|-------------|
| `make test` | Default. Unit tests only. Runs on every save during development. |
| `make ci` | What the lint+test CI minimally does. Run before pushing. |
| `make test-container` | Container-based integration tests. Docker must be running. |
| `make ci-full` | `ci` + `test-container`. Run before opening a PR. |
| `make test-slow` | Long-run sims. Mostly nightly CI or manual. |
| `make test-pi` | On Pi hardware only. Manual or self-hosted runner. |

`make test` MUST be fast (< 30s on a dev laptop). If it gets slow, something is wrongly tagged. Tests have markers (`unit`, `container`, `pi`, `slow`) and the default run excludes everything but `unit`. Don't bypass that.

After a code change: run linter, fix, then test. `make ci` does both in order.

## Requirement coverage & specs

This repo (`hemm`, the core) is the **home base**: it holds `specs/`, `.specify/`,
and the gate tooling (`tools/req_coverage.py`, `tools/branding_audit.py`). The
`ha-hemm` integration is a sibling checkout (`../ha-hemm`).

Functional requirements live in `specs/NNN-*/spec.md`. A `✅ done` status is
*derived*, not asserted — it must be backed by a test tagged with the FR id:

- Tag tests with `@pytest.mark.req("002:FR-001")` (or a `# REQ: 002:FR-001` comment). The `req` marker is registered in each repo's `pyproject.toml`.
- **Tiers matter.** By default a `done` FR must be proven by an *integration* test — one under `ha-hemm/tests/integration/`, run against a real HA container. Genuinely pure-logic FRs that HA can't observe opt out with a `` `unit` `` tag on the spec line.
- Gate: `make gate` (from this repo, with `../ha-hemm` checked out) runs `req_coverage.py --check` + `branding_audit.py`. It fails when a `done` integration-tier FR has only unit tests, when a `done` FR has no test, or when a test points at a missing FR. Regenerate the matrix with `python3 tools/req_coverage.py --markdown specs/coverage.md`. The authoritative run is this repo's Traceability CI workflow (checks out `ha-hemm` as a sibling, on push + nightly).

"Done" means proven end-to-end in Docker by default — not asserted by a shallow unit test. See `specs/README.md` for the full convention.

### Spec it, or don't — process vs. product

Not every change needs a spec/FR. Decide by *what the change affects*:

- **Product capability** — changes what HEMM *does* and is user-observable (solver behavior, manifest schema, services, sensors, the plan). → Full FR in `specs/`, traces to an SR, test-backed at its intended tier.
- **Dev-process / tooling / CI / release plumbing** — the gate, audits, workflows, build scripts, dev Make targets. → **No spec/FR.** Governed by `.specify/memory/constitution.md` and its own tagged tests (the way gate-hardening was).
- **Grey-zone (distribution/release)** — write an FR only per **user-observable outcome** ("installs via HACS"), never one per plumbing file.

When unsure, ask: would a HEMM *user* notice this? If yes → product → spec it. If only a *developer* notices → process → no spec.

## Working principles

**Plan before acting.** No change without a plan. Draft, review, then implement. The implementation plan and the concept doc are the contract — read them before proposing changes.

**Read before writing.** Read the relevant code, tests, and existing manifests first. No assumptions about code you haven't seen.

**Done = green tests.** A feature without tests is unfinished. A milestone without passing tests on the relevant tier is not done. Acceptance criteria in the implementation plan are non-negotiable.

**No speculative fixes.** If a test fails, understand why before touching code. Read the error, trace the cause, fix the root — not the symptom.

**Write-path always dry-run capable.** Any action that changes state in the real world (actuator calls, constraint modifications) must support a dry-run mode for testing and debugging.

## Time warp

All time reads in domain code go through an injected `hemm.time.Clock` —
never `datetime.now()` / `time.monotonic()` directly. Default is `WallClock`;
tests inject `FixedClock` or `VirtualClock`. The `make check-clock` audit
(`tools/check_clock.py`) breaks the build on direct calls.

The corresponding Docker-level time acceleration for the full HA stack
lives in the sibling `ha-hemm` repo (`Dockerfile.warp` + `libwarp.so`).
See `ha-hemm/docs/time-warp.md`.

## Make targets reference

- `make test` — fast unit tests (default pytest run)
- `make ci` — lint + typecheck + check-clock + test
- `make ci-full` — ci + container tests
- `make test-container` — container tests only
- `make test-container-sc SC=<id>` — single SC iteration (e.g. `SC=SC-005`)
- `make test-slow` — long-running sims
- `make test-pi` — Pi hardware tests
- `make gate` — cross-repo requirement-coverage + branding gate (needs `../ha-hemm`)
- `make req-coverage` — requirement-coverage check only
- `make branding-audit` — branding audit only
- `make lint` — ruff check + format check
- `make format` — auto-format
- `make typecheck` — mypy strict
- `make build` — build wheel
- `make remap` — regenerate `docs/CODEBASE_MAP.md` via the cartographer skill (requires the Claude Code CLI on `PATH`; the map file is gitignored in both repos)
