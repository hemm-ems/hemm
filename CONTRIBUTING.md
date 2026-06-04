# Contributing to HEMM

HEMM ships as two repos that depend on each other:

- **`hemm-ems/hemm`** — the pure-Python core (PyPI `hemm`, import `hemm_core`). **This repo.**
- **`hemm-ems/ha-hemm`** — the Home Assistant integration. Installs the core from
  this repo's `main` branch in CI (`pip install git+https://github.com/hemm-ems/hemm.git`).

Clone both under one parent directory so the cross-repo gates (`make gate`,
`make branding-audit`) can find the sibling checkout at `../ha-hemm`.

## Development Setup

1. Clone both repos under one parent directory
2. Create a virtual environment: `uv venv`
3. Install in dev mode: `uv pip install -e ".[dev]"`
4. Install pre-commit hooks: `uv run pre-commit install`
5. Enable the pre-push CI guard: `make hooks` (see below)

## Workflow

1. Create a branch from `main`
2. Make changes
3. **Run `make ci` and wait for green before every push.** This mirrors the
   required `Lint & Test` checks — running it locally is the difference between
   a 10-second fix and a red PR. `make hooks` wires this into `git push`
   automatically (skip a single push with `git push --no-verify`).
4. Open a PR with a Conventional Commit message

## Cross-repo PRs (core ↔ ha-hemm)

When a change spans both repos (e.g. a new device type added to the core and
consumed by the integration), **the core PR lands first.** ha-hemm's CI installs
the core from this repo's `main`, so its checks cannot go green until the core
change is on `main`.

**Merge order — follow it exactly to avoid a deadlock:**

1. Merge the **core** PR into core `main`.
2. **Re-run** the ha-hemm PR's failed checks (`gh run rerun <id> --failed`). The
   re-run reinstalls core `main` and picks up the new code.
3. Once green, merge the **ha-hemm** PR.
4. Cross-repo traceability reconciles on the nightly run — no manual step.

**Required vs. non-required checks.** Branch protection on core `main` requires
**only** `Lint & Test (Python 3.12)` and `Lint & Test (Python 3.13)`. The
`Requirement coverage + branding` check is **intentionally not required**: it
verifies SR → FR → test traceability *across both repos*, so it is red on a core
PR by design until the matching ha-hemm change also lands. It reconciles on the
nightly run.

> A core PR showing `MERGEABLE / UNSTABLE` with only `Requirement coverage`
> red is **mergeable** — that's the green light, not a blocker. Waiting for that
> check to pass before merging core is the deadlock: it can't pass until core is
> merged. Confirm the two required `Lint & Test` checks are green, then merge.

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation only
- `test:` adding/updating tests
- `chore:` tooling, CI, dependencies
- `refactor:` code change that neither fixes a bug nor adds a feature

## Code Style

- Ruff for linting and formatting (configured in `pyproject.toml`)
- mypy strict mode for type checking
- All tests require a marker (`unit`, `container`, `pi`, `slow`)
