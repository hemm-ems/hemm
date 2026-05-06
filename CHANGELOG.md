# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

### Added

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
