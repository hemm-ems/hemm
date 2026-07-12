# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2026.7.2] - 2026-07-12

> The live-data spine (003:RW1). The solver now starts every run from the real
> home's measured state instead of hardcoded defaults, so the HA coordinator can
> feed it live price, PV and SoC. All additive with default-preserving fallbacks
> — golden parity is bit-identical (7/7).

### Added

- **Solver starts from measured state (FR-105)**: the solver protocol accepts a per-device `initial_state` (`{soc_kwh, temp_c}`). Backend A anchors storage SoC initialisation *and* the terminal-neutrality floor to the measured start (not `capacity·0.5`, so a low real SoC is no longer force-charged to 50 %) and starts thermal nodes from the measured temperature; Backend B's `StorageConsumer` starts from the measured level. Omitting `initial_state` is behaviour-preserving.
- **Weather-driven COP in Backend B (FR-106)**: the distributed backend's `ConverterConsumer` interpolates COP against the passed per-slot `weather_forecast` instead of the flat 5 °C default (Backend A already did).

### Notes

- No change was needed for the pre-fetched price `data=` path (`TemplateAdapter`/`ForecastSolarAdapter._from_data`) or for the `generation_forecast` overlay (`PVForecastManifest.to_components()` intentionally keeps `forecast=None` as the overlay hook) — the HA coordinator (ha-hemm) now supplies both.

## [2026.7.1] - 2026-07-11

> First PyPI release since 2026.5.2 — also delivers everything listed under
> [2026.6.1] below (primitive component model, Backend B rebuild, storage
> round-trip losses, RC room thermal estimator). The stray `v2026.6.0` /
> `v2026.7.0` tags were never published.

### Added

- **PV generation reaches the energy balance (FR-006)**: `PVForecastManifest.to_components()` now carries the runtime generation forecast into the solver instead of hardcoding `forecast=None`; the sim runner passes its synthetic PV series through `generation_forecast`.
- **Scenarios that cannot rot (FR-011/012/013)**: constraint windows support relative `deadline_offset_hours` (mutually exclusive with absolute `deadline`); `SimRunner` fails loud when every declared window is already expired at `t0`; sim metrics report per-window fulfillment, not just solve success.

### Fixed

- **Grid settlement and dispatch semantics in Backend A (FR-002, SC-001)**: per-slot net power across all devices is settled at import price vs. feed-in tariff (exports no longer credited at import price); plan-slot `mode` derives from actual power rather than the one-sided `on` binary.
- `find_conflicts` uses real interval overlap for constraint-window arbitration (001:FR-010 / remediation FR-032).
- Package `__version__` fallback literals kept in sync with `pyproject.toml`.

## [2026.6.1] - 2026-06-10

### Changed

- **Primitive component model (spec 003)**: device manifests now compile (`to_components()`) to a fixed set of five physics primitives — `source` / `sink` / `storage` / `converter` / `node`. Both solver backends build from these primitives; no named-device-type `isinstance` dispatch remains in either solver. Adding a device type is now a manifest + mapping, with zero solver code (proven by a `pool_pump` that plans on both backends with the two solver files unchanged).
- **Backend B rebuilt on the component model**: the per-type `ConsumerModel` factory is replaced by per-primitive consumers. Re-running the A/B gate after the refactor, the distributed backend now tracks the central MILP within ~1.2% average cost and converges on all 6 standard scenarios (previously ~96% gap, 1/6). The MILP remains the default because it is exact.
- **Constraint windows target primitive state vars**, not device types (`min_soc_until` → any storage level; `hold_temp_band`/`reach_min_temp_once` → any thermal node), so constraint/device combinations compose without device-specific code.

### Added

- **`Primitive` enum** and the `ComponentSpec` family (`SourceSpec`/`SinkSpec`/`StorageSpec`/`ConverterSpec`/`NodeSpec`) in `manifest/components.py`; `ConverterSpec.factor_at(ctx)` generalizes the heat-pump COP curve to any converter.
- **Constraint-target validation**: a constraint aimed at a state variable a device's primitives do not provide (e.g. `min_soc_until` on a non-storage device) is now rejected with a clear message.
- **Primitive metadata in the exported schema** (`x-hemm-primitives`) and a `primitives_for_type()` helper — additive; existing manifests validate unchanged.
- **Grey-box RC room thermal estimator (spec 006, FR-007)**: `identification/thermal.py` fits a multi-input room thermal model (sun/occupancy/insulation) via least squares, reporting fit quality and conditioning diagnostics.

### Fixed

- Three scenarios carried constraints the old solver silently ignored (two device-id typos, one thermostat with no room); the new validation surfaced them and they are corrected so the constraints actually bind.
- **Storage discharge efficiency was ignored by both solver backends**, making battery/EV round-trips effectively lossless and plans over-optimistic. The MILP now splits storage power into charge/discharge flows (with a binary preventing simultaneous charge+discharge) and drains SoC at `power/discharge_efficiency`; the distributed backend uses the same convention. Backend-A golden plans recaptured; obsolete parity allowlists retired.
- **`ForbiddenWindow` now also pins storage power to zero** during the window — previously a battery could still discharge inside a "must not operate" window.
- **`MinRuntimePerDay`/`MaxRuntimePerDay` respect the constraint-window deadline** instead of silently widening to the full planning horizon.
- **Thermal identification confidence is gated on conditioning**: an ill-conditioned fit (condition number > 500) now reports confidence 0.0 instead of a high R²-based score with unreliable parameters.
- Six bare `assert` statements in the MILP solve path replaced with explicit `TypeError`/`ValueError` raises (they vanished under `python -O`).

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
