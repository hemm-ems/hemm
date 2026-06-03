# Contract: Per-Primitive Solver Builders, Bus Balance & Parity Gate

How both backends consume the component model. The load-bearing contract is **behavior
preservation** (Constitution II + IV).

## Backend A — per-primitive builders (replaces the isinstance ladders)

`MILPCentralSolver.solve()` builds the Pyomo model by iterating each device's components and
dispatching on `component.primitive` (never on the Python manifest type). One builder per
primitive:

| Primitive | Builder adds | Replaces (today) |
|-----------|-------------|------------------|
| `sink` | `power[d,t]` bounds `min..max`; `on` link | `_get_power_bounds` ladder (lines 375–393) |
| `source` | `power[d,t]` bounds `0..forecast` (PV pinned `(0,0)`) | PV branch of `_get_power_bounds` |
| `storage` | `level[d,t]` recursion + η + min/max bounds | battery SoC block (lines 174–197) |
| `converter` | `q_out = factor_at(ctx)·power[d,t]` injected into `output_bus` node | HP COP special-case (lines 246–251) |
| `node` | thermal state recursion (RC) + optional comfort band | room RC block (lines 199–257) |

### Bus balance (research D1 — parity-critical)

- **Electrical bus**: an **open** node with a free, tariff-priced grid-exchange term. No hard
  `Σpower = 0`. The objective remains `Σ_{d,t} price[t]·power[d,t]·dt` (+ plan-change penalty +
  comfort penalty), algebraically identical to today's `obj_rule` (line 289). **No constraint
  may shrink the feasible set vs. today.**
- **Thermal nodes**: a real balance via the RC recursion (converters inject `q_out`); no free
  slack — identical to the current room/tank dynamics.

## Backend B — component-driven local optimization (FR-009)

`get_consumer_model()`'s isinstance factory (consumers.py lines 651–677) is replaced by
component-driven response: each device's local price response is derived from its
component(s) (storage → arbitrage/charge-to-deadline; converter → factor-weighted price;
sink → cheapest-slots; source → forecast injection). Migration stays behind the existing
`ABComparisonRunner`.

## Gates

### Golden plan-parity (FR-005, FR-006) — Backend A oracle

```text
for scenario in testdata/scenarios/*.yaml:
    golden = solve_with_pre_refactor_A(scenario)      # captured baseline
    current = solve_with_component_A(scenario)
    assert abs(current.objective - golden.objective) <= 1e-9 * max(1, |golden.objective|)
    for d, t:
        assert abs(current.power[d,t] - golden.power[d,t]) <= 1e-6   # kW
```

- Baseline is captured **before** the cutover (committed golden fixtures, or a tagged
  pre-refactor solve). Tolerance covers solver-reformulation float noise only — intent is
  identical plans, not "close enough".
- Applies to all 7 scenarios incl. `water_heater_legionella` (DHW decomposition must
  reproduce the tank trajectory, research D3) and `heat_pump_shift` (COP via `factor_at`).

### A/B harness (FR-009) — Backend B

```text
report = ABComparisonRunner(A=component_A, B=component_B).compare_scenarios(all)
assert report.avg_cost_gap_pct < 3.0
assert per-scenario comfort_violations(B) <= comfort_violations(A)
assert max plan_stability_ratio <= 1.5
```

### Thesis smoke (FR-012) — integration tier

```text
add testdata manifest pool_pump  ->  SinkSpec(elec, controllable=True)
solve a scenario containing it
assert pool_pump gets a valid PlanMessage within bounds
assert a forbidden_window on pool_pump zeroes its `on` across the window
assert: git diff --stat shows 0 changed lines in
        src/hemm_core/solvers/milp_central.py AND solvers/consumers.py
```

## Acceptance summary

| FR | Test | Gate |
|----|------|------|
| FR-005 | `test_solver_parity.py` | A builds from components; no isinstance-on-type remains |
| FR-006 | `test_solver_parity.py` | objective + per-slot power within tolerance, 7 scenarios |
| FR-007 | `test_components.py::test_factor_at` | COP via generic `factor_at`, clamped |
| FR-008 | `test_constraints_generic.py` | constraints target storage level / node state / flow |
| FR-009 | `test_comparison.py` | `cost_gap < 3%`, comfort + stability gates |
| FR-012 | integration | pool_pump plans; solver diff == 0 lines |
