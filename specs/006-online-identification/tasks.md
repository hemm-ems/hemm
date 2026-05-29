---
description: "Task list for 006 Online Identification"
---

# Tasks: Online Identification

**Input**: [spec.md](./spec.md), [plan.md](./plan.md). `[X]` = built (stub) & registered.

## Phase 1: Built framework (Phase 5)

- [X] T001 [US1] `DeviceIdentifier` ABC + `IdentificationResult` — `ha-hemm/.../identification.py`
- [X] T002 [US1] 7 stub identifiers (one per device type) — `identification.py`
- [X] T003 [US1] `IDENTIFIER_REGISTRY` + `get_identifier` (warns on unknown) — `identification.py`

## Phase 2: Layout decision + estimators — FR-003 (🔶→⬜)

- [ ] T004 DECISION: estimators in core `hemm/src/hemm/identification/` vs stay in integration
- [ ] T005 Implement Room RC thermal-model identifier (first; highest value/risk)
- [ ] T006 Implement HP COP-curve, tank loss, battery efficiency, PV bias identifiers
- [ ] T007 [P] Synthetic-trajectory tests with known ground truth + tolerance (SC-002)

## Phase 3: Consent + transparency surface — FR-004/005 (⬜)

- [ ] T008 Raise a repair issue on significant change; apply only after confirmation
- [ ] T009 Expose `sensor.hemm_<device>_model_confidence`
- [ ] T010 [P] Tests: significant change → repair issue, not auto-applied (SC-003)

## Phase 4: Safe rollout — FR-006 (⬜)

- [ ] T011 Default-off + manual "try identifying my <device>" trigger (roast #7)
- [ ] T012 [P] Test: no identification runs until trigger fires (SC-004)

## Dependencies

- T004 blocks T005–T007. T005/T006 block T008. Phase 1 complete.
