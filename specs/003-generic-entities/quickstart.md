# Quickstart: Adding a device type with no solver code

This is the payoff of feature 003 — the falsifiable thesis (FR-012). After the refactor,
teaching HEMM a new device means writing a **manifest that composes existing primitives**,
not editing any solver.

## Example: a pool pump (controllable electrical load)

1. **Declare the manifest** (config/UX layer — `types.py` named type or a generic manifest):
   a pool pump is a controllable load with power bounds and optional runtime/forbidden-window
   constraints. It carries the mandatory `safe_default` like any device.

2. **Map it to a primitive** via `to_components()`:

   ```python
   def to_components(self) -> list[ComponentSpec]:
       return [SinkSpec(
           device_id=self.device_id,
           bus="elec",
           min_power_kw=0.0,
           max_power_kw=self.max_power_kw,
           controllable=True,
       )]
   ```

3. **Solve.** Both backends already know how to build a `sink`. The pool pump is planned —
   honoring `forbidden_window` / `min_runtime_per_day` through the generalized constraint
   path — with **zero** lines changed in `solvers/milp_central.py` or `solvers/consumers.py`.

## Verify it end-to-end

```bash
cd hemm

# 1. component model round-trips + mapping is declarative
uv run pytest tests/test_components.py -q

# 2. Backend A still matches the pre-refactor golden plans (the oracle is intact)
uv run pytest tests/test_solver_parity.py -q

# 3. constraints generalize onto primitive state vars (hold_temp_band on DHW, min_soc on EV)
uv run pytest tests/test_constraints_generic.py -q

# 4. Backend B stays within the A/B gate
uv run pytest tests/test_comparison.py -q

# 5. THE THESIS: pool_pump plans, and the two solver files are untouched
uv run pytest tests/ -k pool_pump
git diff --stat HEAD -- src/hemm_core/solvers/milp_central.py src/hemm_core/solvers/consumers.py
#   -> expect: no changes to either file

# 6. traceability gate (run from repo root; needs ../ha-hemm checked out)
make gate
```

## What you must NOT do

- Don't add an `isinstance(manifest, PoolPump)` branch anywhere in the solvers — that
  *re-falsifies the thesis* (FR-003 / SC-006).
- Don't put vendor/quirk logic in the core — that stays in HA plug points (Constitution V).
- Don't add a required manifest field that older manifests lack (Constitution II).

## Success looks like

- `pool_pump` produces a valid `PlanMessage` within its bounds and respects its constraints.
- `git diff --stat` shows **0 changed lines** in both solver files (SC-001, SC-006).
- All 7 golden scenarios still match Backend A bit-for-bit within tolerance (SC-002).
