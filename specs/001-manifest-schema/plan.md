# Implementation Plan: Manifest Schema & Constraint Vocabulary

**Branch**: `001-manifest-schema` (implemented in `hemm`) | **Date**: 2026-05-28
| **Spec**: [spec.md](./spec.md)

**Note**: Retroactive plan. Phase-1 work is implemented; this documents the
as-built design and the one open item (FR-013).

## Summary

Declarative, versioned device manifests + a small vendor-agnostic constraint
vocabulary form the contract every HEMM component reads. Implemented as Pydantic
v2 discriminated unions with an actionable validator, JSON-Schema export, and a
`hemm validate` CLI. One requirement (FR-013, verify-entity guard) is still open.

## Technical Context

**Language/Version**: Python 3.12 / 3.13

**Primary Dependencies**: Pydantic v2 (no HA imports — core repo)

**Storage**: Manifests as JSON files (`testdata/manifests/...`); no DB

**Testing**: pytest, `make test` (unit tier); `tests/test_manifest_types.py`

**Project Type**: Pure-Python library (`hemm` core)

**Performance Goals**: Validation is trivial (<1 ms/manifest); no perf gate

**Constraints**: No HA imports in core (Constitution V); v1 constraint semantics
frozen (Constitution II)

**Scale/Scope**: 7 manifest types, 7 constraint types, 4 message types

## Constitution Check

- **II. Manifest is the Contract** — PASS. Constraint types versioned via
  `VersionSpecifier`; v1 frozen; `CONSTRAINT_VERSIONS` is the single source.
- **V. Clean Core/Integration Split** — PASS. `hemm/src/hemm/manifest/` has no HA
  imports; entities/scripts are referenced as opaque strings.
- **VI. Safe Write-Path** — PARTIAL. `safe_default` mandatory ✅; verification
  contract modeled ✅; verify-entity self-confirm guard ⬜ (FR-013).
- **III. Done = Green Tests** — PASS for ✅ FRs (Phase-1 suite green).

## Project Structure

```text
hemm/src/hemm/manifest/
├── types.py          # 7 manifest types, Action, VerificationContract, RetryPolicy
├── constraints.py    # 7 constraint types, CONSTRAINT_VERSIONS, vocabulary
├── version.py        # VersionSpecifier.parse / matches
├── validator.py      # validate_manifest, _validate_constraint_endpoints
├── conflicts.py      # resolve_conflicts / find_conflicts (priority_penalty)
├── messages.py       # PlanMessage, PriceMessage, ConstraintWindow, slots
└── schema_export.py  # JSON Schema export for all types
hemm/src/hemm/cli.py  # `hemm validate <files>`
hemm/testdata/manifests/simple_house/*.json   # 7 fixtures
hemm/tests/test_manifest_types.py             # 23 tests (Phase-1 suite: 133)
```

**Structure Decision**: As-built; no restructure. FR-013 adds one validator rule
in `validator.py`, not a new module.

## Open Work (drives tasks.md)

- **FR-013 / SC-004**: verify-entity self-confirm guard. The validator needs to
  know which entity a script writes through. Since manifests reference scripts as
  opaque HA entity strings, the guard is heuristic: warn when `verify.entity`
  appears as the action's declared write target. Requires a small schema addition
  (an optional `writes_entity` hint on `Action`) OR a documented convention. This
  is a NEEDS-CLARIFICATION carried to `/speckit-clarify`.

## Complexity Tracking

No constitution violations to justify.
