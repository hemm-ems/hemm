# Implementation Plan: Generic Entities — the Primitive Component Model

**Branch**: `003-generic-entities` | **Date**: 2026-06-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/003-generic-entities/spec.md`

## Summary

Make HEMM's "add a device type with no core code" thesis true by having both solver
backends dispatch on **five physics primitives** (`source` / `sink` / `storage` /
`converter` / `node`) instead of concrete Python manifest types. The 8 named manifest types
survive unchanged as the config/UX/validation surface and gain a declarative
`to_components()` compile step that lowers each to one or more `ComponentSpec`s. Backend A
(MILP) and Backend B (distributed) are re-pointed to build from the component set, replacing
the `isinstance` ladders in `solvers/milp_central.py` and `solvers/consumers.py`. The whole
change is **behavior-preserving**, gated by golden plan-parity (Backend A objective + per-slot
power identical within tolerance, all 7 `testdata/scenarios/*.yaml`) and the existing A/B
harness (Backend B `cost_gap_pct < 3%`). The falsifiable acceptance gate is a brand-new
`pool_pump` manifest that plans with zero solver-code changes.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: Pydantic v2 (manifest/component models), Pyomo + HiGHS
(`appsi_highs`, Backend A MILP), pytest with tiered markers + `req` coverage tags.

**Storage**: N/A — manifests are declarative YAML/JSON validated to Pydantic models;
no persistence introduced by this feature.

**Testing**: pytest. Unit tier for component model, `to_components()`, builders, parity, and
constraint generalization (pure solver/schema logic). One integration-tier test
(`pool_pump` thesis smoke, FR-012) proven through a real solve.

**Target Platform**: Pure-Python core (`hemm_core`), HA-independent (Constitution V).

**Project Type**: Library (solver/domain core) consumed by the `ha-hemm` integration.

**Performance Goals**: No regression. Backend A continues to solve standard scenarios to
`optimal` in well under `time_limit_seconds`; the component layer is a build-time
transformation, not a solve-time cost.

**Constraints**: Behavior-preserving (Constitution II + IV). Backend A objective value and
per-slot power MUST match pre-refactor golden within a documented numeric tolerance
(`abs ≤ 1e-6` on power kW, `rel ≤ 1e-9` on objective — solver-reformulation float noise only).
No HA imports in the core. No constraint-type version bumps.

**Scale/Scope**: 5 primitives, 8 named-type compile mappings, 2 solver backends, 7 golden
scenarios, ~3 manifest/solver modules touched + 1 new module (`manifest/components.py`).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|-----------|------|--------|
| **I. Spec Before Code** | Spec exists with testable FRs tracing to SRs | ✅ `spec.md` (12 FRs → SR-004/005/006) |
| **II. Manifest Is the Contract** | No new required manifest field; v1 constraint semantics unchanged; old manifests validate + behave identically | ✅ Compile step is additive; named types/fields frozen; FR-010 exposes metadata additively; golden parity (FR-006) proves identical behavior |
| **III. Done = Green Tests, Right Tier** | Each FR has a testable threshold at a declared tier | ✅ Parity tolerance + `cost_gap < 3%` + diff-proven "zero solver lines"; tiers tagged in spec |
| **IV. Two Backends, Data-Driven A/B** | No bias to either backend; no merge breaks A's oracle status | ✅ A cut over under golden parity; B migrated under existing `ABComparisonRunner` gate; oracle is the parity reference |
| **V. Clean Core/Integration Split** | No HA imports in core | ✅ Primitives are pure-Python solver specs; `manifest/components.py` lives in core |
| **VI. Safe Write-Path** | N/A | — Feature does not touch the actuator/verification path |
| **VII. Branding & Time Discipline** | No new HA identifiers; time via `Clock` | ✅ No HA-visible identifiers added; solver already uses injected `Clock` |
| **VIII. Spec It, or Don't** | Product capability ⇒ specced | ✅ User-observable (new device types plan; schema gains primitive metadata) ⇒ correctly specced |

**Result**: PASS — no violations, Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/003-generic-entities/
├── plan.md              # This file
├── research.md          # Phase 0 — design decisions (parity-safe bus balance, etc.)
├── data-model.md        # Phase 1 — Primitive enum, ComponentSpec, node/bus model
├── quickstart.md        # Phase 1 — how to add a new device with no solver code
├── contracts/
│   ├── components.md     # to_components() mapping table + ComponentSpec schema
│   └── solver-builder.md # per-primitive builder contract + bus balance + parity gate
├── checklists/
│   └── requirements.md  # spec quality checklist (already written)
└── tasks.md             # Phase 2 — /speckit-tasks (NOT created here)
```

### Source Code (repository root = `hemm/`)

```text
src/hemm_core/
├── manifest/
│   ├── types.py            # 8 named types (frozen); DeviceRole → Primitive (FR-011)
│   ├── components.py        # NEW — Primitive enum, ComponentSpec, ConverterSpec.factor_at, NodeSpec
│   ├── constraints.py       # constraint vocab (semantics frozen); targets become state-var/flow
│   ├── validator.py         # + primitive/component validation (additive, FR-010)
│   └── schema_export.py     # + primitive/component metadata in exported schema (FR-010)
└── solvers/
    ├── milp_central.py      # Backend A — build from components; remove isinstance ladders (FR-005/006)
    └── consumers.py         # Backend B — migrate to component model (FR-009)

testdata/
├── scenarios/*.yaml         # 7 golden-parity scenarios (unchanged inputs)
└── manifests/ (+ pool_pump) # NEW manifest for the thesis smoke test (FR-012)

tests/
├── test_components.py       # NEW unit — to_components() per type, round-trip (FR-001..004)
├── test_solver_parity.py    # NEW unit — golden plan-parity A before/after (FR-005/006)
├── test_constraints_generic.py # NEW unit — constraints on storage/node state vars (FR-008)
├── test_comparison.py       # existing A/B harness — B migration gate (FR-009)
└── (integration)            # pool_pump end-to-end thesis smoke (FR-012)
```

**Structure Decision**: Single pure-Python library (`hemm_core`). The only new module is
`manifest/components.py`; everything else is a behavior-preserving edit of existing solver
and manifest modules. The named types stay where they are; only their *dispatch* moves into
the component layer.

## Implementation Phases (maps to spec FRs and the 6-step sequencing)

1. **Component model behind the existing solver** (FR-001..004). Add `manifest/components.py`
   (Primitive enum, `ComponentSpec`/`ConverterSpec`/`NodeSpec`, `factor_at(ctx)`) and
   `to_components()` on all 8 named types. The solver still runs the old path; a unit test
   asserts every `testdata` manifest round-trips to a well-formed component set. No behavior
   change yet.
2. **Backend A cutover** (FR-005, FR-006, FR-007). Replace `_get_power_bounds`, the battery
   SoC block, the room RC block, and the heat-pump COP special-case with per-primitive
   builders + the parity-safe electrical-bus formulation (see research.md). Lift COP into
   `ConverterSpec.factor_at`. Gate: `test_solver_parity.py` green for all 7 scenarios.
3. **Constraint generalization** (FR-008). Re-point `_apply_constraint_windows` so each
   constraint targets a primitive state var / flow, not a device type. Semantics unchanged.
4. **Backend B migration** (FR-009). Replace the `ConsumerModel` subclass factory with
   component-driven local optimization; keep `ABComparisonRunner` green (`cost_gap < 3%`).
5. **Schema/validator + DeviceRole retirement** (FR-010, FR-011). Expose primitive/component
   metadata additively in `schema_export.py`/`validator.py`; fold `DeviceRole` into
   `Primitive`.
6. **Thesis smoke test** (FR-012). Add a `pool_pump` manifest (controllable `sink`); assert it
   plans end-to-end with zero lines changed in the two solver files (diff-proven).

## Complexity Tracking

> No Constitution violations — section intentionally empty.
