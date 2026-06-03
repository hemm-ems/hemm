---
description: "Task list for feature 003 — Generic Entities (Primitive Component Model)"
---

# Tasks: Generic Entities — the Primitive Component Model

**Input**: Design documents from `specs/003-generic-entities/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: INCLUDED — HEMM requires test-backed FRs (Constitution III) and the
`tools/req_coverage.py` gate fails any `✅ done` FR without a `req`-tagged test at its tier.
Test tasks carry their `req` tag (`003:FR-NNN`).

**Repo root for paths**: `hemm/` (core). Integration tests live in `ha-hemm/tests/integration/`.

**Orchestration note (this project)**: implementation is delegated to **Codex** per phase;
**a subagent evaluates Codex's diff/output** (not bulk-read into the orchestrator); when a
result is uncertain, run **`/code-review` or a Codex review pass**. See memory
`codex-orchestration-on-hemm`. Codex stages **explicit paths only** (never `git add -A`).

---

## Phase 1: Setup (baseline + test scaffolding)

**Purpose**: Capture the parity oracle BEFORE any code changes, and stand up test scaffolding.

- [X] T001 Capture the pre-refactor Backend A golden baseline (objective value + per-slot power per device) for all 7 `testdata/scenarios/*.yaml`, committed as fixtures under `testdata/golden/003_backend_a/<scenario>.json`. **Must run before any solver edit** — it is the only parity reference (plan risk note). _Captured via `tools/capture_golden_003.py` at the pinned instant `CANONICAL_NOW=2026-05-07T00:00Z` (all scenario deadlines inside the 24h horizon); all 7 solve `optimal`, deterministic on re-run._
- [X] T002 [P] Add a parity helper (load golden, compare objective within `rel ≤ 1e-9` and per-slot power within `abs ≤ 1e-6`) in `tests/_parity.py`. _Also hosts the canonical deterministic `solve_scenario()` shared by capture + parity._
- [X] T003 [P] Create empty test modules `tests/test_components.py`, `tests/test_solver_parity.py`, `tests/test_constraints_generic.py`; confirm the `req` marker is registered in `pyproject.toml`. _`req` marker present at `pyproject.toml` line 94._

---

## Phase 2: Foundational — the component model (BLOCKS all user stories)

**Purpose**: `manifest/components.py` + `to_components()` exist and round-trip, behind the
unchanged solver. No behavior change yet.

**⚠️ CRITICAL**: No user-story phase can begin until this is complete.

- [X] T004 Define the `Primitive` enum (`source`/`sink`/`storage`/`converter`/`node`) in `src/hemm_core/manifest/components.py`. [FR-001]
- [X] T005 Define the `ComponentSpec` family (`SourceSpec`/`SinkSpec`/`StorageSpec`/`ConverterSpec`/`NodeSpec`) in `src/hemm_core/manifest/components.py`, including `ConverterSpec.factor_at(ctx)` lifting `_piecewise_cop` (clamped at ends). [FR-001, FR-007]
- [X] T006 Implement `to_components()` on all 8 named types in `src/hemm_core/manifest/types.py` per the data-model.md mapping table (incl. **ThermostatLoad *and* HeatPump `room_id` conditional → converter else `sink`**, research D4 symmetry, and WaterHeater node+converter+storage). [FR-002] (depends on T004, T005)
- [X] T007 Fold `DeviceRole` into `Primitive`: remove `_TYPE_ROLES`, replace with the type→primitive(s) mapping, update `src/hemm_core/manifest/__init__.py` `__all__`. [FR-011] (depends on T004)
- [X] T008 [P] Unit test: `Primitive` has 5 members and `DeviceRole` is gone/folded, in `tests/test_components.py`. `# REQ: 003:FR-001, 003:FR-011`
- [X] T009 [P] Unit test: `to_components()` per type (×8) yields the expected primitive set, and the compile path contains no `isinstance`-on-named-manifest-type, in `tests/test_components.py`. `# REQ: 003:FR-002, 003:FR-003`
- [X] T010 [P] Unit test: every `testdata/scenarios/*.yaml` manifest round-trips to a well-formed component set, in `tests/test_components.py`. `# REQ: 003:FR-004`

**Checkpoint**: component model proven; solver still on the old path.

---

## Phase 3: User Story 2 — Existing manifests behave identically (Priority: P1) 🎯 parity gate

**Goal**: Backend A builds from the component set and produces plans identical (within
tolerance) to the golden baseline — the oracle is preserved.

**Independent Test**: `tests/test_solver_parity.py` green for all 7 scenarios vs. T001 golden.

- [X] T011 [US2] Implement the five per-primitive Backend A builders (sink/source/storage/converter/node) in `src/hemm_core/solvers/milp_central.py`, dispatching on `component.primitive`. [FR-005]
- [X] T012 [US2] Implement the parity-safe electrical bus (open, tariff-priced grid-exchange term — NOT a hard `Σ=0`; thermal nodes keep the real RC balance) in `src/hemm_core/solvers/milp_central.py`. [FR-005, research D1]
- [X] T013 [US2] Remove the `_get_power_bounds` isinstance ladder, the battery SoC block, the room RC block, and the heat-pump COP special-case — replaced by the component-driven build; no `isinstance`-on-named-type remains in `milp_central.py`. [FR-005] (depends on T011, T012)
- [X] T014 [US2] Route converter heat injection through `ConverterSpec.factor_at(ctx)` and delete `cop_at_temp` HP special-casing in `src/hemm_core/solvers/milp_central.py`; a HeatPump with no `room_id` builds as a `sink` (research D4 symmetry), preserving the `heat_pump_shift`/`full_house` parity. [FR-007] (depends on T011)
- [X] T015 [US2] **Per-device** parity test (research D8) in `tests/test_solver_parity.py`, using `tests/_parity.py` (`solve_scenario` + `compare_to_golden`): for every device **not** in the FR-006 divergence allowlist, assert per-slot power within `abs ≤ 1e-6` of its T001 golden and per-scenario objective within `rel ≤ 1e-9` (for scenarios with no diverging device); for each allowlisted device (`dhw` in `water_heater_legionella`+`full_house`; `ev_charger_garage` in `onboarding`) assert it **now acts** (non-zero power where the golden was zero — the constraint binds); and **fail on any unlisted divergence**. Empirically confirm the at-risk `ev_charger_garage` `min_energy_until` (control_class_mix/full_house): if it diverges, add it to the allowlist here and in spec FR-006 with justification. Full "reaches 60 °C / target SoC" correctness lives in T022 (US3). `# REQ: 003:FR-005, 003:FR-006`
- [X] T016 [US2] Unit test: `factor_at` piecewise interpolation + end clamping, in `tests/test_components.py`. `# REQ: 003:FR-007`

**Checkpoint**: Backend A is component-driven and the oracle is intact.

---

## Phase 4: User Story 1 — Add a new device with zero solver code (Priority: P1) 🎯 the thesis

**Goal**: A brand-new `pool_pump` manifest plans correctly with no edits to either solver
file — the falsifiable proof of the product thesis.

**Independent Test**: pool_pump gets a valid plan through a real HA replan; `git diff --stat`
shows 0 changed lines in the two solver files.

**Depends on**: Phase 3 (Backend A must build generically before a new type can plan code-free).

- [X] T017 [P] [US1] Add a `pool_pump` manifest (controllable electrical `sink`, with `safe_default`) and its `to_components()` mapping — `testdata/manifests/pool_pump.yaml` + a scenario including it. [FR-003, FR-012]
- [ ] T018 [US1] Integration test: pool_pump plans end-to-end through an HA replan and gets a `sensor.hemm_*` plan; a `forbidden_window` zeroes its `on` across the window — `ha-hemm/tests/integration/test_pool_pump_thesis.py`. `# REQ: 003:FR-012`
- [X] T019 [US1] Diff guard (CI/unit): assert the pool_pump addition changes **0 lines** in `src/hemm_core/solvers/milp_central.py` and `solvers/consumers.py` (SC-001, SC-006). `# REQ: 003:FR-003`

**Checkpoint**: thesis proven — new device type, zero solver code.

---

## Phase 5: User Story 3 — Constraint/device combinations compose for free (Priority: P2)

**Goal**: Constraints target primitive state vars/flows, so `hold_temp_band` on a DHW node and
`min_soc_until` on an EV work without device-type-specific code.

**Independent Test**: `tests/test_constraints_generic.py` green; parity (T015) still green.

- [ ] T020 [US3] Re-point `_apply_constraint_windows` in `src/hemm_core/solvers/milp_central.py` to resolve each constraint's target from the device's primitives (storage `level` / node thermal state / flow integral), dropping the type/`hasattr(model,"temp")` branches. Semantics unchanged, no version bump. [FR-008]
- [ ] T021 [US3] Add validation in `src/hemm_core/manifest/validator.py`: a constraint targeting a state var the device's primitives do not provide is rejected with a clear message; a converter `output_bus` referencing an absent node is rejected. [FR-008, edge cases]
- [ ] T022 [US3] Unit test: `hold_temp_band` on a DHW node and `min_soc_until` on an EV plan feasibly; a bad-target constraint is rejected, in `tests/test_constraints_generic.py`. `# REQ: 003:FR-008`
- [ ] T023 [US3] Regression guard: re-run `tests/test_solver_parity.py` to confirm constraint generalization did not perturb golden plans.

**Checkpoint**: expressiveness dividend delivered; oracle still intact.

---

## Phase 6: User Story 4 — Backend B stays within the A/B gate (Priority: P2)

**Goal**: Backend B consumes the component model and still passes the A/B harness.

**Independent Test**: `ABComparisonRunner` over all scenarios — avg `cost_gap_pct < 3%`,
comfort ≤ A, stability ≤ 1.5×.

- [ ] T024 [US4] Replace the `ConsumerModel` subclass factory (`get_consumer_model`) in `src/hemm_core/solvers/consumers.py` with component-driven local price response (storage→arbitrage/deadline, converter→factor-weighted price, sink→cheapest-slots, source→forecast). [FR-009]
- [ ] T025 [US4] A/B gate test: avg `cost_gap_pct < 3%`, per-scenario comfort ≤ A, plan-stability ≤ 1.5×, in `tests/test_comparison.py`. `# REQ: 003:FR-009`

**Checkpoint**: both backends share the component contract; B within kill criteria.

---

## Phase 7: Polish & cross-cutting

- [ ] T026 [P] Add primitive/component metadata to `src/hemm_core/manifest/schema_export.py` and `validator.py` — additive only; older manifests gain no required field. [FR-010]
- [ ] T027 [P] Integration test: exported schema includes the primitive metadata and existing manifests validate unchanged — `ha-hemm/tests/integration/test_schema_primitives.py`. `# REQ: 003:FR-010`
- [ ] T028 [P] Regenerate the exported JSON-schema snapshot and run the branding/schema audits for the `DeviceRole`→`Primitive` rename.
- [ ] T029 Flip `specs/003-generic-entities/spec.md` FR statuses `⬜`→`✅` as their tests land; regenerate `python3 tools/req_coverage.py --markdown specs/coverage.md` and confirm `--check` / `make gate` green (needs `../ha-hemm`).
- [ ] T030 [P] Cartographer re-map (`make remap`) and add a component-model note to `docs/solver-decision.md`.
- [ ] T031 Run `quickstart.md` end-to-end as the final acceptance pass.

---

## Dependencies & Execution Order

- **Phase 1 (Setup)** → first; T001 (golden baseline) is a hard prerequisite for all parity work.
- **Phase 2 (Foundational)** → blocks every user story (component model must exist).
- **Phase 3 (US2 parity)** → depends on Phase 2; gates Phase 4.
- **Phase 4 (US1 thesis)** → depends on Phase 3 (generic Backend A) — **not** independent of US2 despite both being P1 (see Implementation Strategy).
- **Phase 5 (US3)** and **Phase 6 (US4)** → both depend on Phase 3; independent of each other, parallelizable.
- **Phase 7 (Polish)** → after the FRs it documents are green.

### Within phases / parallel opportunities

- T002, T003 parallel. T008, T009, T010 parallel (same new test file, distinct test fns — coordinate if one Codex agent). T026, T027, T028, T030 parallel.
- US3 (Phase 5) and US4 (Phase 6) can be two parallel Codex agents once Phase 3 is green.

---

## Implementation Strategy

**Honest MVP** = Phase 1 + Phase 2 + Phase 3 (US2) + Phase 4 (US1). The thesis (US1, P1)
cannot stand alone: it requires the component model (Phase 2) and a generic Backend A
(Phase 3, US2). That bundle is the first demonstrable, valuable increment — *new device type
plans, oracle proven intact*. US3 and US4 are additive P2 increments after that.

**Per-phase loop (orchestration)**: brief Codex on the phase (explicit file paths from this
file) → Codex implements + stages explicit paths → **subagent evaluates the diff and runs the
phase's `req`-tagged tests**, reporting failures only → on green, orchestrator confirms the
gate; **on doubt, `/code-review`** before moving on. Hard cap 2 Codex rounds per phase, then
finish inline.

**Parity is the spine**: never advance past Phase 3 with `test_solver_parity.py` red; re-run
it after Phase 5 (T023) and after any Backend A touch.

---

## Notes

- `[P]` = different files, no incomplete-dependency.
- Every `done` FR needs its `req`-tagged test green at its tier before T029 flips it — the
  gate is the source of truth, not the checkbox.
- FR-010 and FR-012 are **integration-tier** (tests under `ha-hemm/tests/integration/`); all
  others here are unit-tier.
- Capture T001 golden **before** touching `milp_central.py` — it is irrecoverable afterward
  without checking out the pre-refactor commit.
