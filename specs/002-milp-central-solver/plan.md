# Implementation Plan: Backend A — Central MILP Solver

**Branch**: `002-milp-central-solver` (in `hemm`) | **Date**: 2026-05-28 |
**Spec**: [spec.md](./spec.md)

**Note**: Retroactive. Phase-2 core is built; FR-009/010/011 are open.

## Summary

A single Pyomo model over all devices, solved by HiGHS, minimizing energy cost +
a linearized plan-change penalty, honoring device bounds, battery SoC dynamics,
and registered constraint windows. Open work: a thermal model (FR-009),
multi-objective weighting (FR-010), and per-device plan-change penalty (FR-011).

## Technical Context

**Language/Version**: Python 3.12 / 3.13
**Primary Dependencies**: Pyomo, `appsi_highs` (HiGHS); core repo, no HA imports
**Testing**: pytest `tests/test_solver.py`; sim cross-check via 005
**Project Type**: Pure-Python library
**Performance Goals**: milliseconds for standard setups; p95 < 5 s on Pi (Phase 8)
**Constraints**: oracle status protected (Constitution IV); `Clock`-injected time

## Constitution Check

- **IV. Two Backends, Data-Driven A/B** — PASS. Implements the shared
  `SolverProtocol`; is the default/oracle.
- **III. Done = Green Tests** — PASS for ✅ FRs; FR-009/010/011 need new tests.
- **VII. Time discipline** — PASS. Uses injected `Clock` for timing.

## Project Structure

```text
hemm/src/hemm/solvers/
├── protocol.py        # SolverProtocol, SolverResult, SolverStatus
├── milp_central.py    # MILPCentralSolver (model build, objective, extraction)
└── __init__.py
hemm/tests/test_solver.py
```

**Structure Decision**: As-built. FR-010/011 extend the objective in
`milp_central.py` (new weighted terms; penalty weight per device from manifest).
FR-009 adds thermal-state variables and band/reach constraints — the largest
change; may warrant a `thermal.py` helper.

## Open Work (drives tasks.md)

- **FR-009 thermal model**: introduce per-room temperature state driven by
  power, U-value, thermal mass; enforce `hold_temp_band` and
  `reach_min_temp_once`. Needs scenario fixtures with thermal dynamics.
- **FR-010 multi-objective**: add objective terms + weights; decide v1 objective
  set and defaults (NEEDS CLARIFICATION → `/speckit-clarify`). Pareto deferred to v2.
- **FR-011 per-device penalty**: read a per-device penalty (manifest field, likely
  v2 schema addition — coordinate with 001) instead of the global constant.

## Complexity Tracking

No current violations. FR-010 must resist over-generalization (weighted sum v1,
not a full Pareto solver) per Constitution simplicity intent.
