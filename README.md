# HEMM — Distributed Energy Optimizer for Home Automation

HEMM optimizes energy consumption across heterogeneous devices in a home (PV, battery, heat pump, EV charger, hot water) using declarative device manifests and mathematical optimization.

## Quick Start

```bash
# Install in development mode
uv venv
uv pip install -e ".[dev]"

# Run tests
make test

# Run full CI checks
make ci

# CLI
hemm --help
```

## Development Setup

HEMM is developed alongside its Home Assistant integration (`ha-hemm`). Both repos live under one parent directory:

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

- **Declarative manifests** — devices describe themselves (constraints, cost functions, actions)
- **Two solver backends** — Central MILP (default) and Distributed optimization (experimental)
- **Forecast adapters** — pluggable sources for PV, price, weather
- **Verification contracts** — every actuator action has expected outcomes
- **No vendor knowledge in core** — plug points instead of hardcoding

## License

MIT
