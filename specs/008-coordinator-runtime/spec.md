# Feature Specification: Coordinator Runtime & Demand Service API

**Feature Branch**: `008-coordinator-runtime`

**Created**: 2026-05-28

**Status**: Retroactive — Built (Phase 6); price-override bug fixed, 3 runtime gaps open

**Input**: `concept-hemm.md` ("Plug point 1: demand registration", "Runtime
interaction" tick loop, "Plan-change penalty"), `implementation-plan-hemm.md`
Phase 6, code at `ha-hemm/custom_components/hemm/coordinator.py` and
`services.py`.

> FRs tagged `✅ done` / `🔶 partial` / `⬜ todo` with their parent System
> Requirement. This feature realizes **SR-003** (re-plan against reality on a
> periodic tick) and **SR-008** (demand enters through a service API driven by HA
> automations). Two FRs trace to neighbouring SRs: the universal `dry_run`
> behaviour to **SR-009** (safe write-path) and the manual price override to
> **SR-007** (price ingestion). The solve itself is owned by
> [002](../002-milp-central-solver/spec.md); windows by
> [001](../001-manifest-schema/spec.md).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Plan continuously against current state (Priority: P1)

A coordinator periodically pulls current state, runs the configured solver off
the event loop, and surfaces per-device plans and status through HA — without
blocking setup. Operators trigger a solve on demand via `hemm.replan` /
`hemm.tick`, and switch backends via `hemm.set_solver`.

**Why this priority**: This is the runtime heart — SR-003. Everything the user
sees (plan sensors, status) comes from here.

**Independent Test**: Call `hemm.replan` in a container; the device confidence
sensor reflects a mapped solver status (95/70).

### User Story 2 - Register demand from automations (Priority: P1)

An HA automation registers a constraint window (`hemm.add_constraint_window`)
with a deadline, requirement, numeric flex and TTL; HEMM optimizes timing within
it. The automation removes it (`hemm.remove_constraint`) or re-prioritizes it
(`hemm.bump_priority`) as conditions change. Every service supports `dry_run`.

**Why this priority**: This is plug point 1 (SR-008) — the canonical way demand
enters HEMM. Preconditions stay in HA.

**Acceptance Scenarios**:

1. **Given** a live hub, **When** `hemm.replan` is called, **Then** the solver
   runs and the plan/status surfaces on entities.
2. **Given** an automation, **When** it calls `add_constraint_window`, **Then**
   the window is registered and a `constraint_added` event fires; `remove` fires
   `constraint_resolved`.
3. **Given** any side-effecting service, **When** called with `dry_run: true`,
   **Then** the full path runs with no state change.

### Edge Cases

- No devices configured → solve is a no-op returning OPTIMAL.
- Price adapter failure → coordinator falls back to a flat price (logged).
- Removing a non-existent window fires no event.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `✅ done` `unit` `SR-003`: The solver MUST run off the event loop
  (executor) and `_async_update_data` MUST only serve cached results, so setup
  and refresh never block on a solve.
- **FR-002** `✅ done` `SR-003`: `hemm.replan` and `hemm.tick` MUST trigger a
  solve whose termination status and per-device plan surface through HA.
- **FR-003** `✅ done` `SR-003`: `hemm.set_solver` MUST switch the active backend
  at runtime (firing `solver_switched`), default `milp_central`.
- **FR-004** `🔶 partial` `SR-003`: HEMM MUST re-plan automatically on the
  periodic tick. *(Gap: the 15-min `update_interval` only refreshes cached data;
  it does NOT run the solver. A real periodic solve must currently be driven by
  an external automation calling `hemm.tick`. Wire a scheduled solve.)*
- **FR-005** `🔶 partial` `SR-003`: Each solve MUST feed the previous plans back
  in (rolling-horizon continuity) and record an `iteration_complete` event.
  *(Built in `async_run_solver`; no test asserts plan continuity across ticks —
  plan-change penalty is [002](../002-milp-central-solver/spec.md) FR-011, ⬜.)*
- **FR-006** `✅ done` `SR-008`: `hemm.add_constraint_window` MUST register a
  window (`window_id`, `device_id`, `deadline`, `requirement_type` + params,
  `flex_cost_per_hour_early`, `priority_penalty`, `ttl_seconds`) for all 7
  requirement types; an unknown type MUST be rejected.
- **FR-007** `✅ done` `SR-008`: `hemm.remove_constraint` (fires
  `constraint_resolved`) and `hemm.bump_priority` MUST manage windows by id.
- **FR-008** `✅ done` `SR-009`: Every side-effecting service MUST honor
  `dry_run: true` — run the full path with no state change.
- **FR-009** `🔶 partial` `SR-008`: Constraint windows MUST expire by TTL each
  solve (`expire_old`, firing `constraint_resolved`). *(Built; no runtime expiry
  test. Conflict-by-penalty is [001](../001-manifest-schema/spec.md) FR-010.)*
- **FR-010** `✅ done` `unit` `SR-007`: `hemm.set_price_curve` MUST inject a
  manual price curve for the next solve — `_get_price_forecast` consumes
  `_manual_prices` (at `_manual_price_resolution` spacing) ahead of the adapter.

### Key Entities

- **HemmCoordinator**: schedule, cached state, solver invocation, event firing.
- **8 services**: `replan`, `simulate`, `tick`, `set_solver`, `set_price_curve`,
  `add_constraint_window`, `remove_constraint`, `bump_priority`.
- **5 events**: `iteration_complete`, `constraint_added`, `constraint_resolved`,
  `solver_switched`, `dry_run_completed`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** `✅`: A container `replan` surfaces a mapped status on a device
  sensor (covers FR-002).
- **SC-002** `✅`: Add/remove/bump windows for all 7 requirement types succeed
  and fire the right events (covers FR-006/007).
- **SC-003** `✅`: Every side-effecting service called with `dry_run: true`
  leaves state unchanged (covers FR-008).
- **SC-004** `⬜`: A scheduled tick triggers a solve with no external automation
  (closes FR-004).
- **SC-005** `✅`: A manual price curve set via `set_price_curve` is returned by
  `_get_price_forecast` ahead of the adapter (covers FR-010).

## Assumptions

- The single-instance coordinator lookup (`_get_coordinator`) is valid because
  the hub is a singleton (007:FR-002).
- Mocked-core unit tests are acceptable for logic; the full solve path is proven
  only in container tests (the core `hemm` package is shadowed under unit tests).
