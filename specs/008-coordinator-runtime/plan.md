# Implementation Plan: Coordinator Runtime & Demand Service API

**Branch**: `008-coordinator-runtime` | **Date**: 2026-05-28 |
**Spec**: [spec.md](./spec.md)

**Note**: Retroactive. The coordinator, 8 services, and 5 events are built
(Phase 6). The price-override bug (FR-010) is fixed. Three runtime gaps remain:
automatic periodic solve (FR-004), rolling-horizon continuity proof (FR-005),
and a runtime TTL-expiry test (FR-009).

## Summary

`HemmCoordinator` (a `DataUpdateCoordinator`) holds runtime state and runs the
configured solver in an executor; `_async_update_data` only serves cached
results so HA setup never blocks. Services are the I/O surface: solve triggers
(`replan`/`tick`/`simulate`), backend switch (`set_solver`), price override
(`set_price_curve`), and demand registration (`add_constraint_window` /
`remove_constraint` / `bump_priority`). All side-effecting services accept
`dry_run`.

## Technical Context

**Language/Version**: Python 3.12 / 3.13
**Primary Dependencies**: HA `DataUpdateCoordinator`, event bus, services;
`hemm` core (solvers, `ConstraintWindowManager`, adapters) via deferred imports
**Testing**: unit (mocked core) + container (full solve path via hactl)
**Project Type**: Integration glue; solver/window logic stays in core `hemm`
**Constraints**: no blocking calls in the loop; all time via injected `Clock`
(SR-012); single-instance coordinator lookup

## Constitution Check

- **V. Clean Core/Integration Split** — OK. Solver, windows, adapters live in
  `hemm`; the coordinator orchestrates via deferred imports.
- **VI. Safe Write-Path** — `dry_run` is honored across services (FR-008). The
  *actuator* side of the write-path is Phase 7, not here.
- **III. Done = Green Tests** — `done` FRs are container-backed (solve, services)
  or unit-backed (non-blocking). The 3 partials are flagged because they lack a
  proving test or are not yet wired.

## Project Structure

```text
ha-hemm/custom_components/hemm/coordinator.py   # schedule, cache, solve, events
ha-hemm/custom_components/hemm/services.py      # 8 services + schemas
ha-hemm/custom_components/hemm/const.py         # service/event names
ha-hemm/tests/test_services.py                  # services + coordinator (unit, mocked core)
ha-hemm/tests/integration/test_hactl_services.py# full solve path + windows (container)
```

**Structure Decision**: Stable. The fixes are localized.

## Open Work (drives tasks.md)

- **FR-004** schedule a periodic solve (e.g. coordinator-driven `async_run_solver`
  on the tick, or a tracked time interval) instead of relying on an external
  `hemm.tick` automation. Respect plan-change penalty / stability.
- **FR-005** add a test asserting previous plans are fed back across ticks (pairs
  with 002:FR-011 plan-change penalty).
- **FR-009** add a runtime TTL-expiry test.

## Complexity Tracking

No violations. FR-004 (automatic periodic solve) is the largest remaining item
and is design-sensitive — it must not reintroduce blocking in the update path,
so it belongs on a tracked time interval, not in `_async_update_data`.
