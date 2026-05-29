# Feature Specification: Simulation Harness & Scenarios

**Feature Branch**: `005-sim-harness`

**Created**: 2026-05-28

**Status**: Retroactive — Implemented (Phase 2/3, completed 2026-05-06); uncertainty open

**Input**: `concept-hemm.md` (sim harness, falsifiable A/B), code under
`hemm/src/hemm/sim/` (`scenario.py`, `runner.py`, `comparison.py`,
`synthetic.py`), `testdata/scenarios/`, `local-concept-roast.md` weakness #2
(stochastic/uncertainty). Validated against `tests/test_sim.py`,
`tests/test_comparison.py`.

> FRs tagged `✅ done` / `🔶 partial` / `⬜ todo`. The A/B *decision gate* itself
> is owned by [003-distributed-solver](../003-distributed-solver/spec.md); this
> spec owns the harness that produces the numbers.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run a multi-day scenario and get metrics (Priority: P1)

A developer defines a scenario (devices, constraint windows, price/weather
profile, days) in YAML and runs it through the solver, getting cost, energy,
plan-change, violation, and solve-time metrics.

**Why this priority**: Every solver claim ("optimal", "stable plans", "< 5 s")
is only meaningful against a reproducible harness. It is the measurement
instrument for the whole project.

**Independent Test**: Load `testdata/scenarios/onboarding.yaml`, run via
`SimRunner`, assert `success` and populated `SimMetrics`.

**Acceptance Scenarios**:

1. **Given** a valid scenario YAML, **When** run, **Then** a `SimResult` with
   per-day solver results and aggregate metrics is returned.
2. **Given** a scenario with invalid manifests, **When** run, **Then**
   `success=False` with an error message, not a crash.

### User Story 2 - Compare both backends on identical inputs (Priority: P1)

The same scenarios run through Backend A and Backend B; an A/B report computes
cost gap, comfort-violation diff, plan-stability ratio, and speed ratio, and
emits CSV + Markdown with the Phase-6 decision-gate thresholds.

**Independent Test**: Run `ABComparisonRunner.compare_scenarios([...])`; assert
the report exposes `cost_gap_pct`, `plan_stability_ratio`, `speed_ratio` and the
Markdown decision table.

**Acceptance Scenarios**:

1. **Given** N scenarios, **When** compared, **Then** the report's decision
   table evaluates cost gap < 3 %, comfort B ≤ A, stability ≤ 1.5× A.

### Edge Cases

- Scenario references a missing manifest file → `FileNotFoundError` with the path.
- Backend A cost = 0 → cost-gap computation avoids divide-by-zero (documented).
- Solver returns `infeasible` for a day → counted as a constraint violation.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `✅ done` `unit` `SR-005`: System MUST load scenarios from YAML (`Scenario`) with
  inline or file-referenced manifests.
- **FR-002** `✅ done` `unit` `SR-005`: `SimRunner` MUST run a scenario day-by-day, feeding the
  previous plan forward (rolling horizon) and collecting `SimMetrics`.
- **FR-003** `✅ done` `unit` `SR-005`: System MUST ship the standard scenarios in
  `testdata/scenarios/` (onboarding, battery arbitrage, EV departure, heat-pump
  shift, water-heater legionella, full house).
- **FR-004** `✅ done` `unit` `SR-005`: `ABComparisonRunner` MUST run identical scenarios through
  both backends and compute cost gap, comfort diff, stability and speed ratios.
- **FR-005** `✅ done` `unit` `SR-005`: Reports MUST export CSV and Markdown, including the
  Phase-6 decision-gate thresholds (cost gap < 3 %, comfort B ≤ A, stability ≤ 1.5×).
- **FR-006** `✅ done` `unit` `SR-005`: Synthetic price/weather generation MUST be deterministic
  given parameters (`synthetic.py`) for reproducible runs.
- **FR-007** `⬜ todo` `SR-005`: System MUST support **uncertainty evaluation** — run
  plans against scenario fans (e.g. PV forecast intervals, day-ahead price
  realizations) and report robustness, not just a single deterministic forecast.
  *(Source: roast weakness #2; today every run uses one deterministic forecast.)*

### Key Entities

- **Scenario**: declarative test case (devices, windows, profiles, days, tags).
- **SimRunner / SimResult / SimMetrics**: the runner and its outputs.
- **ABComparisonRunner / ComparisonReport / ComparisonMetrics**: A/B measurement.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** `✅`: All standard scenarios run to `success`; `tests/test_sim.py`
  and `tests/test_comparison.py` green (Phase 2/3 suites).
- **SC-002** `✅`: A/B report reproduces identical numbers across runs given a
  fixed `Clock` and parameters.
- **SC-003** `⬜`: A scenario fan produces a robustness metric (e.g. worst-case /
  CVaR cost across the fan), enabling robust-MPC claims (covers FR-007).

## Assumptions

- The harness is the source of truth for performance/quality claims; test counts
  are not (per `AGENT.md` / roast: "did the heat pump short-cycle in week 3").
- Uncertainty (FR-007) feeds robust evaluation here; robust *optimization* in the
  solver is a separate, larger question deferred with FR-007.
