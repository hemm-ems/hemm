"""Backend-A golden plan-parity helper (feature 003).

This module is the single canonical Backend-A oracle used by both the golden
capture (T001 / `tools/capture_golden_003.py`) and the parity test
(`test_solver_parity.py`, T015). It deliberately pins a ``FixedClock`` so the
solve is reproducible regardless of the wall-clock date CI runs on, and so the
scenario constraint windows (deadlines on 2026-05-07) are always active.

Not a test module itself (leading underscore → not collected by pytest).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hemm_core.constraints import ConstraintWindowManager
from hemm_core.manifest.validator import validate_manifest
from hemm_core.sim.scenario import Scenario, load_scenario, resolve_constraint_window
from hemm_core.sim.synthetic import generate_price_series
from hemm_core.solvers.milp_central import MILPCentralSolver
from hemm_core.solvers.protocol import SolverResult
from hemm_core.time import FixedClock

# Canonical instant: 2026-05-07T00:00Z — the pinned t0 the oracle solves at.
# Scenario deadlines are relative (`deadline_offset_hours`, FR-011) and resolve
# against this instant to the same absolute deadlines the goldens were captured
# with (offsets equal the time-of-day of the historic 2026-05-07 deadlines), so
# every constraint still falls *inside* the 24h planning window and genuinely
# binds (EV delivers its energy, the tank reaches 60°C, the heat pump meets its
# runtime) — a strong parity reference rather than a trivial all-zero plan.
# Pinning also keeps the oracle independent of the wall-clock date the capture
# or parity run happens on.
CANONICAL_NOW = datetime(2026, 5, 7, 0, 0, tzinfo=UTC)

# Tolerances from plan.md / contracts: solver-reformulation float noise only.
OBJECTIVE_REL_TOL = 1e-9
POWER_ABS_TOL = 1e-6  # kW

_TESTDATA = Path(__file__).resolve().parent.parent / "testdata"
SCENARIOS_DIR = _TESTDATA / "scenarios"
GOLDEN_DIR = _TESTDATA / "golden" / "003_backend_a"

# The 7 golden-parity scenarios (FR-006).
SCENARIOS = (
    "battery_arbitrage",
    "control_class_mix",
    "ev_departure",
    "full_house",
    "heat_pump_shift",
    "onboarding",
    "water_heater_legionella",
)

# FR-006 / research D8 — the closed, justified set of future deliberate Backend-A
# cutovers allowed to diverge from the golden fixtures. The goldens were recaptured
# at HEAD on 2026-06-10 after the storage-efficiency fix, so no current scenario is
# expected to diverge.
DIVERGENCE_ALLOWLIST: frozenset[tuple[str, str]] = frozenset()

# Cost-tied alternate optima: for these (scenario, device) pairs the MILP optimum
# is not unique (equal-price slots make the placement cost-neutral) and HiGHS
# resolves the tie differently per platform (macOS ARM capture vs Linux x86 CI).
# Per-slot parity is skipped; total device energy AND the scenario objective
# still must match the golden. full_house/dhw: slots 4 and 8 are both off-peak,
# tie observed after the grid-settlement import/export split. full_house EV +
# battery: the RW2 EV charge-efficiency change (FR-203) made the night-slot
# allocation degenerate — macOS and Linux HiGHS pick different equal-cost
# vertices (energy swaps between slots 0 and 6); totals still must match.
DEGENERATE_TIE_ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        ("full_house", "dhw"),
        ("full_house", "ev_charger_garage"),
        ("full_house", "house_battery"),
    }
)


def _price_params(scenario: Scenario) -> dict[str, Any]:
    """Mirror SimRunner._price_params — pass through the supported price knobs."""
    params: dict[str, Any] = {}
    for key in ("base_price", "peak_price", "off_peak_price"):
        if key in scenario.price_params:
            params[key] = scenario.price_params[key]
    return params


def solve_scenario(path: str | Path) -> SolverResult:
    """Deterministic single-day Backend-A solve of a scenario file.

    Mirrors ``SimRunner``'s day-0 solve (no weather forecast, outdoor_temp 5.0)
    but pins a ``FixedClock`` for reproducibility. This is the canonical solve
    captured as golden and re-run for parity.
    """
    scenario = load_scenario(path)
    clock = FixedClock(CANONICAL_NOW)

    manifests = [validate_manifest(m) for m in scenario.manifests]

    mgr = ConstraintWindowManager(clock=clock)
    for cw_data in scenario.constraint_windows:
        # Relative deadlines resolve against the pinned CANONICAL_NOW, so the
        # oracle stays deterministic and the migrated scenarios (offset =
        # time-of-day of the old 2026-05-07 deadlines) keep bit-identical goldens.
        mgr.add(resolve_constraint_window(cw_data, CANONICAL_NOW))
    active_windows = mgr.get_active(now=CANONICAL_NOW)

    price_forecast = generate_price_series(
        start=CANONICAL_NOW,
        hours=scenario.horizon_hours,
        resolution_minutes=scenario.resolution_minutes,
        **_price_params(scenario),
    )

    solver = MILPCentralSolver(outdoor_temp_c=5.0, clock=clock)
    return solver.solve(
        manifests=manifests,
        constraint_windows=active_windows,
        price_forecast=price_forecast,
        horizon_minutes=scenario.horizon_hours * 60,
        resolution_minutes=scenario.resolution_minutes,
        previous_plans=None,
    )


def extract_plan(result: SolverResult) -> dict[str, Any]:
    """Reduce a SolverResult to the comparable parity payload."""
    return {
        "status": result.status.value,
        "objective_value": result.objective_value,
        "devices": {
            plan.device_id: [slot.power_kw for slot in plan.slots]
            for plan in sorted(result.plans, key=lambda p: p.device_id)
        },
    }


def load_golden(scenario: str) -> dict[str, Any]:
    """Load a committed golden fixture by scenario name."""
    return json.loads((GOLDEN_DIR / f"{scenario}.json").read_text(encoding="utf-8"))


def compare_to_golden(
    golden: dict[str, Any],
    current: dict[str, Any],
    *,
    rel_tol: float = OBJECTIVE_REL_TOL,
    abs_tol: float = POWER_ABS_TOL,
) -> list[str]:
    """Return human-readable mismatches between golden and current payloads.

    Empty list == parity holds (objective within ``rel_tol``, every per-slot
    power within ``abs_tol``).
    """
    diffs: list[str] = []

    if current["status"] != golden["status"]:
        diffs.append(f"status: golden={golden['status']} current={current['status']}")

    g_obj, c_obj = golden["objective_value"], current["objective_value"]
    if (g_obj is None) != (c_obj is None):
        diffs.append(f"objective presence: golden={g_obj} current={c_obj}")
    elif g_obj is not None and abs(c_obj - g_obj) > rel_tol * max(1.0, abs(g_obj)):
        diffs.append(f"objective: golden={g_obj!r} current={c_obj!r} (Δ={c_obj - g_obj:.3e})")

    g_dev, c_dev = golden["devices"], current["devices"]
    if set(g_dev) != set(c_dev):
        diffs.append(f"device set: golden={sorted(g_dev)} current={sorted(c_dev)}")

    for dev in sorted(set(g_dev) & set(c_dev)):
        gp, cp = g_dev[dev], c_dev[dev]
        if len(gp) != len(cp):
            diffs.append(f"{dev}: slot count golden={len(gp)} current={len(cp)}")
            continue
        for t, (gv, cv) in enumerate(zip(gp, cp, strict=True)):
            if abs(cv - gv) > abs_tol:
                diffs.append(f"{dev}[{t}]: golden={gv!r} current={cv!r} (Δ={cv - gv:.3e})")

    return diffs


def capture_golden() -> list[Path]:
    """Solve every scenario and (over)write its golden fixture. Returns paths.

    WARNING: only run pre-refactor — this defines the parity oracle.
    """
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for scenario in SCENARIOS:
        result = solve_scenario(SCENARIOS_DIR / f"{scenario}.yaml")
        payload = extract_plan(result)
        out = GOLDEN_DIR / f"{scenario}.json"
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(out)
    return written
