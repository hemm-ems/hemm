# Feature Specification: Backend A — Central MILP Solver (the Oracle)

**Feature Branch**: `002-milp-central-solver`

**Created**: 2026-05-28

**Status**: Retroactive — Implemented (Phase 2, completed 2026-05-06); open FRs carried forward

**Input**: Derived from `concept-hemm.md` ("Backend A: Central MILP"),
`implementation-plan-hemm.md` Phase 2, code under `hemm/src/hemm/solvers/`
(`protocol.py`, `milp_central.py`), and `local-concept-roast.md` weaknesses
#1 (multi-objective), #9 (per-device plan-change penalty). Validated against
`tests/test_solver.py`.

> **Retro-spec convention.** FRs tagged `✅ done` / `🔶 partial` / `⬜ todo`.
> See [001-manifest-schema](../001-manifest-schema/spec.md) for the shared
> contract this solver consumes.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One optimal plan across all devices (Priority: P1)

A user with PV + battery + EV + dynamic tariff gets a single, globally optimal
schedule per tick: when to charge the battery, when to charge the car, computed
together against the price forecast. Backend A is the default and the oracle all
other backends are measured against.

**Why this priority**: Without a trustworthy oracle there is no A/B decision and
no read-only plan to show users. This is the load-bearing solver.

**Independent Test**: Run `MILPCentralSolver.solve()` on the onboarding scenario
manifests and a price curve; assert status `optimal` and one `PlanMessage` per
device with slot powers within device bounds.

**Acceptance Scenarios**:

1. **Given** a battery + EV + price forecast, **When** solved, **Then** status
   is `optimal` and each device gets a `PlanMessage` over the horizon.
2. **Given** an infeasible constraint set, **When** solved, **Then** status is
   `infeasible` with a termination diagnostic, not a crash.
3. **Given** a solve exceeding `time_limit_seconds`, **When** solved, **Then**
   status is `timeout`, not silent acceptance.

### User Story 2 - Stable plans across ticks (Priority: P1)

Re-planning every tick must not make actuators short-cycle. The objective
includes a plan-change penalty: deviating from the previous plan's near-term
slots costs a little.

**Independent Test**: Solve twice with `previous_plans` supplied; assert the
second plan's near-term slots are penalized toward the previous plan (fewer
changes than with penalty = 0).

**Acceptance Scenarios**:

1. **Given** a previous plan and `plan_change_penalty > 0`, **When** re-solved
   with unchanged inputs, **Then** the new plan does not gratuitously differ.

### User Story 3 - Respect registered constraint windows (Priority: P2)

Active constraint windows (forbidden windows, min-SoC, min-energy, min/max
runtime) are translated into MILP constraints so the plan satisfies registered
demand by the deadline.

**Independent Test**: Add a `min_energy_until` window for the EV; assert the plan
delivers ≥ the required kWh before the deadline slot.

**Acceptance Scenarios**:

1. **Given** `min_energy_until: 60` by 07:00, **When** solved, **Then** EV
   cumulative energy before the deadline slot is ≥ 60 kWh.
2. **Given** a `forbidden_window`, **When** solved, **Then** the device's `on`
   variable is 0 for every slot in the window.

### Edge Cases

- `horizon/resolution` ≤ 0 → `ERROR` result, no model built.
- Empty price forecast → default €0.30/kWh fill (documented default).
- HiGHS raises → caught, returns `ERROR` with the exception in diagnostics.
- Heat-pump COP outside the COP-map range → clamped to the nearest endpoint.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `✅ done` `SR-004`: System MUST implement the `SolverProtocol`
  (`name`, `solve(...) -> SolverResult`) so backends are interchangeable.
- **FR-002** `✅ done` `SR-004`: System MUST build a unified Pyomo model over all devices
  with continuous `power[d,t]` and binary `on[d,t]` variables and solve via HiGHS.
- **FR-003** `✅ done` `unit` `SR-004`: System MUST enforce per-device power bounds by type
  (battery charge/discharge, EV/HP/thermostat/water-heater ≥ 0, PV/Room = 0).
- **FR-004** `✅ done` `unit` `SR-004`: System MUST track battery SoC across slots with charge
  efficiency and min/max SoC bounds.
- **FR-005** `✅ done` `unit` `SR-004`: System MUST translate `forbidden_window`, `min_soc_until`,
  `min_energy_until`, `min_runtime_per_day`, `max_runtime_per_day` into MILP
  constraints.
- **FR-006** `✅ done` `unit` `SR-004`: The objective MUST minimize energy cost plus a
  linearized plan-change penalty (absolute-deviation auxiliary variables).
- **FR-007** `✅ done` `SR-004`: System MUST map HiGHS termination to
  `optimal/feasible/infeasible/timeout/error` and never raise out of `solve`.
- **FR-008** `✅ done` `unit` `SR-004`: System MUST interpolate heat-pump COP from a
  piecewise-linear COP map (clamped at the ends; default map if none given).
- **FR-009** `✅ done` `unit` `SR-004`: Thermal constraints `hold_temp_band` (room) and
  `reach_min_temp_once` (water-heater tank) are enforced via linear RC
  temperature state. Rooms gain a `max_heating_kw` heat lever (v1: electrical =
  thermal, COP=1); tanks use volume-derived thermal mass + standby loss.
  `reach_min_temp_once` uses big-M binaries ("reach target at least once before
  deadline"). *(Was a no-op `pass`; fixing it also hardened FR-007: infeasible
  runs now classify as INFEASIBLE instead of raising → ERROR.)*
- **FR-010** `⬜ todo` `SR-004`: System MUST support **multi-objective** optimization —
  at minimum a documented weighted sum over {cost, self-consumption, comfort,
  peak, grid-export cap} with default weights; single-objective (cost) remains
  the v1 default. *(Source: roast weakness #1 — the #1 user-facing knob.)*
- **FR-011** `⬜ todo` `SR-003`: The plan-change penalty MUST be configurable **per
  device** (HP compressor cycles ≠ EV ramps ≠ battery), not a single global
  scalar. *(Source: roast weakness #9; today `PLAN_CHANGE_PENALTY_WEIGHT` is
  global.)*

### Key Entities

- **SolverProtocol / SolverResult / SolverStatus**: the backend contract and its
  typed outcome (`hemm/src/hemm/solvers/protocol.py`).
- **MILPCentralSolver**: the Pyomo+HiGHS implementation.
- **PlanMessage**: per-device output consumed by the integration and actuator.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** `✅`: Solves standard PV+battery+EV+tariff scenarios to `optimal`
  in milliseconds on a dev laptop; Phase-2 suite green (200 tests, ≥ 80 % cov).
- **SC-002** `✅`: Solver never raises out of `solve`; all failure modes map to
  a `SolverResult` status.
- **SC-003** `⬜`: With multi-objective enabled, changing the comfort weight
  measurably shifts the plan toward comfort at a quantifiable cost increase
  (covers FR-010).
- **SC-004** `⬜`: Per-device penalty: raising the HP penalty reduces HP on/off
  transitions without affecting EV ramp freedom (covers FR-011).
- **SC-005** `✅`: A room with `hold_temp_band` is feasibly heated within the
  band (and infeasible when underpowered); a water heater meets a
  `reach_min_temp_once` target (covers FR-009) —
  `tests/test_solver.py::TestThermalConstraints`.

## Assumptions

- Backend A is the oracle: it MUST NOT be biased to flatter Backend B (Constitution IV).
- Initial battery SoC is assumed 50 % at horizon start (documented simplification).
- Thermal v1 simplifications: room heat is electrical (COP=1); a single outdoor
  temperature; room initial temp = band midpoint (else 20 °C); tank initial temp
  45 °C, constant standby loss. COP-coupled room heating is a v2 extension.
- Uncertainty/robustness over forecasts is **out of scope here** and owned by
  [005-sim-harness](../005-sim-harness/spec.md) (scenario evaluation) and rolling
  MPC at the integration tick.
