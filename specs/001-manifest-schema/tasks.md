---
description: "Task list for 001 Manifest Schema & Constraint Vocabulary"
---

# Tasks: Manifest Schema & Constraint Vocabulary

**Input**: [spec.md](./spec.md), [plan.md](./plan.md)

**Note**: Retroactive. `[X]` = implemented & test-backed (Phase 1). `[ ]` = open
work. Paths are in the `hemm` core repo.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Foundational (built)

- [X] T001 [US1] Define 7 manifest types as discriminated union — `src/hemm/manifest/types.py`
- [X] T002 [US3] Model `Action`, `VerificationContract`, `RetryPolicy`, mandatory `safe_default` — `types.py`
- [X] T003 [US2] Define 7 constraint types + `CONSTRAINT_VERSIONS` + vocabulary — `src/hemm/manifest/constraints.py`
- [X] T004 [US2] Implement `VersionSpecifier.parse/matches` — `src/hemm/manifest/version.py`
- [X] T005 [US1] Implement `validate_manifest` with actionable, collected errors — `src/hemm/manifest/validator.py`
- [X] T006 [US2] Validate `constraint_endpoints` against vocabulary versions — `validator.py`
- [X] T007 [US4] Implement `resolve_conflicts`/`find_conflicts` by `priority_penalty` — `src/hemm/manifest/conflicts.py`
- [X] T008 [US1] Define `PlanMessage`/`PriceMessage`/`ConstraintWindow` + slots — `src/hemm/manifest/messages.py`
- [X] T009 [US5] JSON-Schema export for all manifest/constraint/message types — `src/hemm/manifest/schema_export.py`
- [X] T010 [US5] `hemm validate <files>` CLI — `src/hemm/cli.py`
- [X] T011 [P] 7 "simple house" manifest fixtures — `testdata/manifests/simple_house/*.json`
- [X] T012 [P] Manifest tests (23 in file; Phase-1 suite 133, 98.51 % cov) — `tests/test_manifest_types.py`

## Phase 2: FR-013 verify-entity guard — DONE (2026-05-28)

- [X] T013 DECISION: option A chosen — optional `writes_entity` hint on `Action`
  (additive, no v1 break) over a brittle naming convention.
- [X] T014 [req 001:FR-013] Validator warning when `verify.entity` == `writes_entity`:
  `manifest_warnings()` + `ManifestWarning`, emitted from `validate_manifest` —
  `src/hemm/manifest/{types,validator}.py`
- [X] T015 [P][req 001:FR-013] Tests: self-confirming warns; independent sensor and
  unset `writes_entity` do not — `tests/test_validator.py::TestVerifyIndependence`
- [X] T016 lint + format + mypy + check-clock + unit (275 passed) green

## Dependencies

- Phase 1 and Phase 2 complete.
