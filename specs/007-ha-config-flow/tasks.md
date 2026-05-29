---
description: "Task list for 007 HA Config Flow & Tiered Device Setup"
---

# Tasks: HA Config Flow & Tiered Device Setup

**Input**: [spec.md](./spec.md), [plan.md](./plan.md). `[X]` = built & tested.

## Phase 1: Built hub + device flow (Phase 4/5)

- [X] T001 [US1] Hub config flow (name, horizon, iterations, adapters, backend) — `config_flow.py` (FR-001)
- [X] T002 [US1] Singleton guard — second flow aborts `already_configured` — `config_flow.py` (FR-002)
- [X] T003 [US1] Options flow add-device → select_device → configure_device — `device_flow.py` (FR-003)
- [X] T004 [US1] 7 tiered device schemas (beginner/advanced/pro) — `device_flow.py` (FR-005)
- [X] T005 Hub settings step in options flow — `config_flow.py` (FR-004)
- [X] T006 Clean setup/reload/unload — `__init__.py` (FR-007)

## Phase 2: Close correctness gaps

- [X] T007 FR-004: settings round-trip test (`test_options_flow_updates`) (SC-003)
- [X] T008 FR-006: `pro → advanced` downgrade test for unsupported type (SC-004)

## Dependencies

- Phase 1 complete. All FRs test-backed.
