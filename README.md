# HEMM — Distributed Energy Optimizer for Home Automation

[![CI](https://github.com/swifty99/hemm/actions/workflows/ci.yml/badge.svg)](https://github.com/swifty99/hemm/actions/workflows/ci.yml)
[![CodeQL](https://github.com/swifty99/hemm/actions/workflows/codeql.yml/badge.svg)](https://github.com/swifty99/hemm/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/swifty99/hemm)](https://github.com/swifty99/hemm/releases/latest)
[![License](https://img.shields.io/github/license/swifty99/hemm)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)

> **Beta.** The manifest schema, constraint vocabulary, and solver interface may still change before 1.0. Contributions and code reviews are welcome.

> **Home Assistant users:** see [ha-hemm](https://github.com/swifty99/ha-hemm) for the HA integration. This repository is the core Python library — no HA dependency, standalone testable.

HEMM optimizes energy consumption across heterogeneous home devices (PV, battery, heat pump, EV charger, hot water) using declarative device manifests and MILP optimization. Each device declares its constraints, cost function, and actions in a JSON manifest; a central solver reads all manifests and produces 24-hour power plans in 15-minute slots.

## Developer Quick Start

```bash
uv venv
uv pip install -e ".[dev]"

make test      # unit tests
make ci        # lint + type check + test

hemm --help
hemm schema    # list manifest types
hemm validate <manifest.json>
hemm sim run <scenario.yaml>
hemm sim compare <scenario_a.yaml> <scenario_b.yaml>
```

## Development Setup

HEMM is developed alongside [ha-hemm](https://github.com/swifty99/ha-hemm), the Home Assistant integration. Both repos live under one parent directory:

```
~/dev/hemm/
├── hemm/       # this repo (core library, PyPI package)
└── ha-hemm/    # HA custom component
```

The integration uses an editable install of the core during development:

```bash
cd ha-hemm
uv pip install -e ../hemm
```

## Architecture

- **Declarative manifests** — devices describe themselves via a versioned JSON schema (constraints, cost functions, efficiency maps, actuator contracts with expected-outcome verification). The solver has no device-specific code.
- **Control classes** — each manifest declares `control_class` (planned / reactive / passive). Planned devices get full 15-min scheduling; reactive devices follow second-by-second setpoints; passive devices are monitored but never actuated.
- **Reason annotation** — every plan slot carries a `reason` field (`pv_surplus`, `cheap_grid`, `constraint`, `idle`, `manual`, `safety_default`) explaining why the solver chose that power level.
- **Two solver backends** — Central MILP (Pyomo + HiGHS, default) and distributed optimization (experimental, price iteration / ADMM). Both read identical manifests.
- **Forecast adapters** — pluggable sources for PV and price forecasts (Solcast, Forecast.Solar, template fallback).
- **Simulation harness** — run scenarios against historical data, compare solver backends, generate Markdown reports.
- **Occupant demand simulation** — deterministic household profiles add baseload, DHW draws, presence, internal gains, and typed interventions for savings A/B runs.
- **No vendor knowledge in core** — device quirks belong in HA automations, not here.

## Occupant Simulation

Occupant demand lives entirely in the core simulation harness. Scenarios may add a `household:` block that points at a baked canonical profile or uses the deterministic synthetic adapter. Interventions are typed diffs against the same profile and seed, so `hemm sim run <scenario> --ab-interventions` reports attributable cost and energy deltas.

```bash
hemm sim bake-profile --archetype family4 --year 2026 --seed 17 \
  --output testdata/profiles/family4-2026-s17.parquet --synthetic-fixture

hemm sim run testdata/scenarios/family4_winter_setback.yaml --ab-interventions
hemm sim sweep testdata/scenarios/family4_winter_setback.yaml
```

LPG is supported as an out-of-process bake source through `HEMM_LPG_ENGINE` or `HEMM_LPG_DOCKER_IMAGE`; LPG binaries are not vendored.

## Testing

The test suite has 260+ tests across three levels:

- **Unit tests** cover manifest schema, constraint vocabulary, solver correctness, and forecast adapters. Run with `make test` in under 60 seconds.
- **Slow tests** (`-m slow`) run multi-day simulations and A/B comparisons between solver backends.
- **Onboarding scenario tests** (`tests/test_onboarding_examples.py`) verify that the canonical worked examples in the [ha-hemm onboarding guide](https://github.com/swifty99/ha-hemm/blob/main/docs/onboarding.md) solve correctly on every commit. If these tests pass, the guide is accurate.

CI runs on Python 3.12 and 3.13 on every push.

## Contributing

Issues, pull requests, and code reviews are welcome. The project is in early-access beta — feedback on the manifest schema and constraint vocabulary is particularly useful because those are the interfaces that future manifest types and the HA integration depend on.

See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow details.

## License

MIT
