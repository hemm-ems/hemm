# hemm — Testing Guide

This document explains how the hemm core library is tested. hemm is a pure-Python library with no Home Assistant imports — its tests verify manifest schemas, solvers, adapters, constraint managers, and simulation harnesses in isolation.

---

## Test Layers

hemm's tests are organized by speed and scope, controlled by pytest markers.

**Unit tests** (`@pytest.mark.unit` or unmarked) cover the vast majority: manifest types, constraint vocabulary, solver algorithms, adapter registry, validator, schema export, CLI commands, and message types. They run in under 10 seconds, require no external services, and are the primary feedback loop during development.

**Slow tests** (`@pytest.mark.slow`) run full multi-day simulations across all 6 standard scenarios. These take longer (30–60 seconds) and exercise the sim harness, synthetic data generators, and solver convergence over realistic horizons. They are excluded from the default `uv run pytest` run.

**Occupant simulation tests** cover canonical household profiles, parquet/CSV round-trips, calendar overlays, typed interventions, LPG fixture normalization, scenario parsing, and runner metrics. Unit tests use checked-in fixtures only and never invoke LPG.

**Property-based tests** use [Hypothesis](https://hypothesis.readthedocs.io/) for constraint validation and version specifier parsing. These generate random inputs and verify invariants (e.g., every valid constraint roundtrips through JSON, every version specifier comparison is consistent). They run as part of the unit suite.

---

## Running Tests

```bash
# Default: unit tests only (~9s)
uv run pytest

# Include slow simulation tests
uv run pytest -m "not pi"

# Slow tests only
make test-slow

# Full CI: lint + typecheck + unit tests
make ci

# Reproducible property-based tests
uv run pytest --hypothesis-seed=0

# Occupant A/B and sweep smoke
uv run hemm sim run testdata/scenarios/family4_winter_setback.yaml --ab-interventions
uv run hemm sim sweep testdata/scenarios/family4_winter_setback.yaml
```

---

## What the Tests Cover

| Test file | Marker | What it checks |
|---|---|---|
| `test_smoke.py` | unit | Import sanity, CLI `--help` / `--version` / `info` commands |
| `test_manifest_types.py` | unit | JSON round-trip for all 7 manifest types, testdata validation, `safe_default` mandatory |
| `test_constraints.py` | unit | All 7 constraint types with Hypothesis property-based validation |
| `test_constraint_manager.py` | unit | ConstraintWindowManager CRUD, expiry, TTL, priority sorting, per-device filtering |
| `test_messages.py` | unit | Plan/Price/Constraint messages, conflict resolution (higher penalty wins) |
| `test_validator.py` | unit | Manifest validator, constraint endpoint version checking, clear error messages |
| `test_version.py` | unit | Version specifier parsing (`>=`, `<=`, `==`, `!=`, `>`, `<`), Hypothesis tests |
| `test_schema_export.py` | unit | Schema export CLI, manifest/constraint/message schemas, validate command |
| `test_adapters.py` | unit | Adapter registry, ForecastPoint serialization, Solcast/ForecastSolar/Template adapters |
| `test_solver.py` | unit | MILP central solver, COP interpolation, constraints (min_soc, energy, forbidden, runtime), plan-change penalty |
| `test_consumers.py` | unit | All 7 consumer models respond to price signals, respect constraints, charge/discharge during favorable periods |
| `test_distributed.py` | unit | Distributed solver (price_iteration & ADMM modes), convergence, constraint handling |
| `test_comparison.py` | unit | A/B solver comparison runner, metrics, CSV/Markdown reports, all 6 standard scenarios |
| `test_occupants.py` | unit | Canonical profile schema, overlays, interventions, LPG normalization, household runner metrics |
| `test_onboarding_examples.py` | unit | **Mandatory** — onboarding + full house scenarios solve, constraints met, priority ordering correct. These are the living tests for the [onboarding guide](../../ha-hemm/docs/onboarding.md). |
| `test_sim.py` | slow | Scenario loading, simulation runner, synthetic price/weather generators, all 6 scenarios solve |
| `test_markers.py` | unit | Marker demonstration |
| `test_version.py` | unit | Version specifier with Hypothesis |

333 unit tests pass. 7 slow tests are deselected by default.

---

## A/B Solver Comparison

The comparison test (`test_comparison.py`) is architecturally important. It runs both solver backends (central MILP and distributed) against all 6 standard scenarios and compares:

- **Cost gap**: distributed vs. central MILP (oracle)
- **Comfort violations**: temperature band breaches
- **Plan stability**: slot-to-slot plan changes
- **Solve time**: per-tick performance

The Phase 6 decision gate uses these metrics with hard thresholds:
- Cost gap < 3% over 7-day simulation
- Comfort violations ≤ Backend A
- Plan stability ≤ 1.5× Backend A
- p95 solve time < 5s

Reports are generated in CSV and Markdown format.

---

## Standard Scenarios

Six scenarios in `testdata/scenarios/` serve as the canonical test set:

| Scenario | Purpose |
|---|---|
| `onboarding.yaml` | PV + battery + EV + thermostat + dynamic tariff — the load-bearing case |
| `battery_arbitrage.yaml` | Pure battery charge/discharge against dynamic pricing |
| `heat_pump_shift.yaml` | Heat pump load shifting with COP-dependent scheduling |
| `ev_departure.yaml` | EV charging to target SoC by departure deadline |
| `water_heater_legionella.yaml` | Hot water with legionella constraint (reach 60°C once per window) |
| `full_house.yaml` | All device types active simultaneously |
| `family4_winter_setback.yaml` | Occupant demand with deterministic profile, setback, shifted load, and EV timing |

---

## CI/CD

The CI workflow (`.github/workflows/ci.yml`) runs on every push to `main` and every PR:

1. **Core gate**: `make ci` on Python 3.12 and 3.13
2. **Simulation smoke**: `make test-slow` on Python 3.12
3. **Occupants smoke**: `hemm sim run ... --ab-interventions` and `hemm sim sweep ...`

The core gate includes lint, format check, strict mypy, clock audit, and unit tests.

---

## Quick Reference

```bash
uv run pytest                    # Unit tests (~9s)
uv run pytest -m slow            # Slow sim tests only
make ci                          # lint + typecheck + test
make lint                        # ruff check + format check
make typecheck                   # mypy --strict
make format                      # auto-format
```
