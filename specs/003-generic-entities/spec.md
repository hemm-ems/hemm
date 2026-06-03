# Feature Specification: Generic Entities — the Primitive Component Model

**Feature Branch**: `003-generic-entities`

**Created**: 2026-06-03

**Status**: Draft

**Input**: Concept-change doc "Generic Entities (Primitive Component Model)"
(source material), amending `concept-hemm.md` (§"Manifest type catalog",
§"Constraint vocabulary") and specs [001-manifest-schema](../001-manifest-schema/spec.md),
[002-milp-central-solver](../002-milp-central-solver/spec.md). Governed by Constitution
principles **II** (Manifest Is the Contract) and **IV** (Two Backends, Data-Driven A/B).

> **Thesis-repair spec.** HEMM's headline thesis is *"plug-and-play of new device types
> without code changes."* Today that is false: the solvers dispatch on concrete Python
> manifest types via `isinstance` ladders in two files, so every new device needs solver
> code. This feature makes the thesis **true and demonstrable** by having the solvers
> dispatch on a small set of **physics primitives**; the 8 named types survive as the
> config/UX/validation surface and *compile down* to primitives. It is a
> **behavior-preserving refactor for every device whose behavior is already defined** —
> with one principled exception: a device that *today silently ignores* a constraint it has
> no state to represent (a water heater asked to reach 60 °C with no temperature state; an
> EV asked to hit a target SoC with no SoC state) begins to **honor** that constraint once
> it compiles to the right primitive. That is the US3 expressiveness gain, not a regression
> — the oracle never produced those plans — so it is gated by **correctness tests**, not
> golden parity, and the diverging devices are **enumerated** (FR-006). FRs are tagged
> `⬜ todo` / `🔶 partial` / `✅ done`; see [001](../001-manifest-schema/spec.md) for the
> manifest contract this builds on.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Add a new device type with zero solver code (Priority: P1)

A contributor (or advanced user) wants HEMM to plan a device HEMM has never seen — say a
pool pump. They write a manifest that declares the device's energy behavior in terms the
core already understands (a controllable electrical load with runtime constraints). HEMM
plans it correctly on the next tick **without a single line of new solver code** — no new
`isinstance` branch, no new per-type block in either backend.

**Why this priority**: This is the falsifiable proof of the product's headline thesis. If
it does not hold, the refactor delivered nothing. Everything else exists to make this safe.

**Independent Test**: Add a brand-new manifest (e.g. `pool_pump`) that compiles to a
controllable `sink`, run `MILPCentralSolver.solve()` on a scenario containing it, and
assert it gets a valid `PlanMessage` within its power bounds and honors a
`forbidden_window` — with no edits to `solvers/milp_central.py` or `solvers/consumers.py`.

**Acceptance Scenarios**:

1. **Given** a manifest composed only of existing primitives, **When** added to a scenario
   and solved, **Then** the device is planned correctly with no solver-code change.
2. **Given** that new device carries a `forbidden_window` constraint, **When** solved,
   **Then** its `on` variable is 0 across the window — the generalized constraint path,
   not a per-type branch, enforces it.

---

### User Story 2 - Existing manifests behave identically (Priority: P1)

An existing user's manifests (battery, EV, heat pump, water heater, rooms, PV, passive
loads) keep validating, and every device whose behavior the pre-refactor solver already
defined produces the **exact same plan** — same objective contribution, same per-slot
power. The change is invisible to them, *except* where the refactor makes a constraint
they already declared finally take effect (their water heater now actually reaches its
legionella target; their EV now actually hits its morning SoC) — a fix they asked for, not
a surprise.

**Why this priority**: Constitution II (Manifest Is the Contract) and IV (Backend A is the
oracle, no merge may break its oracle status). A refactor that changes a plan the oracle
*already produced* is a regression; making the oracle *start honoring* a constraint it
previously dropped on the floor is the opposite of a regression — but it is still a
behavior change, so it lives under correctness tests (US3), not under golden parity.

**Independent Test**: For every `testdata/scenarios/*.yaml`, capture Backend A's objective
value and per-slot power before the refactor (golden), then assert **per-device** parity
after the cutover for every device *except* the enumerated divergence set (FR-006), each of
which is instead asserted to honor its previously-ignored constraint (US3 / SC-004).

**Acceptance Scenarios**:

1. **Given** any standard scenario, **When** Backend A solves it through the component
   model, **Then** for every device not in the FR-006 divergence set the objective
   contribution and per-slot power match the pre-refactor golden within tolerance.
2. **Given** a device **in** the divergence set (e.g. the `water_heater_legionella` tank,
   the `onboarding` EV), **When** solved, **Then** it now honors the constraint it
   previously ignored (reaches 60 °C / reaches target SoC by the deadline) — validated by a
   correctness assertion, not golden equality.
3. **Given** any existing manifest file, **When** validated, **Then** it validates
   unchanged — no new required fields, no semantic shift.
4. **Given** the parity run, **When** a device *not* in the enumerated divergence set
   diverges from its golden, **Then** the gate fails (an unlisted divergence is a regression).

---

### User Story 3 - New constraint/device combinations compose for free (Priority: P2)

Because constraints target a **primitive's state var or flow** rather than a device type,
combinations that were previously impossible just work: a `hold_temp_band` on a hot-water
(DHW) node, a `min_soc_until` on an EV. The user declares the constraint against the
device; HEMM applies it through the generalized state-var path.

**Why this priority**: This is the expressiveness dividend that justifies the refactor
beyond cleanup — but it depends on US1/US2 landing safely first.

**Independent Test**: Add a `hold_temp_band` to a water-heater (DHW node) scenario; assert
the plan keeps the DHW temperature state within the band (and is infeasible when
underpowered). Add a `min_soc_until` to an EV; assert the EV reaches the SoC target by the
deadline slot.

**Acceptance Scenarios**:

1. **Given** a `hold_temp_band` on a DHW node, **When** solved, **Then** the DHW
   temperature state stays within the band across the horizon.
2. **Given** a `min_soc_until` on an EV, **When** solved, **Then** the EV's storage level
   reaches the target by the deadline slot.

---

### User Story 4 - Backend B stays within the A/B gate after migration (Priority: P2)

The distributed backend (Backend B) is migrated to consume the same component model as
Backend A, and it continues to pass the existing A/B comparison harness — cost gap under
3%, comfort violations no worse than A, plan stability within bound.

**Why this priority**: Constitution IV requires both backends to share the contract and B
to be measured against the oracle. The refactor must not silently regress B.

**Independent Test**: Run `ABComparisonRunner` over all standard scenarios after the B
migration; assert average `cost_gap_pct < 3%` and per-scenario comfort/stability gates hold.

**Acceptance Scenarios**:

1. **Given** all standard scenarios, **When** Backend B is run through the component model
   under `ABComparisonRunner`, **Then** average cost gap vs. Backend A is < 3%.

---

### Edge Cases

- A device whose named type maps to **multiple** primitives (WaterHeater → node +
  converter + storage): all sub-components must share the same `device_id` namespace and
  link correctly, and the single device must still emit one coherent `PlanMessage`.
- A converter whose `output_bus` (`room_id`) references a node that does not exist in the
  scenario → validation/solve error with a clear diagnostic, not a silent drop.
- A `ThermostatLoad` **or `HeatPump`** with **no** `room_id` → compiles to a plain `sink`,
  not a converter (degenerate-but-valid case; the no-`room_id` heat pumps in
  `heat_pump_shift` / `full_house` stay plain loads, preserving parity).
- A constraint targeting a state var the device's primitives do not have (e.g.
  `min_soc_until` on a device with no `storage` level) → rejected at validation with a
  clear message, not an opaque solver failure.
- COP factor evaluated outside the COP-map range → clamped to the nearest endpoint
  (unchanged behavior, now via the generic `factor_at(ctx)`).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `⬜ todo` `unit` `SR-006`: System MUST define a primitive/component model
  (`manifest/components.py`) with five primitives — **source**, **sink**, **storage**,
  **converter**, **node/bus** — each carrying only solver-relevant parameters (no HA, no
  UX) and, where applicable, a state variable (storage level/SoC; node thermal state).
- **FR-002** `⬜ todo` `unit` `SR-006`: Every named manifest type MUST expose a
  `to_components() -> list[ComponentSpec]` compile step. The 8 mappings are: PVForecast →
  `source`(elec); PassiveLoad → `sink`(elec, `controllable=False`, fixed profile); Battery
  → `storage`(elec); EVCharger → `storage`(elec, charge-only, deadline-aware); Room →
  `node`(thermal, RC dynamics, comfort band); HeatPump → `converter`(elec→thermal[`room_id`],
  factor = COP(outdoor_temp)) **or** `sink`(elec) if no `room_id` (degenerate, mirrors
  ThermostatLoad — a heat pump bound to no thermal node is a plain controllable load, as
  today); ThermostatLoad → `converter`(elec→thermal[`room_id`], η≈1)
  **or** `sink` if no `room_id`; WaterHeater → a DHW `node` + a `converter`(elec→DHW, η≈1)
  + `storage` on that node.
- **FR-003** `⬜ todo` `unit` `SR-006`: The compile step MUST be a declarative mapping
  table — no per-manifest custom Python. Adding a device type means adding a manifest that
  composes existing primitives, not new solver branches. (*Falsifies the thesis if violated.*)
- **FR-004** `⬜ todo` `unit` `SR-006`: Every `testdata/scenarios/*.yaml` manifest MUST
  round-trip through `to_components()` to a well-formed component set (verified before any
  solver is cut over).
- **FR-005** `⬜ todo` `unit` `SR-004`: Backend A (`solvers/milp_central.py`) MUST build its
  Pyomo model from the component set — one builder per primitive plus an explicit bus
  balance (`Σin = Σout` per node, electrical bus implicit/global) — replacing the
  per-concrete-type `isinstance` blocks (battery SoC, room RC, water-heater DHW,
  `_get_power_bounds` ladder).
- **FR-006** `⬜ todo` `unit` `SR-004`: The Backend A cutover MUST be proven by **per-device
  golden plan-parity**: for every device whose component mapping reproduces its pre-refactor
  solver treatment, the post-refactor per-slot power MUST equal the pre-refactor golden
  within a documented numeric tolerance, and each scenario's objective MUST match within
  tolerance *unless* it contains a divergence-set device (below). The following devices are
  an **intended capability gain** — pre-refactor they had no state variable to represent a
  constraint they already declared, so the oracle *silently ignored* it; once compiled to the
  right primitive they begin to honor it. They are **excluded from golden parity** and
  instead covered by US3 correctness tests (SC-004):
  - `dhw` in `water_heater_legionella` and `full_house` — WaterHeater → DHW `node`+`storage`
    gives it a thermal state, so `reach_min_temp_once` (60 °C) now binds (research D3).
  - `ev_charger_garage` in `onboarding` — EVCharger → `storage` gives it a SoC `level`, so
    `min_soc_until` (80 %) now binds (research D5/US3).
  - *(at-risk, confirm empirically in Phase 3)* `ev_charger_garage`'s `min_energy_until` in
    `control_class_mix` and `full_house`: the sink→storage remap must reproduce the same kWh
    delivery; if charge-efficiency perturbs it, the device joins this list with justification.

  Any device that diverges from its golden and is **not** in this enumerated set is a
  regression and MUST fail the gate. (*Constitution IV: the oracle's existing plans are never
  broken; making it honor a previously-dropped constraint is the opposite of breaking it.*)
- **FR-007** `⬜ todo` `unit` `SR-006`: COP interpolation MUST be lifted out of heat-pump
  special-casing into a generic `ConverterSpec.factor_at(ctx)` (the existing
  `_piecewise_cop` / `cop_at_temp` logic), so any converter can have a context-dependent
  factor; clamped at the COP-map ends (unchanged behavior).
- **FR-008** `⬜ todo` `unit` `SR-006`: Constraint-window application MUST target a
  primitive's state var or flow, not a device type: `min_soc_until` → any **storage** level
  var; `reach_min_temp_once` / `hold_temp_band` → any **node** with a thermal state var;
  `min_energy_until` → a flow integral on any sink/storage power var; `forbidden_window`,
  `min_runtime_per_day`, `max_runtime_per_day` → the device `on`/power var. Constraint-type
  **semantics are unchanged** (no version bumps).
- **FR-009** `⬜ todo` `unit` `SR-005`: Backend B (`solvers/consumers.py`) MUST be migrated
  to consume the same component model (retiring the per-type `ConsumerModel` subclass
  factory), and MUST continue to satisfy the existing A/B harness gate (avg
  `cost_gap_pct < 3%`, comfort violations ≤ A, plan-stability ratio ≤ 1.5×).
- **FR-010** `⬜ todo` `SR-006`: Primitive/component metadata MUST be added to the exported
  JSON schema and validator, exposed additively — **not** required of existing manifests
  (Constitution II). Existing manifests validate unchanged.
- **FR-011** `⬜ todo` `unit` `SR-006`: The dead `DeviceRole` enum MUST be folded into a new
  `Primitive` enum (`source`/`sink`/`storage`/`converter`/`node`). This is an accepted
  breaking change to the exported enum **name** in the schema; the type→primitive mapping
  replaces the current type→role mapping.
- **FR-012** `⬜ todo` `SR-006`: A brand-new device manifest (e.g. `pool_pump` → controllable
  `sink`) MUST plan correctly with **no** new solver code — the falsifiable thesis smoke
  test. This is the acceptance gate for the whole feature. (*integration tier: proven
  end-to-end through a real solve.*)

### Key Entities

- **Primitive**: the enum of solver dispatch targets — `source`, `sink`, `storage`,
  `converter`, `node` (replaces `DeviceRole`).
- **ComponentSpec**: a single primitive instance with its solver-relevant parameters,
  bus/node references, optional state var, and (for converters) a `factor_at(ctx)` hook.
  One named manifest compiles to one or more ComponentSpecs.
- **Bus / Node**: a balance point for a conserved quantity. The electrical bus is
  implicit/global; thermal zones (rooms, DHW tanks) are first-class nodes with optional
  state dynamics, capacity, and comfort band.
- **Named manifest types** (unchanged): Room, ThermostatLoad, HeatPump, WaterHeater,
  Battery, PVForecast, EVCharger, PassiveLoad — the config/UX/validation surface that
  compiles to primitives.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** `⬜`: A new device type (`pool_pump`) plans correctly with **zero** lines
  changed in `solvers/milp_central.py` and `solvers/consumers.py` (diff proves it) —
  covers FR-003, FR-012.
- **SC-002** `⬜`: Backend A per-slot power is identical (within documented tolerance) to the
  pre-refactor golden for every device **except** the enumerated FR-006 divergence set
  (`dhw`, the `onboarding` EV), and each diverging device instead provably honors its
  previously-ignored constraint; no unlisted device diverges — covers FR-005, FR-006.
- **SC-003** `⬜`: Every existing `testdata` manifest validates unchanged and round-trips to
  components — covers FR-004, FR-010.
- **SC-004** `⬜`: A `hold_temp_band` on a DHW node and a `min_soc_until` on an EV both plan
  feasibly without any device-type-specific constraint code — covers FR-008.
- **SC-005** `⬜`: After the Backend B migration, average `cost_gap_pct` across standard
  scenarios stays < 3% and comfort/stability gates hold — covers FR-009.
- **SC-006** `⬜`: The two solver files contain **no** `isinstance`-on-named-manifest-type
  dispatch after the refactor (the per-type ladders are gone) — covers FR-005, FR-009.

## Assumptions

- Backend A remains the oracle and MUST NOT be biased to flatter Backend B (Constitution IV).
- "Golden plan-parity" tolerance is a small absolute/relative numeric epsilon to absorb
  solver-reformulation float noise, not a behavior allowance; the intent is identical plans
  for every device **outside** the FR-006 divergence set. The divergence set is a
  closed, enumerated, justified list — not an open licence to change behavior; an unlisted
  divergence fails the gate.
- The pre-refactor golden was captured at the pinned instant `2026-05-07T00:00Z`
  (`tests/_parity.py::CANONICAL_NOW`) so every scenario's constraint deadlines fall inside
  the 24 h horizon and the constraints genuinely bind; the parity run re-solves at the same
  instant. (At an earlier `now` the deadlines fell outside the horizon and nothing bound — a
  trivial oracle.)
- The electrical bus is implicit/global (not declared per-manifest); thermal nodes are
  derived from `room_id` links and the WaterHeater DHW decomposition, kept solver-internal
  unless a later spec exposes them in the manifest schema.
- WaterHeater is modeled as `node + converter + storage` (resolved), giving DHW a real
  temperature/comfort state uniform with Room — superseding the 002 assumption that the
  tank is a simpler volume-derived thermal mass.
- The named types, their fields, and constraint-type semantics are frozen by this feature;
  only solver dispatch and the additive component layer change.
- Vendor/quirk logic stays in HA plug points; the core stays HA-import-free (Constitution V);
  the compile step is declarative data, not per-type code.

## Out of Scope

- Removing or renaming the 8 named manifest types (they remain the config/UX/onboarding
  surface; only *dispatch* changes).
- Vendor- or installation-specific behavior (stays in HA plug points, `concept-hemm.md`
  §"Device specifics").
- Any HA import in the core (Principle V untouched; primitives are pure-Python solver specs).
- New constraint *types* or version bumps (the vocabulary generalizes onto primitives with
  unchanged semantics).
- Exposing buses/nodes explicitly in the manifest schema as user-authored entities
  (candidate for a later spec; here they stay derived/solver-internal).
