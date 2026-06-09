---
description: "Task list for 006 Online Identification"
---

# Tasks: Online Identification

**Input**: [spec.md](./spec.md), [plan.md](./plan.md). `[X]` = built (stub) & registered.

## Phase 1: Built framework (Phase 5)

- [X] T001 [US1] `DeviceIdentifier` ABC + `IdentificationResult` — `ha-hemm/.../identification.py`
- [X] T002 [US1] 7 stub identifiers (one per device type) — `identification.py`
- [X] T003 [US1] `IDENTIFIER_REGISTRY` + `get_identifier` (warns on unknown) — `identification.py`

## Phase 2: Room thermal model — FR-007/008/009 (⬜)

- [X] T004 DECISION: estimators in core `hemm/src/hemm_core/identification/` (RESOLVED — see plan.md)
- [X] T005 Define `ThermalObservation` input — core (`identification/thermal.py`); `ExogenousForecast` output deferred to FR-009/T008
- [X] T006 Implement multi-input grey-box RC room estimator `{R, C, A_sol, Q_occ}` (FR-007) — core, least-squares, unit-tested (4 tests)
- [ ] T007 Identifiability ladder: 1R1C → +solar → +occupancy, info/condition gate, per-term confidence (FR-008)
- [ ] T008 [P] `predict_demand(horizon) -> ExogenousForecast` (FR-009)
- [ ] T009 [P] Synthetic-trajectory tests: recover known params from `sim/occupants` ground truth (SC-005); 1R1C-only fallback (SC-006)

## Phase 2b: Remaining device estimators — FR-003 (🔶→⬜)

- [ ] T010 Implement HP COP-curve, tank loss, battery efficiency, PV bias identifiers (core)
- [ ] T011 [P] Synthetic-trajectory tests with known ground truth + tolerance (SC-002)

## Phase 3: Consent + transparency surface — FR-004/005 (⬜)

- [ ] T012 Raise a repair issue on significant change; apply only after confirmation
- [ ] T013 Expose `sensor.hemm_<device>_model_confidence`
- [ ] T014 [P] Tests: significant change → repair issue, not auto-applied (SC-003)

## Phase 4: Safe rollout — FR-006 (⬜)

- [ ] T015 Default-off + manual "try identifying my <device>" trigger (roast #7)
- [ ] T016 [P] Test: no identification runs until trigger fires (SC-004)

## Dependencies

- T004 RESOLVED. T005 blocks T006; T006 blocks T007/T008/T009. T006/T010 block T012.
- FR-007 reuses `sim/exogenous.py` from `occupants-demand-sim` (core PR #3) —
  stabilise that contract first. Phase 1 complete.
