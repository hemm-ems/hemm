"""RW2 — the plan respects real physical & economic limits (spec 003 Phase 2).

Covers the bug#2 reason fix (peak discharge is expensive_grid, not pv_surplus),
FR-201 (grid/main-fuse cap), FR-203 (EV/DHW round-trip losses), FR-205
(declared physics honored or rejected), and FR-206 (ignored windows surfaced,
impossible deadlines rejected — never clamped).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hemm_core.manifest.messages import PlanReason
from hemm_core.manifest.types import BatteryManifest
from hemm_core.solvers.distributed import DistributedSolver
from hemm_core.solvers.milp_central import MILPCentralSolver
from hemm_core.solvers.protocol import SolverStatus

_T0 = datetime(2026, 5, 6, 0, 0, tzinfo=UTC)


def _valley_peak_prices(n: int = 96) -> list[tuple[datetime, float]]:
    """Cheap night (0.15), expensive day (0.45) — classic arbitrage shape."""
    prices = []
    for i in range(n):
        hour = (i * 15) / 60
        price = 0.15 if hour < 6 or hour >= 22 else 0.45
        prices.append((_T0 + timedelta(minutes=15 * i), price))
    return prices


def _battery(device_id: str = "bat") -> BatteryManifest:
    return BatteryManifest(
        device_id=device_id,
        name="Battery",
        capacity_kwh=10.0,
        max_charge_kw=5.0,
        max_discharge_kw=5.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        min_soc_pct=10,
        max_soc_pct=90,
        safe_default={
            "script": "script.bat_safe",
            "verify": {"entity": "sensor.bat", "expected": "== 0", "within_seconds": 30},
        },
    )


class TestExpensiveGridReason:
    """Bug #2 — battery discharge at peak prices was mislabeled pv_surplus."""

    @pytest.mark.unit
    def test_peak_discharge_is_expensive_grid_not_pv_surplus(self) -> None:
        """A battery-only arbitrage plan labels peak discharge expensive_grid.

        Repro of the gs shadow-plan bug: the 19:45–21:15 −4 kW discharge slots
        carried reason "pv_surplus" although there is no PV in the model at all.
        """
        solver = MILPCentralSolver()
        result = solver.solve(
            manifests=[_battery()],
            constraint_windows=[],
            price_forecast=_valley_peak_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        plan = result.plans[0]
        discharging = [s for s in plan.slots if s.power_kw < -0.1]
        assert discharging, "arbitrage scenario must discharge at the peak"
        assert all(s.reason == PlanReason.EXPENSIVE_GRID for s in discharging)
        # A battery-only model can never justify a pv_surplus label.
        assert not any(s.reason == PlanReason.PV_SURPLUS for s in plan.slots)

    @pytest.mark.unit
    def test_discharge_below_peak_keeps_pv_surplus_fallback(self) -> None:
        """Low/mid-price production keeps the pv_surplus fallback (both backends)."""
        prices = [0.20, 0.60]
        cheap, expensive = 0.20, 0.60
        milp_low = MILPCentralSolver._determine_reason("d", 0, -2.0, 1.0, set(), prices, cheap, expensive)
        milp_peak = MILPCentralSolver._determine_reason("d", 1, -2.0, 1.0, set(), prices, cheap, expensive)
        assert milp_low == PlanReason.PV_SURPLUS
        assert milp_peak == PlanReason.EXPENSIVE_GRID

        dist_low = DistributedSolver._determine_reason("d", 0, -2.0, set(), prices, cheap, expensive)
        dist_peak = DistributedSolver._determine_reason("d", 1, -2.0, set(), prices, cheap, expensive)
        assert dist_low == PlanReason.PV_SURPLUS
        assert dist_peak == PlanReason.EXPENSIVE_GRID
