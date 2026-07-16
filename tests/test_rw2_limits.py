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


def _flat_prices(n: int = 96, value: float = 0.30) -> list[tuple[datetime, float]]:
    return [(_T0 + timedelta(minutes=15 * i), value) for i in range(n)]


def _soc_window(deadline: datetime, device_id: str = "bat", pct: float = 80.0) -> ConstraintWindow:
    return ConstraintWindow(
        window_id="w1",
        device_id=device_id,
        deadline=deadline,
        requirement=MinSocUntil(min_soc_pct=pct),
    )


class TestDeclaredPhysicsHonoredOrRejected:
    """FR-205 / SC-RW2c — every accepted manifest field binds or fails loud."""

    @pytest.mark.unit
    def test_defrost_lockout_rejected(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        from hemm_core.manifest.types import HeatPumpManifest

        with pytest.raises(PydanticValidationError, match="defrost_lockout_minutes"):
            HeatPumpManifest(
                device_id="hp",
                name="HP",
                max_power_kw=5.0,
                defrost_lockout_minutes=30,
                safe_default={"script": "script.noop"},
            )

    @pytest.mark.unit
    def test_ev_phase_inconsistency_rejected(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError, match="phase"):
            EVChargerManifest(
                device_id="ev",
                name="EV",
                max_charge_kw=11.0,
                phases=1,  # 11 kW on one phase is 48 A — not a real wallbox
                safe_default={"script": "script.noop"},
            )
        # The plausible 3-phase variant constructs fine.
        EVChargerManifest(
            device_id="ev",
            name="EV",
            max_charge_kw=11.0,
            phases=3,
            safe_default={"script": "script.noop"},
        )

    @pytest.mark.unit
    def test_hp_min_modulation_binds_in_the_plan(self) -> None:
        """Active heat-pump slots never run below the modulation floor."""
        from hemm_core.manifest.constraints import HoldTempBand
        from hemm_core.manifest.types import HeatPumpManifest, RoomManifest

        room = RoomManifest(
            device_id="room",
            name="Room",
            floor_area_m2=25.0,
            thermal_mass_kwh_per_k=2.0,
            u_value_w_per_m2k=0.5,
            safe_default={"script": "script.noop"},
        )
        hp = HeatPumpManifest(
            device_id="hp",
            name="HP",
            max_power_kw=5.0,
            room_id="room",
            min_modulation_pct=30,
            safe_default={"script": "script.noop"},
        )
        cw = ConstraintWindow(
            window_id="comfort",
            device_id="room",
            deadline=_T0 + timedelta(hours=24),
            requirement=HoldTempBand(min_temp_c=20.0, max_temp_c=23.0),
            priority_penalty=3.0,
        )
        cold = [(_T0 + timedelta(minutes=15 * i), -5.0) for i in range(96)]
        result = MILPCentralSolver().solve(
            manifests=[room, hp],
            constraint_windows=[cw],
            price_forecast=_flat_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
            weather_forecast=cold,
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        hp_plan = next(p for p in result.plans if p.device_id == "hp")
        active = [s.power_kw for s in hp_plan.slots if s.power_kw > 0.01]
        assert active, "cold day + comfort band must heat"
        assert all(p >= 1.5 - 1e-6 for p in active)  # 30 % of 5 kW

    @pytest.mark.unit
    def test_converter_consumer_respects_modulation_floor(self) -> None:
        """Backend B rounds a partial slot up to the modulation floor."""
        from hemm_core.manifest.constraints import MinEnergyUntil
        from hemm_core.manifest.types import HeatPumpManifest, RoomManifest

        hp = HeatPumpManifest(
            device_id="hp",
            name="HP",
            max_power_kw=5.0,
            room_id="room",
            min_modulation_pct=30,
            cop_map=[(0.0, 1.0)],
            safe_default={"script": "script.noop"},
        )
        _ = RoomManifest(
            device_id="room",
            name="Room",
            floor_area_m2=25.0,
            safe_default={"script": "script.noop"},
        )
        consumer = get_consumer_model(hp)
        assert consumer is not None
        cw = ConstraintWindow(
            window_id="min_energy",
            device_id="hp",
            deadline=_T0 + timedelta(hours=24),
            requirement=MinEnergyUntil(min_energy_kwh=0.2),
        )
        powers = consumer.respond_to_prices([0.30] * 96, 96, 15, [cw], _T0)
        active = [p for p in powers if p > 0.01]
        assert active
        assert all(p >= 1.5 - 1e-6 for p in active)

    @pytest.mark.unit
    def test_ev_min_charge_kw_binds(self) -> None:
        """Charging slots run at ≥ min_charge_kw or not at all (both backends)."""
        ev = EVChargerManifest(
            device_id="ev",
            name="EV",
            max_charge_kw=11.0,
            min_charge_kw=6.0,
            battery_capacity_kwh=10.0,
            safe_default={"script": "script.noop"},
        )
        cw = _soc_window(_T0 + timedelta(hours=24), device_id="ev", pct=60.0)
        result = MILPCentralSolver().solve(
            manifests=[ev],
            constraint_windows=[cw],
            price_forecast=_valley_peak_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
            initial_state={"ev": {"soc_kwh": 5.0}},
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        active = [s.power_kw for s in result.plans[0].slots if s.power_kw > 0.01]
        assert active, "the SoC target requires charging"
        assert all(p >= 6.0 - 1e-6 for p in active)

        consumer = get_consumer_model(ev, initial_state={"soc_kwh": 5.0})
        assert consumer is not None
        powers = consumer.respond_to_prices([0.30] * 96, 96, 15, [cw], _T0)
        active_b = [p for p in powers if p > 0.01]
        assert active_b
        assert all(p >= 6.0 - 1e-6 for p in active_b)

    @pytest.mark.unit
    def test_flex_cost_shifts_delivery_toward_deadline(self) -> None:
        """flex_cost_per_hour_early binds: a priced window charges late, not early."""

        def weighted_mean_slot(powers: list[float]) -> float:
            total = sum(powers)
            assert total > 0
            return sum(t * p for t, p in enumerate(powers)) / total

        # Slightly rising prices: without flex the cheapest slots are the EARLIEST.
        prices = [(_T0 + timedelta(minutes=15 * i), 0.30 + 0.0001 * i) for i in range(96)]
        deadline = _T0 + timedelta(hours=12)

        def solve_mean_slot(flex: float) -> float:
            cw = ConstraintWindow(
                window_id="departure",
                device_id="ev",
                deadline=deadline,
                requirement=MinSocUntil(min_soc_pct=100),
                flex_cost_per_hour_early=flex,
            )
            result = MILPCentralSolver().solve(
                manifests=[_ev()],
                constraint_windows=[cw],
                price_forecast=prices,
                horizon_minutes=1440,
                resolution_minutes=15,
                initial_state={"ev": {"soc_kwh": 5.0}},
            )
            assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
            return weighted_mean_slot([max(0.0, s.power_kw) for s in result.plans[0].slots])

        assert solve_mean_slot(0.0) < 10  # cheapest-first → charges immediately
        assert solve_mean_slot(2.0) > 40  # earliness priced → charges near the 12 h deadline

        # Backend B mirrors the preference through price shading.
        def consumer_mean_slot(flex: float) -> float:
            cw = ConstraintWindow(
                window_id="departure",
                device_id="ev",
                deadline=deadline,
                requirement=MinSocUntil(min_soc_pct=100),
                flex_cost_per_hour_early=flex,
            )
            consumer = get_consumer_model(_ev(), initial_state={"soc_kwh": 5.0})
            assert consumer is not None
            powers = consumer.respond_to_prices([p for _, p in prices], 96, 15, [cw], _T0)
            return weighted_mean_slot(powers)

        assert consumer_mean_slot(0.0) < 10
        assert consumer_mean_slot(2.0) > 40

    @pytest.mark.unit
    def test_ev_without_window_plans_zero_demand(self) -> None:
        """An unconstrained EV defaults to zero demand — no invented charge slots."""
        result = MILPCentralSolver().solve(
            manifests=[_ev()],
            constraint_windows=[],
            price_forecast=_valley_peak_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
            initial_state={"ev": {"soc_kwh": 5.0}},
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert all(abs(s.power_kw) < 0.01 for s in result.plans[0].slots)

        consumer = get_consumer_model(_ev(), initial_state={"soc_kwh": 5.0})
        assert consumer is not None
        powers = consumer.respond_to_prices([p for _, p in _valley_peak_prices()], 96, 15, [], _T0)
        assert all(abs(p) < 0.01 for p in powers)

    @pytest.mark.unit
    def test_forbidden_window_gates_storage_discharge(self) -> None:
        """A forbidden window blocks discharge too, in both backends."""
        from hemm_core.manifest.constraints import ForbiddenWindow

        cw = ConstraintWindow(
            window_id="lockout",
            device_id="bat",
            deadline=_T0 + timedelta(hours=12),
            requirement=ForbiddenWindow(),
        )
        result = MILPCentralSolver().solve(
            manifests=[_battery()],
            constraint_windows=[cw],
            price_forecast=_valley_peak_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        for slot in result.plans[0].slots[:48]:
            assert abs(slot.power_kw) < 0.01

        consumer = get_consumer_model(_battery())
        assert consumer is not None
        powers = consumer.respond_to_prices([p for _, p in _valley_peak_prices()], 96, 15, [cw], _T0)
        assert all(abs(p) < 0.01 for p in powers[:48])


def _room(device_id: str) -> "RoomManifest":
    from hemm_core.manifest.types import RoomManifest

    return RoomManifest(
        device_id=device_id,
        name=device_id,
        floor_area_m2=25.0,
        thermal_mass_kwh_per_k=2.0,
        u_value_w_per_m2k=0.5,
        safe_default={"script": "script.noop"},
    )


def _room_hp(device_id: str, room_id: str) -> "HeatPumpManifest":
    from hemm_core.manifest.types import HeatPumpManifest

    return HeatPumpManifest(
        device_id=device_id,
        name=device_id,
        max_power_kw=5.0,
        room_id=room_id,
        safe_default={"script": "script.noop"},
    )


def _hold_band(device_id: str, window_id: str) -> ConstraintWindow:
    from hemm_core.manifest.constraints import HoldTempBand

    return ConstraintWindow(
        window_id=window_id,
        device_id=device_id,
        deadline=_T0 + timedelta(hours=24),
        requirement=HoldTempBand(min_temp_c=20.0, max_temp_c=23.0),
        priority_penalty=3.0,
    )


class TestZoneGainsAndTankDraw:
    """FR-207/FR-208 — per-zone internal gains and hot-water draw on the tank state."""

    def _solve_two_rooms(self, internal_gains: dict[str, list[float]] | None) -> dict[str, float]:
        cold = [(_T0 + timedelta(minutes=15 * i), -5.0) for i in range(96)]
        result = MILPCentralSolver().solve(
            manifests=[_room("room_a"), _room_hp("hp_a", "room_a"), _room("room_b"), _room_hp("hp_b", "room_b")],
            constraint_windows=[_hold_band("room_a", "comfort_a"), _hold_band("room_b", "comfort_b")],
            price_forecast=_flat_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
            weather_forecast=cold,
            internal_gains=internal_gains,
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        return {p.device_id: _total_energy_kwh(result, p.device_id) for p in result.plans}

    @pytest.mark.unit
    def test_gains_offset_heating_in_their_zone_only(self) -> None:
        """0.5 kW of occupant gains in room A cut hp_a's energy; hp_b is untouched."""
        base = self._solve_two_rooms(None)
        gained = self._solve_two_rooms({"room_a": [0.5] * 96})
        assert gained["hp_a"] < base["hp_a"] - 0.5  # gains displace real heating energy
        assert gained["hp_b"] == pytest.approx(base["hp_b"], abs=0.05)  # not duplicated across zones

    @pytest.mark.unit
    def test_tank_draw_forces_reheat(self) -> None:
        """A hot-water draw (negative gains on the tank zone) costs reheat energy."""
        from hemm_core.manifest.constraints import HoldTempBand

        def solve_energy(draw_kw: float) -> float:
            cw = ConstraintWindow(
                window_id="keep_hot",
                device_id="dhw",
                deadline=_T0 + timedelta(hours=24),
                requirement=HoldTempBand(min_temp_c=50.0, max_temp_c=65.0),
                priority_penalty=10.0,
            )
            gains = {"dhw": [-draw_kw] * 96} if draw_kw else None
            result = MILPCentralSolver().solve(
                manifests=[_water_heater(1.0)],
                constraint_windows=[cw],
                price_forecast=_flat_prices(),
                horizon_minutes=1440,
                resolution_minutes=15,
                initial_state={"dhw": {"temp_c": 55.0}},
                internal_gains=gains,
            )
            assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
            return _total_energy_kwh(result, "dhw")

        idle_losses_only = solve_energy(0.0)
        with_draw = solve_energy(0.5)
        # 0.5 kW extracted for 24 h = 12 kWh that heating must replace.
        assert with_draw > idle_losses_only + 10.0

    @pytest.mark.unit
    def test_gains_default_is_behaviour_preserving(self) -> None:
        assert self._solve_two_rooms(None) == self._solve_two_rooms({})


class TestIgnoredWindows:
    """FR-206 — windows the solver cannot apply are surfaced, never clamped."""

    @pytest.mark.unit
    def test_past_deadline_is_rejected_and_surfaced(self, caplog: pytest.LogCaptureFixture) -> None:
        """A deadline before the horizon start used to clamp to slot 0 — now it is ignored."""
        import logging

        with caplog.at_level(logging.WARNING, logger="hemm_core.solvers.windows"):
            result = MILPCentralSolver().solve(
                manifests=[_battery()],
                constraint_windows=[_soc_window(_T0 - timedelta(hours=2))],
                price_forecast=_flat_prices(),
                horizon_minutes=1440,
                resolution_minutes=15,
                initial_state={"bat": {"soc_kwh": 2.0}},
            )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        ignored = result.diagnostics["ignored_windows"]
        assert ignored == [
            {
                "window_id": "w1",
                "device_id": "bat",
                "requirement": "min_soc_until",
                "reason": "deadline_in_past",
            }
        ]
        # Not applied: flat price + low start → the plan stays idle.
        assert all(abs(s.power_kw) < 0.01 for s in result.plans[0].slots)
        assert not any(s.reason == PlanReason.CONSTRAINT for s in result.plans[0].slots)
        assert "Ignoring constraint window 'w1'" in caplog.text

    @pytest.mark.unit
    def test_demand_deadline_beyond_horizon_is_not_pulled_forward(self) -> None:
        """A 30 h SoC deadline on a 24 h horizon used to be forced by end-of-horizon."""
        result = MILPCentralSolver().solve(
            manifests=[_battery()],
            constraint_windows=[_soc_window(_T0 + timedelta(hours=30))],
            price_forecast=_flat_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
            initial_state={"bat": {"soc_kwh": 2.0}},
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert [w["reason"] for w in result.diagnostics["ignored_windows"]] == ["deadline_beyond_horizon"]
        assert all(abs(s.power_kw) < 0.01 for s in result.plans[0].slots)

    @pytest.mark.unit
    def test_restrictive_window_beyond_horizon_still_applies(self) -> None:
        """A forbidden window spanning past the horizon truncates safely — not ignored."""
        from hemm_core.manifest.constraints import ForbiddenWindow

        cw = ConstraintWindow(
            window_id="lockout",
            device_id="bat",
            deadline=_T0 + timedelta(hours=48),
            requirement=ForbiddenWindow(),
        )
        result = MILPCentralSolver().solve(
            manifests=[_battery()],
            constraint_windows=[cw],
            price_forecast=_valley_peak_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert result.diagnostics["ignored_windows"] == []
        assert all(abs(s.power_kw) < 0.01 for s in result.plans[0].slots)

    @pytest.mark.unit
    def test_in_horizon_window_reports_nothing_ignored(self) -> None:
        result = MILPCentralSolver().solve(
            manifests=[_battery()],
            constraint_windows=[_soc_window(_T0 + timedelta(hours=12))],
            price_forecast=_flat_prices(),
            horizon_minutes=1440,
            resolution_minutes=15,
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert result.diagnostics["ignored_windows"] == []
