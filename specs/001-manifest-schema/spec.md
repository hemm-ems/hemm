# Feature Specification: Manifest Schema & Constraint Vocabulary (the Contract)

**Feature Branch**: `001-manifest-schema`

**Created**: 2026-05-28

**Status**: Retroactive — Implemented (Phase 1, completed 2026-05-06)

**Input**: Derived from `concept-hemm.md` ("Manifest is the contract"),
`implementation-plan-hemm.md` Phase 1, and the built code under
`hemm/src/hemm/manifest/`. Validated against `tests/test_manifest_types.py`
(23 tests; Phase-1 suite reported 133 tests, 98.51 % coverage).

> **Retro-spec convention.** This describes already-built behaviour. Each FR is
> tagged `✅ done` / `🔶 partial` / `⬜ todo`. `done` FRs are backed by existing
> tests; `⬜` FRs are live work (see `tasks.md`).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Declare a device without writing code (Priority: P1)

A user (or an LLM acting for them) describes a device — battery, heat pump, EV
charger — as a declarative manifest: what it is, which constraint types it
accepts, which actuator actions it can run with what verification, and its cost
shape. HEMM's solver consumes the manifest; no vendor- or device-specific code
is added to the core.

**Why this priority**: The manifest schema is the central design artifact of
HEMM. Every other capability (solvers, integration, actuator layer) reads it.
Without it there is no system.

**Independent Test**: Load each of the 7 manifest JSON files in
`testdata/manifests/simple_house/`, validate them, and confirm typed models are
returned with no code changes per device type.

**Acceptance Scenarios**:

1. **Given** a valid `battery.json` manifest, **When** `validate_manifest` runs,
   **Then** a typed `BatteryManifest` is returned.
2. **Given** a manifest missing `safe_default`, **When** validated, **Then**
   validation fails with a clear, actionable message naming the missing field.
3. **Given** a manifest with `type: "furnace"` (unknown), **When** validated,
   **Then** validation fails and lists the 7 known types.

### User Story 2 - Register demand against a versioned constraint vocabulary (Priority: P1)

A device manifest declares which constraint types it supports, each with a
semantic version specifier (`hold_temp_band: ">=1"`). At runtime, demand is
registered as a constraint window with numeric flex and a priority penalty.

**Why this priority**: The constraint vocabulary is how "when something is
needed" enters the optimizer. Versioning from day one prevents silent breakage.

**Independent Test**: Validate a manifest whose `constraint_endpoints` requires
`reach_min_temp_once: ">=1"` against the v1 vocabulary; confirm acceptance.
Validate one requiring `==2`; confirm rejection with a version-mismatch message.

**Acceptance Scenarios**:

1. **Given** `constraint_endpoints: {hold_temp_band: ">=1"}`, **When** validated
   against v1 vocabulary, **Then** it passes.
2. **Given** `{hold_temp_band: "==2"}`, **When** validated, **Then** it fails
   with "requires version ==2, but current vocabulary provides v1".
3. **Given** an unknown constraint name, **When** validated, **Then** it fails
   and lists the 7 known constraint types.

### User Story 3 - Safe actuation declared, not coded (Priority: P2)

Every manifest declares named actuator `actions`, each optionally carrying a
verification contract (entity / expected / within_seconds / timeout / retry),
plus a **mandatory** `safe_default` action used on HEMM failure or watchdog.

**Why this priority**: The verification contract is the differentiating safety
feature. The schema must capture it even though the executing engine ships in
Phase 7.

**Independent Test**: Construct an `Action` with a `VerificationContract` and a
manifest with a `safe_default`; confirm models validate and that a manifest
without `safe_default` is rejected.

**Acceptance Scenarios**:

1. **Given** a manifest with a valid `safe_default.script`, **When** validated,
   **Then** it passes.
2. **Given** a `safe_default` with an empty script, **When** validated, **Then**
   it fails with "safe_default must have a script defined".

### User Story 4 - Conflicting demands resolve deterministically (Priority: P2)

When two constraint windows target the same device and overlap in time, the one
with the higher `priority_penalty` wins — explicitly, never "first registered".

**Independent Test**: Feed two overlapping `ConstraintWindow`s for the same
device with different penalties to `resolve_conflicts`/`find_conflicts`; confirm
the higher-penalty window ranks first.

**Acceptance Scenarios**:

1. **Given** two windows for `dhw` with penalties 2.0 and 1.0, **When**
   conflicts are resolved, **Then** the 2.0 window precedes the 1.0 window.

### User Story 5 - Schemas exportable for tooling and LLM authoring (Priority: P3)

JSON Schema for every manifest type, constraint type, and message is exportable,
and a `hemm validate` CLI checks manifest files.

**Independent Test**: Call `get_all_schemas()` and confirm schema entries for all
7 manifests + 7 constraints + 4 messages; run `hemm validate <file>` on a good
and a bad manifest and check exit codes.

**Acceptance Scenarios**:

1. **Given** the export function, **When** called, **Then** it returns
   `manifest/*`, `constraint/*`, `message/*` JSON Schemas.

### Edge Cases

- Unknown manifest `type` → rejected, lists known types.
- Missing `safe_default` → rejected before Pydantic parsing.
- Malformed version specifier (e.g. `~1`) → rejected with format guidance.
- Constraint requiring a version the vocabulary does not provide → rejected.
- **Verification blind spot**: `verify.entity` equal to the entity the action's
  own script writes through (`writes_entity`) makes the contract self-confirming
  — now flagged with a `ManifestWarning` (FR-013).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `✅ done` `SR-006`: System MUST provide 7 manifest types — `room`,
  `thermostat_load`, `heat_pump`, `water_heater`, `battery`, `pv_forecast`,
  `ev_charger` — as a discriminated union on `type`.
- **FR-002** `✅ done` `SR-006`: Each manifest MUST carry `device_id`, `name`,
  `constraint_endpoints`, `actions`, and a mandatory `safe_default`.
- **FR-003** `✅ done` `SR-009`: System MUST reject a manifest lacking `safe_default`, or
  whose `safe_default` has no script, with an actionable message.
- **FR-004** `✅ done` `SR-006`: System MUST provide 7 constraint types — `reach_min_temp_once`,
  `hold_temp_band`, `min_soc_until`, `min_energy_until`, `forbidden_window`,
  `min_runtime_per_day`, `max_runtime_per_day` — as a discriminated union.
- **FR-005** `✅ done` `SR-006`: System MUST keep `min_soc_until` (state variable, %) and
  `min_energy_until` (cumulative kWh) semantically distinct.
- **FR-006** `✅ done` `unit` `SR-006`: Each constraint type MUST be semantically versioned;
  manifests declare endpoints with version specifiers (`>=`,`<=`,`==`,`!=`,`>`,`<`
  + integer).
- **FR-007** `✅ done` `unit` `SR-006`: System MUST validate `constraint_endpoints` against the
  current vocabulary versions and reject unknown types or unsatisfiable specs.
- **FR-008** `✅ done` `unit` `SR-009`: An `Action` MUST support an optional `VerificationContract`
  (`entity`, `expected`, `within_seconds`), a `timeout_seconds`, and a
  `RetryPolicy` (`max_attempts`, `backoff_seconds`).
- **FR-009** `✅ done` `unit` `SR-002`: System MUST define the core messages: `PlanMessage`,
  `PriceMessage`, `ConstraintWindow` (with numeric flex
  `flex_cost_per_hour_early`, `priority_penalty`, optional `ttl_seconds`).
- **FR-010** `✅ done` `unit` `SR-008`: Conflicting constraint windows for the same device MUST
  resolve by highest `priority_penalty`, deterministically and explicitly.
- **FR-011** `✅ done` `unit` `SR-006`: System MUST export JSON Schema for all manifest,
  constraint, and message types, and provide a `hemm validate` CLI.
- **FR-012** `✅ done` `SR-006`: The validator MUST NOT silently swallow unknown fields;
  errors are collected and reported together with clear locations.
- **FR-013** `✅ done` `unit` `SR-009`: The validator MUST warn (loudly) when an action's
  `verify.entity` is the same entity that the action's own `script` writes
  through directly, because such a contract is self-confirming and cannot detect
  a silently-ignored write. *(Source: `local-concept-roast.md` weakness #4.)*
  Implemented via an optional `Action.writes_entity` field and
  `manifest_warnings()` / `ManifestWarning` (emitted during `validate_manifest`).

### Key Entities

- **DeviceManifest**: discriminated union of the 7 typed manifests; the contract
  the solver reads. Contains vocabulary and references, never code.
- **ConstraintRequirement**: discriminated union of the 7 constraint payloads.
- **ConstraintWindow**: a registered demand with deadline, requirement, numeric
  flex, priority penalty, TTL.
- **Action / VerificationContract / RetryPolicy**: declarative actuator
  interface consumed by the Phase-7 actuator engine.
- **PlanMessage / PriceMessage**: solver outputs (plan) and Backend-B internal
  price signal.
- **ConstraintVocabulary / VersionSpecifier**: the versioned vocabulary and its
  matcher.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** `✅`: All 7 `testdata/manifests/simple_house/*.json` validate to
  typed models with zero per-device code.
- **SC-002** `✅`: Manifest test suite green (`make test`); Phase-1 coverage
  ≥ 80 % (reported 98.51 %).
- **SC-003** `✅`: Every invalid-manifest case (missing `safe_default`, unknown
  type, bad version spec, unknown constraint) produces an actionable error
  naming the field and the allowed values.
- **SC-004** `✅`: A manifest where `verify.entity` == the action's `writes_entity`
  produces a `ManifestWarning`; an independent sensor does not (covers FR-013).

## Assumptions

- A manifest contains no executable code — only vocabulary and references to HA
  entities/scripts; execution lives in the integration (Phase 7).
- v1 constraint semantics are frozen; new behaviour goes to a new type's v1 or an
  existing type's v2, never a silent change to v1.
- The 7-type catalog is sufficient for a typical house; new types arrive
  organically, each as its own spec extension.
- Schema validation uses Pydantic v2; this is an implementation detail the spec
  does not mandate, but the discriminated-union and actionable-error behaviour is
  required regardless of library.
