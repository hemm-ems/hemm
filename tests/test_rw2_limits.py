"""RW2 — the plan respects real physical & economic limits (spec 003 Phase 2).

Covers the bug#2 reason fix (peak discharge is expensive_grid, not pv_surplus),
FR-201 (grid/main-fuse cap), FR-203 (EV/DHW round-trip losses), FR-205
(declared physics honored or rejected), and FR-206 (ignored windows surfaced,
impossible deadlines rejected — never clamped).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hemm_core.manifest.constraints import MinSocUntil, ReachMinTempOnce
from hemm_core.manifest.messages import ConstraintWindow, PlanReason
from hemm_core.manifest.types import (
    BatteryManifest,
    EVChargerManifest,
    PassiveLoadManifest,
    PVForecastManifest,
    WaterHeaterManifest,
)
from hemm_core.solvers.consumers import get_consumer_model
from hemm_core.solvers.distributed import DistributedSolver
from hemm_core.solvers.milp_central import MILPCentralSolver
from hemm_core.solvers.protocol import SolverResult, SolverStatus

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


def _passive_load(power_kw: float, device_id: str = "load") -> PassiveLoadManifest:
    return PassiveLoadManifest(
        device_id=device_id,
        name="Base Load",
        typical_daily_kwh=power_kw * 24.0,
        safe_default={"script": "script.noop"},
    )


def _pv(device_id: str = "pv") -> PVForecastManifest:
    return PVForecastManifest(
        device_id=device_id,
        name="PV",
        peak_power_kwp=5.0,
        safe_default={"script": "script.noop"},
    )


def _net_per_slot(result: SolverResult, n_slots: int) -> list[float]:
    """Total house power per slot (positive = import, negative = export)."""
    totals = [0.0] * n_slots
    for plan in result.plans:
        for i, slot in enumerate(plan.slots[:n_slots]):
            totals[i] += slot.power_kw
    return totals


class TestGridCap:
    """FR-201 / SC-RW2a — per-slot grid import/export bounded by the connection limit."""

    @pytest.mark.unit
    def test_uncapped_solver_exceeds_the_fuse(self) -> None:
        """Mutation guard: without a limit the plan does exceed 2 kW import."""
        result = MILPCentralSolver().solve(
            manifests=[_battery()],
            constraint_windows=[],
            price_forecast=_valley_peak_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert max(_net_per_slot(result, 96)) > 2.0

    @pytest.mark.unit
    def test_import_cap_binds(self) -> None:
        solver = MILPCentralSolver(grid_import_limit_kw=2.0)
        result = solver.solve(
            manifests=[_battery()],
            constraint_windows=[],
            price_forecast=_valley_peak_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        net = _net_per_slot(result, 96)
        assert max(net) <= 2.0 + 1e-6
        # The battery still arbitrages within the cap.
        assert any(p > 0.1 for p in net)

    @pytest.mark.unit
    def test_export_cap_curtails_pv(self) -> None:
        solver = MILPCentralSolver(grid_export_limit_kw=2.0)
        result = solver.solve(
            manifests=[_pv()],
            constraint_windows=[],
            price_forecast=_valley_peak_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
            generation_forecast={"pv": [5.0] * 96},
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        net = _net_per_slot(result, 96)
        assert min(net) >= -2.0 - 1e-6

    @pytest.mark.unit
    def test_impossible_cap_is_infeasible_not_exceeded(self) -> None:
        """A fixed 3 kW load with a 2 kW fuse fails loud instead of over-drawing."""
        solver = MILPCentralSolver(grid_import_limit_kw=2.0)
        result = solver.solve(
            manifests=[_passive_load(3.0)],
            constraint_windows=[],
            price_forecast=_valley_peak_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
        )
        assert result.status == SolverStatus.INFEASIBLE
        assert result.plans == []

    @pytest.mark.unit
    def test_nonpositive_limit_rejected(self) -> None:
        with pytest.raises(ValueError, match="grid_import_limit_kw"):
            MILPCentralSolver(grid_import_limit_kw=0.0)
        with pytest.raises(ValueError, match="grid_export_limit_kw"):
            MILPCentralSolver(grid_export_limit_kw=-1.0)

    @pytest.mark.unit
    @settings(max_examples=8, deadline=None)
    @given(
        base_load_kw=st.floats(min_value=0.2, max_value=2.0),
        headroom_kw=st.floats(min_value=0.3, max_value=4.0),
        max_charge_kw=st.floats(min_value=1.0, max_value=11.0),
        export_limit_kw=st.floats(min_value=0.5, max_value=6.0),
    )
    def test_property_no_slot_exceeds_limits(
        self, base_load_kw: float, headroom_kw: float, max_charge_kw: float, export_limit_kw: float
    ) -> None:
        """SC-RW2a: randomized instances never exceed the configured limits."""
        import_limit_kw = base_load_kw + headroom_kw  # always feasible by construction
        battery = BatteryManifest(
            device_id="bat",
            name="Battery",
            capacity_kwh=10.0,
            max_charge_kw=max_charge_kw,
            max_discharge_kw=max_charge_kw,
            safe_default={"script": "script.noop"},
        )
        n_slots = 24
        solver = MILPCentralSolver(
            grid_import_limit_kw=import_limit_kw,
            grid_export_limit_kw=export_limit_kw,
        )
        result = solver.solve(
            manifests=[battery, _passive_load(base_load_kw)],
            constraint_windows=[],
            price_forecast=_valley_peak_prices(n_slots),
            horizon_minutes=n_slots * 15,
            resolution_minutes=15,
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        net = _net_per_slot(result, n_slots)
        assert max(net) <= import_limit_kw + 1e-6
        assert min(net) >= -export_limit_kw - 1e-6


def _ev(capacity_kwh: float = 10.0, charge_efficiency: float | None = None) -> EVChargerManifest:
    kwargs = {} if charge_efficiency is None else {"charge_efficiency": charge_efficiency}
    return EVChargerManifest(
        device_id="ev",
        name="EV",
        max_charge_kw=11.0,
        battery_capacity_kwh=capacity_kwh,
        safe_default={"script": "script.noop"},
        **kwargs,
    )


def _water_heater(heating_efficiency: float) -> WaterHeaterManifest:
    return WaterHeaterManifest(
        device_id="dhw",
        name="Tank",
        volume_liters=100.0,
        max_power_kw=3.0,
        standby_loss_w=0.0,
        heating_efficiency=heating_efficiency,
        safe_default={"script": "script.noop"},
    )


def _total_energy_kwh(result: SolverResult, device_id: str, dt_hours: float = 0.25) -> float:
    plan = next(p for p in result.plans if p.device_id == device_id)
    return sum(max(0.0, s.power_kw) * dt_hours for s in plan.slots)


class TestStorageLosses:
    """FR-203 / SC-RW2b — EV and DHW storage no longer round-trip losslessly."""

    @pytest.mark.unit
    def test_lossless_defaults_are_gone(self) -> None:
        """Mutation guard: default EV/DHW components carry a real loss factor."""
        ev_storage = _ev().to_components()[0]
        assert ev_storage.charge_efficiency < 1.0

        dhw = WaterHeaterManifest(
            device_id="dhw",
            name="Tank",
            volume_liters=100.0,
            max_power_kw=3.0,
            safe_default={"script": "script.noop"},
        )
        components = {type(c).__name__: c for c in dhw.to_components()}
        assert components["StorageSpec"].charge_efficiency < 1.0
        assert components["ConverterSpec"].factor_at(0.0) < 1.0

    @pytest.mark.unit
    def test_ev_charging_draws_more_than_the_deficit(self) -> None:
        """Charging 5 kWh into the EV at 0.9 efficiency draws ≈5.56 kWh from the grid."""
        deadline = _T0 + timedelta(hours=24)
        cw = ConstraintWindow(
            window_id="departure",
            device_id="ev",
            deadline=deadline,
            requirement=MinSocUntil(min_soc_pct=100),
        )
        result = MILPCentralSolver().solve(
            manifests=[_ev()],
            constraint_windows=[cw],
            price_forecast=_valley_peak_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
            initial_state={"ev": {"soc_kwh": 5.0}},
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        drawn = _total_energy_kwh(result, "ev")
        assert drawn >= 5.5  # 5.0 / 0.9 ≈ 5.56, lossless would be 5.0
        assert drawn <= 5.7

    @pytest.mark.unit
    def test_ev_consumer_charge_to_target_is_lossy(self) -> None:
        """Backend B's EV consumer covers the efficiency deficit too."""
        cw = ConstraintWindow(
            window_id="departure",
            device_id="ev",
            deadline=_T0 + timedelta(hours=24),
            requirement=MinSocUntil(min_soc_pct=100),
        )
        consumer = get_consumer_model(_ev(), initial_state={"soc_kwh": 5.0})
        assert consumer is not None
        powers = consumer.respond_to_prices([0.30] * 96, 96, 15, [cw], _T0)
        drawn = sum(p * 0.25 for p in powers)
        assert drawn >= 5.5
        assert drawn <= 5.7

    @pytest.mark.unit
    def test_water_heater_efficiency_costs_energy(self) -> None:
        """Reaching 60 °C with a 0.8-efficient element needs ~25 % more energy than 1.0."""

        def solve_energy(efficiency: float) -> float:
            cw = ConstraintWindow(
                window_id="legionella",
                device_id="dhw",
                deadline=_T0 + timedelta(hours=24),
                requirement=ReachMinTempOnce(target_temp_c=60.0),
            )
            result = MILPCentralSolver().solve(
                manifests=[_water_heater(efficiency)],
                constraint_windows=[cw],
                price_forecast=_valley_peak_prices(),
                horizon_minutes=1440,
                resolution_minutes=15,
            )
            assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
            return _total_energy_kwh(result, "dhw")

        lossless = solve_energy(1.0)
        lossy = solve_energy(0.8)
        assert lossless > 0
        assert lossy > lossless * 1.15  # 1/0.8 = 1.25 nominal, big-M slack tolerance


class TestTerminalNeutrality:
    """FR-204 — the end-of-horizon SoC floor tracks the measured start, not 50 %."""

    @pytest.mark.unit
    def test_low_start_is_not_force_charged_to_half(self) -> None:
        """A battery measured at 20 % on a flat price stays idle (no fictitious 50 % floor)."""
        flat = [(_T0 + timedelta(minutes=15 * i), 0.30) for i in range(96)]
        result = MILPCentralSolver().solve(
            manifests=[_battery()],
            constraint_windows=[],
            price_forecast=flat,
            horizon_minutes=1440,
            resolution_minutes=15,
            initial_state={"bat": {"soc_kwh": 2.0}},
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert all(abs(s.power_kw) < 0.01 for s in result.plans[0].slots)

    @pytest.mark.unit
    def test_arbitrage_ends_at_or_above_measured_start(self) -> None:
        """Peak discharge is recharged: final SoC ≥ the measured 8.1 kWh start."""
        result = MILPCentralSolver().solve(
            manifests=[_battery()],
            constraint_windows=[],
            price_forecast=_valley_peak_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
            initial_state={"bat": {"soc_kwh": 8.1}},
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        soc = 8.1
        for s in result.plans[0].slots:
            if s.power_kw >= 0:
                soc += s.power_kw * 0.25 * 0.95
            else:
                soc += s.power_kw * 0.25 / 0.95
        assert soc >= 8.1 - 1e-6

    @pytest.mark.unit
    def test_backend_b_terminal_floor_tracks_start(self) -> None:
        consumer = get_consumer_model(_battery(), initial_state={"soc_kwh": 8.1})
        assert consumer is not None
        prices = [p for _, p in _valley_peak_prices()]
        powers = consumer.respond_to_prices(prices, 96, 15, [], _T0)
        level = 8.1
        for p in powers:
            level += p * 0.25 * 0.95 if p >= 0 else p * 0.25 / 0.95
        # The DP plans on a ~0.1 kWh level grid, so a continuous replay drifts a
        # few grid steps over 96 slots. 0.5 kWh of slack still cleanly separates
        # the anchored floor (ends ≈ 8.1) from the old 50 % bug (would end ≈ 5.0).
        assert level >= 8.1 - 0.5
