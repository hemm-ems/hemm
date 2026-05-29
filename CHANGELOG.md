# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
