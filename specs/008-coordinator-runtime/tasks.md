---
description: "Task list for 008 Coordinator Runtime & Demand Service API"
---

# Tasks: Coordinator Runtime & Demand Service API

**Input**: [spec.md](./spec.md), [plan.md](./plan.md). `[X]` = built & tested.

## Phase 1: Built coordinator + services (Phase 6)

- [X] T001 [US1] Non-blocking coordinator (executor solve, cached update) — `coordinator.py` (FR-001)
- [X] T002 [US1] `hemm.replan` / `hemm.tick` solve triggers; status surfaces — `services.py` (FR-002)
- [X] T003 [US1] `hemm.set_solver` runtime backend switch + `solver_switched` — `coordinator.py` (FR-003)
- [X] T004 [US2] `hemm.add_constraint_window` (7 requirement types) — `services.py` (FR-006)
- [X] T005 [US2] `hemm.remove_constraint` / `hemm.bump_priority` + events — `services.py` (FR-007)
- [X] T006 [US2] Universal `dry_run` across side-effecting services — `services.py` (FR-008)
- [X] T007 TTL expiry on solve (`expire_old`) — `coordinator.py` (FR-009, partial)

## Phase 2: Close runtime gaps

- [X] T008 FR-010 (bug): `_get_price_forecast` consumes `_manual_prices` when set; falls back to adapter — `coordinator.py` (SC-005)
- [ ] T009 FR-004: schedule a periodic solve on the tick (no external automation), respecting plan stability (SC-004)
- [ ] T010 [P] FR-005: test that previous plans feed back across ticks (pairs with 002:FR-011)
- [ ] T011 [P] FR-009: runtime TTL-expiry test (window expires → `constraint_resolved`)

## Dependencies

- Phase 1 complete. T008 and T009 are independent; T010/T011 are test-only and
  parallelizable. T009 should land with or after 002:FR-011 (plan-change penalty).
