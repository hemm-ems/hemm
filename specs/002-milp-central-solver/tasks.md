---
description: "Task list for 002 Backend A — Central MILP Solver"
---

# Tasks: Backend A — Central MILP Solver

**Input**: [spec.md](./spec.md), [plan.md](./plan.md). `[X]` = built & tested.

## Phase 1: Built (Phase 2)

- [X] T001 [US1] Define `SolverProtocol`/`SolverResult`/`SolverStatus` — `solvers/protocol.py`
- [X] T002 [US1] Build unified Pyomo model (power + on/off vars), solve via HiGHS — `solvers/milp_central.py`
- [X] T003 [US3] Per-device power bounds by manifest type — `milp_central.py`
- [X] T004 [US3] Battery SoC dynamics with efficiency + bounds — `milp_central.py`
- [X] T005 [US3] Translate forbidden/min_soc/min_energy/min-max-runtime windows — `milp_central.py`
- [X] T006 [US2] Linearized plan-change penalty (global weight) — `milp_central.py`
- [X] T007 [US1] HiGHS status mapping; never raise from `solve` — `milp_central.py`
- [X] T008 [US1] Piecewise COP interpolation + default map — `milp_central.py`
- [X] T009 [P] Solver tests — `tests/test_solver.py`

## Phase 2: Thermal model — FR-009 DONE (2026-05-28)

- [X] T010 Room `max_heating_kw` field + power lever; room/tank temperature state +
  linear RC dynamics — `manifest/types.py`, `solvers/milp_central.py::_build_thermal_state`
- [X] T011 [req 002:FR-009] Enforce `hold_temp_band` (room) and `reach_min_temp_once`
  (tank, big-M "once") against thermal state — `_apply_constraint_windows`
- [X] T012 [P][req 002:FR-009] Thermal tests incl. negative controls (infeasible when
  underpowered) — `tests/test_solver.py::TestThermalConstraints`
- [X] T012b Hardened FR-007: `solve(load_solutions=False)` → infeasible classifies as
  INFEASIBLE instead of raising → ERROR — `milp_central.py`

## Phase 3: Multi-objective — FR-010 (⬜)

- [ ] T013 CLARIFY: v1 objective set + default weights (`/speckit-clarify`)
- [ ] T014 Add weighted objective terms (cost, self-consumption, comfort, peak, export-cap)
- [ ] T015 [P] Tests: weight change shifts plan measurably (SC-003)

## Phase 4: Per-device plan-change penalty — FR-011 (⬜)

- [ ] T016 Schema: per-device penalty field (coordinate v2 with 001-manifest-schema)
- [ ] T017 Use per-device penalty in objective instead of global constant — `milp_central.py`
- [ ] T018 [P] Tests: HP penalty reduces HP transitions, EV unaffected (SC-004)
- [ ] T019 Run `make ci` green; re-run A/B (003) to confirm oracle status intact

## Dependencies

- T013 blocks T014–T015. T016 (schema) blocks T017. T010 blocks T011–T012.
- Phase 1 complete.
