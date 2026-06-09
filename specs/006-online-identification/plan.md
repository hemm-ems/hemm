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

**Structure Decision**: RESOLVED (2026-06-09) — pure estimators go in core
(`hemm/src/hemm_core/identification/`), HA keeps repair-issue + sensor wiring.
Driver: the room model (FR-007) reuses the core occupant `ExogenousForecast`
(`sim/exogenous.py`), so it must live core-side; this also gives SR-011 its first
FR trace.

## Open Work (drives tasks.md)

- **FR-007** multi-input room grey-box RC model (sun / occupancy / insulation) in
  core, consuming `ThermalObservation` + reusing `ExogenousForecast`. The hardest
  and most valuable estimator — build first.
- **FR-008** identifiability ladder (1R1C → +solar → +occupancy), conservative
  gating; budget for ≥ 50 % rejection per roast #6.
- **FR-009** `predict_demand(horizon) -> ExogenousForecast` feeding the solver.
- **FR-003** remaining estimators per device type (HP COP, tank loss, battery
  efficiency, PV bias).
- **FR-004/005** repair-issue confirmation flow + `model_confidence` sensor.
- **FR-006** default-off + manual trigger.

## Cross-feature note

The `occupants-demand-sim` work (core PR #3 / ha-hemm PR #6) was the **generative**
counterpart: occupant profiles → `ExogenousForecast` → solver. Those PRs were
**closed as superseded (2026-06-09)** — they forked before the 003 component-model
refactor and their solver hooks (typed `RoomManifest` RC) can't merge onto the
generic `_add_node`. Their additive code (`sim/occupants/*`, `exogenous.py`,
synthetic profiles, tests) is salvageable on the undeleted `occupants-demand-sim`
branch.

This feature absorbs the generative side as its **inverse** (history → parameters
→ `ExogenousForecast`). FR-007 re-cuts the `ExogenousForecast` / `ThermalObservation`
contracts **fresh against the component model** (reusing the closed branch's
dataclasses as a starting point, not merging them), and FR-009 builds the
exogenous→solver wiring on `_add_node` directly — the port PR #3 could not do.
The simulator's synthetic profiles serve as SC-005 ground truth.

## Complexity Tracking

No violations yet. Risk is over-promising (roast #6): keep estimators conservative
and ship behind a manual trigger before any background mode.
