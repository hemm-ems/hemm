# Feature Specification: Forecast & Price Adapters

**Feature Branch**: `004-forecast-price-adapters`

**Created**: 2026-05-28

**Status**: Retroactive — Implemented (Phase 2, completed 2026-05-06); minor gaps open

**Input**: `concept-hemm.md` ("Forecast adapter pattern"), code under
`hemm/src/hemm/adapters/`, validated against `tests/test_adapters.py`.

> FRs tagged `✅ done` / `🔶 partial` / `⬜ todo`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Any PV forecast source works (Priority: P1)

PV forecast sources in HA are not standardized (Solcast, Forecast.Solar, local
models). A user picks an adapter by name; HEMM normalizes the source into a
canonical `[{timestamp, value, unit}]` series the solver can read.

**Why this priority**: The solver needs uniform forecast input; without
normalization every source would leak format details into the core.

**Independent Test**: Fetch via the `solcast` and `forecast_solar` adapters from
sample data; assert both return `list[ForecastPoint]` in chronological order
with correct units.

**Acceptance Scenarios**:

1. **Given** Solcast-shaped attribute data, **When** the `solcast` adapter
   fetches, **Then** it returns canonical `ForecastPoint`s sorted by time.
2. **Given** an unknown adapter name, **When** requested from the registry,
   **Then** a `KeyError` lists the available adapters.

### User Story 2 - Exotic sources via a template fallback (Priority: P2)

For any source without a dedicated adapter, a `template` adapter builds the
canonical schema from arbitrary sensor data, so new sources never require core
changes.

**Independent Test**: Configure the `template` adapter against a generic sensor
payload; assert it yields canonical points.

**Acceptance Scenarios**:

1. **Given** a generic sensor payload, **When** the `template` adapter fetches,
   **Then** canonical `ForecastPoint`s are produced.

### Edge Cases

- Adapter name not registered → `KeyError` with available names.
- Empty/malformed source payload → adapter returns an empty list or raises a
  clear error (no partial silent data).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `✅ done` `unit` `SR-007`: System MUST define a canonical `ForecastPoint`
  (`timestamp`, `value`, `unit`) schema all adapters emit.
- **FR-002** `✅ done` `SR-007`: System MUST define an `AdapterProtocol`
  (`name`, `source_type`, `fetch(**kwargs) -> list[ForecastPoint]`).
- **FR-003** `✅ done` `SR-007`: System MUST provide a registry with `register/get/
  list_adapters/has` and a global singleton seeded with built-ins.
- **FR-004** `✅ done` `SR-007`: System MUST ship `solcast`, `forecast_solar`, and
  `template` adapters.
- **FR-005** `✅ done` `unit` `SR-007`: An unknown adapter lookup MUST fail loudly, listing
  available adapters.
- **FR-006** `🔶 partial` `SR-007`: The concept names `openmeteo` as a built-in; it is
  **not** yet registered. System SHOULD add an `openmeteo` adapter.
- **FR-007** `⬜ todo` `SR-007`: Dedicated **price** adapters (Tibber, aWATTar, ENTSO-E)
  named in the concept are not yet shipped; price currently flows via the generic
  `template` adapter. System SHOULD add first-class price adapters.

### Key Entities

- **ForecastPoint**: canonical normalized data point.
- **AdapterProtocol / AdapterRegistry**: the extension surface; new sources are
  contributions, not core edits.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** `✅`: All three built-in adapters normalize sample data to canonical
  points; `tests/test_adapters.py` green.
- **SC-002** `✅`: Adding a new adapter requires no change to solver or registry
  internals beyond a `register()` call.
- **SC-003** `⬜`: `openmeteo` and at least one named price adapter ship and
  round-trip sample data (covers FR-006/007).

## Assumptions

- Adapters are pure (no HA imports); HA-specific wiring lives in the integration.
- `source_type` distinguishes solar/price/temperature/load for the same protocol.
