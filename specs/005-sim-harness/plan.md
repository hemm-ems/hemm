# Implementation Plan: Simulation Harness & Scenarios

**Branch**: `005-sim-harness` (in `hemm`) | **Date**: 2026-05-28 |
**Spec**: [spec.md](./spec.md)

**Note**: Retroactive. Harness + A/B reporting built; uncertainty (FR-007) open.

## Summary

YAML scenarios → day-by-day rolling-horizon runner → metrics; an A/B runner
compares both backends and emits CSV/Markdown with decision-gate thresholds.
Deterministic synthetic price/weather makes runs reproducible. Open: scenario
fans for uncertainty/robustness evaluation.

## Technical Context

**Language/Version**: Python 3.12 / 3.13
**Primary Dependencies**: PyYAML, core solver + constraint manager; no HA imports
**Testing**: `tests/test_sim.py`, `tests/test_comparison.py`; tier includes `slow`
**Project Type**: Pure-Python library
**Constraints**: deterministic given `Clock` + params (Constitution VII)

## Constitution Check

- **III. Done = Green Tests** — PASS for ✅ FRs; this *is* the measurement tier.
- **IV. Two Backends** — PASS. Runs both backends on identical inputs, unbiased.
- **VII. Time discipline** — PASS. `Clock`-injected; synthetic series deterministic.

## Project Structure

```text
hemm/src/hemm/sim/
├── scenario.py     # Scenario + load_scenario (YAML, manifest refs)
├── runner.py       # SimRunner, SimResult, SimMetrics
├── comparison.py   # ABComparisonRunner, ComparisonReport (CSV/Markdown)
└── synthetic.py    # deterministic price/weather generation
hemm/testdata/scenarios/*.yaml
hemm/tests/test_sim.py, tests/test_comparison.py
```

**Structure Decision**: As-built. FR-007 adds a fan generator (multiple forecast
realizations per scenario) and a robustness aggregator in `runner.py`/new module.

## Open Work (drives tasks.md)

- **FR-007**: define forecast-fan representation (e.g. quantile bands → sampled
  realizations); run plan against the fan; report worst-case/CVaR cost and
  violation distribution.

## Complexity Tracking

No violations. Keep FR-007 to evaluation first; robust optimization in the solver
is explicitly out of scope here (deferred, see 002 assumptions).
