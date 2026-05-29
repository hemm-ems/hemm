---
description: "Task list for 005 Simulation Harness & Scenarios"
---

# Tasks: Simulation Harness & Scenarios

**Input**: [spec.md](./spec.md), [plan.md](./plan.md). `[X]` = built & tested.

## Phase 1: Built (Phase 2/3)

- [X] T001 [US1] `Scenario` + YAML loader with manifest refs — `sim/scenario.py`
- [X] T002 [US1] `SimRunner` day-by-day rolling horizon + `SimMetrics` — `sim/runner.py`
- [X] T003 [US1] Standard scenarios — `testdata/scenarios/*.yaml`
- [X] T004 [US2] `ABComparisonRunner` + comparison metrics — `sim/comparison.py`
- [X] T005 [US2] CSV + Markdown report incl. decision-gate table — `sim/comparison.py`
- [X] T006 [P] Deterministic synthetic price/weather — `sim/synthetic.py`
- [X] T007 [P] Sim + comparison tests — `tests/test_sim.py`, `tests/test_comparison.py`

## Phase 2: Uncertainty evaluation — FR-007 (⬜)

- [ ] T008 CLARIFY: forecast-fan representation (quantile bands vs sampled realizations)
- [ ] T009 Generate scenario fans from a base scenario — `sim/` (new module or `runner.py`)
- [ ] T010 Run plan against the fan; aggregate worst-case / CVaR cost + violation spread
- [ ] T011 [P] Tests: a noisier fan yields a worse robustness metric (SC-003)

## Dependencies

- T008 blocks T009–T010. Phase 1 complete.
