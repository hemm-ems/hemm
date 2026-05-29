# Implementation Plan: Online Identification

**Branch**: `006-online-identification` | **Date**: 2026-05-28 |
**Spec**: [spec.md](./spec.md)

**Note**: Retroactive. Framework + 7 stub identifiers built; estimators, consent
wiring, status sensor, and default-off trigger are open.

## Summary

A per-device-type identifier framework refines model parameters from HA history,
surfacing significant changes as repair issues (consent, not magic) with a
confidence sensor. Today the 7 identifiers are registered stubs that return
`None`; the estimators and the HA consent/trigger surface remain.

## Technical Context

**Language/Version**: Python 3.12 / 3.13
**Primary Dependencies**: HA (repair issues, sensors) for the surface; estimators
are numeric (candidate for core `hemm` to stay HA-free and testable)
**Testing**: integration unit tests + synthetic-trajectory tests
**Project Type**: Integration glue today; estimators may migrate to core
**Constraints**: conservative estimation (prefer `None`); default-off (roast #7)

## Constitution Check

- **V. Clean Core/Integration Split** — DECISION NEEDED. Pure numeric estimators
  belong in core (`hemm`) for standalone tests; only repair-issue/sensor wiring
  belongs in `ha-hemm`. Today everything is in the integration.
- **III. Done = Green Tests** — stubs are trivially "green" but prove nothing;
  FR-003 needs synthetic-trajectory tests with known ground truth.

## Project Structure

```text
ha-hemm/custom_components/hemm/identification.py   # ABC, 7 identifiers (stubs), registry
# Proposed: move estimators to hemm/src/hemm/identification/ (per concept doc),
# keep HA repair-issue + sensor wiring in ha-hemm.
```

**Structure Decision**: Open. Recommended: pure estimators in core, HA surface in
integration — coordinate with the concept doc's intended layout.

## Open Work (drives tasks.md)

- **FR-003** estimators per device type (RC thermal ID first — the hardest and
  most valuable; budget for ≥ 50 % rejection in practice per roast #6).
- **FR-004/005** repair-issue confirmation flow + `model_confidence` sensor.
- **FR-006** default-off + manual trigger.

## Complexity Tracking

No violations yet. Risk is over-promising (roast #6): keep estimators conservative
and ship behind a manual trigger before any background mode.
