# Implementation Plan: Forecast & Price Adapters

**Branch**: `004-forecast-price-adapters` (in `hemm`) | **Date**: 2026-05-28 |
**Spec**: [spec.md](./spec.md)

**Note**: Retroactive. Pattern + 3 adapters built; openmeteo + price adapters open.

## Summary

A canonical `ForecastPoint` schema plus an adapter protocol and registry let any
forecast/price source normalize into uniform solver input. Three solar adapters
and a generic template ship; `openmeteo` and dedicated price adapters remain.

## Technical Context

**Language/Version**: Python 3.12 / 3.13
**Primary Dependencies**: Pydantic v2; core repo, no HA imports
**Testing**: `tests/test_adapters.py`
**Project Type**: Pure-Python library
**Constraints**: new adapters MUST be additive (register only), no core edits

## Constitution Check

- **V. Clean Core/Integration Split** — PASS. Adapters are pure; HA wiring is in
  the integration.
- **III. Done = Green Tests** — PASS for ✅ FRs.

## Project Structure

```text
hemm/src/hemm/adapters/
├── protocol.py        # ForecastPoint, AdapterProtocol
├── registry.py        # AdapterRegistry + global singleton + builtins
├── solcast.py
├── forecast_solar.py
└── template.py
hemm/tests/test_adapters.py
```

**Structure Decision**: As-built. FR-006/007 add new files
(`openmeteo.py`, `tibber.py`/`awattar.py`/`entsoe.py`) and register them in
`_register_builtin_adapters`.

## Open Work (drives tasks.md)

- **FR-006**: `openmeteo` adapter.
- **FR-007**: price adapters (Tibber/aWATTar/ENTSO-E); confirm which to ship v1.

## Complexity Tracking

No violations. Resist adding adapters speculatively — ship sources users have.
