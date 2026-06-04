# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Primitive component model (spec 003)**: device manifests now compile (`to_components()`) to a fixed set of five physics primitives — `source` / `sink` / `storage` / `converter` / `node`. Both solver backends build from these primitives; no named-device-type `isinstance` dispatch remains in either solver. Adding a device type is now a manifest + mapping, with zero solver code (proven by a `pool_pump` that plans on both backends with the two solver files unchanged).
- **Backend B rebuilt on the component model**: the per-type `ConsumerModel` factory is replaced by per-primitive consumers. Re-running the A/B gate after the refactor, the distributed backend now tracks the central MILP within ~1.2% average cost and converges on all 6 standard scenarios (previously ~96% gap, 1/6). The MILP remains the default because it is exact.
- **Constraint windows target primitive state vars**, not device types (`min_soc_until` → any storage level; `hold_temp_band`/`reach_min_temp_once` → any thermal node), so constraint/device combinations compose without device-specific code.

### Added

- **`Primitive` enum** and the `ComponentSpec` family (`SourceSpec`/`SinkSpec`/`StorageSpec`/`ConverterSpec`/`NodeSpec`) in `manifest/components.py`; `ConverterSpec.factor_at(ctx)` generalizes the heat-pump COP curve to any converter.
- **Constraint-target validation**: a constraint aimed at a state variable a device's primitives do not provide (e.g. `min_soc_until` on a non-storage device) is now rejected with a clear message.
- **Primitive metadata in the exported schema** (`x-hemm-primitives`) and a `primitives_for_type()` helper — additive; existing manifests validate unchanged.

### Fixed

- Three scenarios carried constraints the old solver silently ignored (two device-id typos, one thermostat with no room); the new validation surfaced them and they are corrected so the constraints actually bind.

## [2026.5.2] - 2026-05-29

### Added

- **Zeitdynamik-Erweiterung**: `ControlClass` enum (`passive` / `reactive` / `planned`) on all device manifests
- **Plan reason annotation**: `PlanReason` enum on every `PlanSlot` (`pv_surplus`, `cheap_grid`, `constraint`, `idle`, `manual`, `safety_default`)
- **Envelope stubs**: `envelope_min_kw` / `envelope_max_kw` fields on `PlanSlot`, `envelope_tolerance_pct` on manifests (Phase 2 — declared, not yet populated)
- **Solver reason heuristic**: both MILP and Distributed solvers annotate plan slots with reason based on power/price/constraint analysis

### Fixed

- `hemm_core.__version__` now derives from the packaged `hemm` distribution version, with an editable-source fallback, so CLI and wheel metadata stay aligned.

## [2026.5.0] - 2026-05-11

### Added

- **Mandatory onboarding example tests** (`test_onboarding_examples.py`): 9 tests for onboarding + full_house scenarios, run in default fast suite
- **CI/CD overhaul**: CodeQL security scanning, auto-release (monthly), patch-release (on demand), hardened dependabot auto-merge, SECURITY.md, README badges
- **HA-style versioning**: vYYYY.M.PATCH convention (matching HA ecosystem)

### Fixed

- Device ID mismatches in `onboarding.yaml` (`ev_charger` → `ev_charger_garage`, `thermostat_living` → `bathroom_heater`)
- Device ID mismatches in `full_house.yaml` (`ev_charger` → `ev_charger_garage`, `water_heater_1` → `dhw`)

### Added (Phases 1–3)

- Initial project skeleton with `src/hemm/` layout
- CLI stub (`hemm --help`)
- Pytest configuration with markers (unit, container, pi, slow)
- Makefile with canonical targets
- Ruff + mypy strict configuration
- Pre-commit hooks
- GitHub Actions CI

#### Phase 1: Manifest schema & constraint vocabulary

- 7 manifest types (Pydantic v2 models): Room, ThermostatLoad, HeatPump, WaterHeater, Battery, PVForecast, EVCharger
- Constraint vocabulary v1 (7 types): ReachMinTempOnce, HoldTempBand, MinSocUntil, MinEnergyUntil, ForbiddenWindow, MinRuntimePerDay, MaxRuntimePerDay
- Version specifier resolver
- JSON Schema export via CLI (`hemm schema`)
- Manifest validator (`hemm validate`)
- Conflict resolution (higher penalty wins)
- Complete "simple house" manifest set in `testdata/manifests/`

#### Phase 2: Central MILP solver, sim harness, forecast adapters

- Pyomo-based MILP backend (Backend A) with HiGHS solver
- Piecewise-linear COP, plan-change penalty (L1 linearized)
- Forecast adapter framework (solcast, forecast_solar, template)
- Constraint-window manager (`hemm/constraints/`)
- Simulation harness (`hemm sim run <scenario.yaml>`)
- 6 standard scenarios in `testdata/scenarios/`
- Synthetic price + weather time series generators

#### Phase 3: Distributed solver (Backend B) & A/B comparison

- Distributed solver with price iteration and ADMM modes (`hemm/solvers/distributed.py`)
- Consumer models for all 7 manifest types (`hemm/solvers/consumers.py`)
- A/B comparison runner with CSV and Markdown report export (`hemm/sim/comparison.py`)
- CLI: `hemm sim run --solver distributed`, `hemm sim compare <scenarios...>`
- SimRunner now accepts any solver backend (not just MILP central)
