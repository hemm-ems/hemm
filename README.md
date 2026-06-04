# HEMM — Distributed Energy Optimizer for Home Automation

[![CI](https://github.com/hemm-ems/hemm/actions/workflows/ci.yml/badge.svg)](https://github.com/hemm-ems/hemm/actions/workflows/ci.yml)
[![CodeQL](https://github.com/hemm-ems/hemm/actions/workflows/codeql.yml/badge.svg)](https://github.com/hemm-ems/hemm/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/hemm-ems/hemm)](https://github.com/hemm-ems/hemm/releases/latest)
[![License](https://img.shields.io/github/license/hemm-ems/hemm)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)

> **Beta.** The manifest schema is stable (existing manifests validate unchanged); the constraint vocabulary may still gain types and the solver interface may refine before 1.0. Contributions and code reviews are welcome.

> **Home Assistant users:** see [ha-hemm](https://github.com/hemm-ems/ha-hemm) for the HA integration. This repository is the core Python library — no HA dependency, standalone testable.

HEMM optimizes energy consumption across heterogeneous home devices (PV, battery, heat pump, EV charger, hot water) using declarative device manifests and MILP optimization. Each device declares its constraints, cost function, and actions in a JSON manifest; the solver compiles every manifest down to a handful of physics primitives and produces 24-hour power plans in 15-minute slots. Adding a new device type is a manifest, not a code change.

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

HEMM is developed alongside [ha-hemm](https://github.com/hemm-ems/ha-hemm), the Home Assistant integration. Both repos live under one parent directory:

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

- **Declarative manifests** — devices describe themselves via a versioned JSON schema (constraints, cost functions, efficiency maps, actuator contracts with expected-outcome verification).
- **Primitive component model** — every manifest compiles (`to_components()`) to a small, fixed set of physics primitives: **source, sink, storage, converter, node**. The solvers build from these primitives, never from device types, so teaching HEMM a new device means writing a manifest that composes existing primitives — not editing a solver. A `pool_pump`, for example, plans correctly with zero lines changed in either solver file.
- **Control classes** — each manifest declares `control_class` (planned / reactive / passive). Planned devices get full 15-min scheduling; reactive devices follow second-by-second setpoints; passive devices are monitored but never actuated.
- **Reason annotation** — every plan slot carries a `reason` field (`pv_surplus`, `cheap_grid`, `constraint`, `idle`, `manual`, `safety_default`) explaining why the solver chose that power level.
- **Two backends, one contract** — a central MILP (Pyomo + HiGHS; the default, provably optimal) and a distributed price-iteration backend. Both read the same manifests and build from the same primitives, so device knowledge lives in the manifest layer rather than in either solver — the second backend adds little to maintain. On the standard scenarios the distributed backend now tracks the optimal plan within ~1.2% average cost and converges on all of them; the MILP stays the default because it is exact. See [solver-decision](https://github.com/hemm-ems/ha-hemm/blob/main/docs/solver-decision.md) for the A/B gate.
- **Forecast adapters** — pluggable sources for PV and price forecasts (Solcast, Forecast.Solar, template fallback).
- **Simulation harness** — run scenarios against historical data, compare solver backends, generate Markdown reports.
- **No vendor knowledge in core** — device quirks belong in HA automations, not here.

## Testing

The test suite has 350+ tests across three levels:

- **Unit tests** cover manifest schema, constraint vocabulary, solver correctness, and forecast adapters. Run with `make test` in under 60 seconds.
- **Slow tests** (`-m slow`) run multi-day simulations and A/B comparisons between solver backends.
- **Onboarding scenario tests** (`tests/test_onboarding_examples.py`) verify that the canonical worked examples in the [ha-hemm onboarding guide](https://github.com/hemm-ems/ha-hemm/blob/main/docs/onboarding.md) solve correctly on every commit. If these tests pass, the guide is accurate.

CI runs on Python 3.12 and 3.13 on every push.

## Contributing

Issues, pull requests, and code reviews are welcome. The project is in early-access beta — feedback on the manifest schema and constraint vocabulary is particularly useful because those are the interfaces that future manifest types and the HA integration depend on.

See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow details.

## License

MIT
