---
description: "Task list for 004 Forecast & Price Adapters"
---

# Tasks: Forecast & Price Adapters

**Input**: [spec.md](./spec.md), [plan.md](./plan.md). `[X]` = built & tested.

## Phase 1: Built (Phase 2)

- [X] T001 [US1] Canonical `ForecastPoint` + `AdapterProtocol` — `adapters/protocol.py`
- [X] T002 [US1] `AdapterRegistry` + global singleton + builtin registration — `adapters/registry.py`
- [X] T003 [US1] Solcast adapter — `adapters/solcast.py`
- [X] T004 [US1] Forecast.Solar adapter — `adapters/forecast_solar.py`
- [X] T005 [US2] Template fallback adapter — `adapters/template.py`
- [X] T006 [US1] Unknown-adapter lookup error lists available — `registry.py`
- [X] T007 [P] Adapter tests — `tests/test_adapters.py`

## Phase 2: Open adapters

- [ ] T008 [US?] Add `openmeteo` adapter + register it — `adapters/openmeteo.py` (FR-006)
- [ ] T009 CLARIFY: which price adapters ship v1 (Tibber/aWATTar/ENTSO-E)
- [ ] T010 Add chosen price adapter(s) + register — `adapters/*.py` (FR-007)
- [ ] T011 [P] Tests round-trip sample data for new adapters — `tests/test_adapters.py` (SC-003)

## Dependencies

- T009 blocks T010. Phase 1 complete.
