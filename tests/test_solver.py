"""Tests for the solver protocol and MILP central solver."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hemm_core.manifest.components import ComponentSpec, SourceSpec
from hemm_core.manifest.constraints import (
    ForbiddenWindow,
    HoldTempBand,
    MinEnergyUntil,
    MinRuntimePerDay,
    MinSocUntil,
    ReachMinTempOnce,
)
from hemm_core.manifest.messages import ConstraintWindow, PlanReason
from hemm_core.manifest.types import (
    BatteryManifest,
    EVChargerManifest,
    HeatPumpManifest,
    PVForecastManifest,
    RoomManifest,
    ThermostatLoadManifest,
)
from hemm_core.solvers.milp_central import DEFAULT_COP_MAP, MILPCentralSolver, _piecewise_cop
from hemm_core.solvers.protocol import SolverResult, SolverStatus

# --- Fixtures ---


def _make_battery() -> BatteryManifest:
    return BatteryManifest(
        device_id="test_battery",
        name="Test Battery",
        capacity_kwh=10.0,
        max_charge_kw=5.0,
        max_discharge_kw=5.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        min_soc_pct=10,
        max_soc_pct=90,
        safe_default={
            "script": "script.battery_safe",
            "verify": {"entity": "sensor.bat", "expected": "== 0", "within_seconds": 30},
        },
    )


def _make_ev_charger() -> EVChargerManifest:
    return EVChargerManifest(
        device_id="test_ev",
        name="Test EV Charger",
        max_charge_kw=11.0,
        min_charge_kw=1.4,
        phases=3,
        safe_default={
            "script": "script.ev_safe",
            "verify": {"entity": "sensor.ev", "expected": "== 0", "within_seconds": 30},
        },
    )


def _make_heat_pump() -> HeatPumpManifest:
    return HeatPumpManifest(
        device_id="test_hp",
        name="Test Heat Pump",
        max_power_kw=5.0,
        cop_map=[(-10, 2.5), (0, 3.5), (10, 4.5)],
        safe_default={
            "script": "script.hp_safe",
            "verify": {"entity": "sensor.hp", "expected": "== idle", "within_seconds": 30},
        },
    )


def _make_thermostat() -> ThermostatLoadManifest:
    return ThermostatLoadManifest(
        device_id="test_thermo",
        name="Test Thermostat",
        max_power_kw=2.0,
        safe_default={
            "script": "script.thermo_safe",
            "verify": {"entity": "sensor.thermo", "expected": "== off", "within_seconds": 30},
        },
    )


def _make_price_forecast(n_slots: int = 96, base: float = 0.30) -> list[tuple[datetime, float]]:
    """Create a simple price forecast."""
    t0 = datetime(2026, 5, 6, 0, 0, tzinfo=UTC)
    return [(t0 + timedelta(minutes=15 * i), base) for i in range(n_slots)]


# --- Tests ---


@pytest.mark.req("002:FR-001")
class TestSolverProtocol:
    """Tests for the solver protocol compliance."""

    @pytest.mark.unit
    def test_milp_central_has_name(self) -> None:
        solver = MILPCentralSolver()
        assert solver.name == "milp_central"

    @pytest.mark.unit
    def test_solver_result_creation(self) -> None:
        result = SolverResult(status=SolverStatus.OPTIMAL)
        assert result.status == SolverStatus.OPTIMAL
        assert result.plans == []
        assert result.solve_time_seconds == 0.0


@pytest.mark.req("002:FR-008")
class TestPiecewiseCOP:
    """Tests for piecewise-linear COP interpolation."""

    @pytest.mark.unit
    def test_cop_at_known_point(self) -> None:
        cop = _piecewise_cop(DEFAULT_COP_MAP, 0.0)
        assert cop == 3.5

    @pytest.mark.unit
    def test_cop_interpolation(self) -> None:
        cop = _piecewise_cop(DEFAULT_COP_MAP, 2.5)
        # Between (0, 3.5) and (5, 4.0) -> should be 3.75
        assert abs(cop - 3.75) < 0.01

    @pytest.mark.unit
    def test_cop_below_min(self) -> None:
        cop = _piecewise_cop(DEFAULT_COP_MAP, -20.0)
        assert cop == 2.0  # clamps to first value

    @pytest.mark.unit
    def test_cop_above_max(self) -> None:
        cop = _piecewise_cop(DEFAULT_COP_MAP, 25.0)
        assert cop == 5.0  # clamps to last value

    @pytest.mark.unit
    def test_cop_empty_map(self) -> None:
        cop = _piecewise_cop([], 5.0)
        assert cop == 3.5  # default

    @pytest.mark.unit
    def test_cop_approximation_error_within_5pct(self) -> None:
        """COP interpolation has < 5% approximation error vs linear."""
        # Test several intermediate points
        cop_map = [(-10.0, 2.5), (0.0, 3.5), (10.0, 4.5)]
        for temp in range(-10, 11):
            cop = _piecewise_cop(cop_map, float(temp))
            # Perfect linear: COP = 3.5 + temp * 0.1
            expected = 3.5 + temp * 0.1
            error_pct = abs(cop - expected) / expected * 100
            assert error_pct < 5.0, f"COP error {error_pct}% at {temp}°C"


@pytest.mark.req("002:FR-002", "002:FR-003", "002:FR-004", "002:FR-005", "002:FR-006", "002:FR-007")
class TestMILPCentralSolver:
    """Tests for the MILP central solver."""

    @pytest.mark.unit
    def test_solve_single_battery(self) -> None:
        """Solver produces a plan for a single battery."""
        solver = MILPCentralSolver()
        battery = _make_battery()
        prices = _make_price_forecast(96)

        result = solver.solve(
            manifests=[battery],
            constraint_windows=[],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert len(result.plans) == 1
        assert result.plans[0].device_id == "test_battery"
        assert len(result.plans[0].slots) == 96

    @pytest.mark.unit
    def test_battery_efficiency_applies_to_charge_and_discharge(self) -> None:
        """Battery SoC loses energy on both charge and discharge legs."""
        solver = MILPCentralSolver()
        battery = BatteryManifest(
            device_id="lossy_battery",
            name="Lossy Battery",
            capacity_kwh=2.0,
            max_charge_kw=1.0,
            max_discharge_kw=1.0,
            charge_efficiency=0.9,
            discharge_efficiency=0.9,
            min_soc_pct=0,
            max_soc_pct=100,
            safe_default={
                "script": "script.battery_safe",
                "verify": {"entity": "sensor.bat", "expected": "== 0", "within_seconds": 30},
            },
        )
        t0 = datetime(2026, 5, 6, 0, 0, tzinfo=UTC)
        prices = [(t0, -1.0), (t0 + timedelta(hours=1), 1.0)]

        result = solver.solve(
            manifests=[battery],
            constraint_windows=[],
            price_forecast=prices,
            horizon_minutes=120,
            resolution_minutes=60,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        powers = [slot.power_kw for slot in result.plans[0].slots]
        assert powers[0] == pytest.approx(1.0)
        # Terminal neutrality caps the discharge: SoC may not end below the
        # initial 1.0 kWh, so only the 0.9 kWh charged (after losses) can be
        # sold, draining 0.9 kWh at 0.9 discharge efficiency = 0.81 kW for 1h.
        assert powers[1] == pytest.approx(-0.81)

        soc = [1.0]
        for power in powers:
            if power >= 0.0:
                soc.append(soc[-1] + power * 0.9)
            else:
                soc.append(soc[-1] + power / 0.9)
        assert soc[1] == pytest.approx(1.9)
        assert soc[2] == pytest.approx(1.0)

    @pytest.mark.unit
    def test_battery_does_not_charge_and_discharge_simultaneously(self) -> None:
        """Negative prices cannot be exploited by wasting energy at full SoC."""
        solver = MILPCentralSolver()
        battery = BatteryManifest(
            device_id="full_battery",
            name="Full Battery",
            capacity_kwh=2.0,
            max_charge_kw=1.0,
            max_discharge_kw=1.0,
            charge_efficiency=0.9,
            discharge_efficiency=0.9,
            min_soc_pct=0,
            max_soc_pct=50,
            safe_default={
                "script": "script.battery_safe",
                "verify": {"entity": "sensor.bat", "expected": "== 0", "within_seconds": 30},
            },
        )
        prices = _make_price_forecast(1, base=-1.0)

        result = solver.solve(
            manifests=[battery],
            constraint_windows=[],
            price_forecast=prices,
            horizon_minutes=60,
            resolution_minutes=60,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert result.plans[0].slots[0].power_kw == pytest.approx(0.0)

    @pytest.mark.unit
    def test_solve_with_min_soc_constraint(self) -> None:
        """Solver respects min_soc_until constraint."""
        solver = MILPCentralSolver()
        battery = _make_battery()
        prices = _make_price_forecast(96)
        t0 = prices[0][0]

        cw = ConstraintWindow(
            window_id="test_soc",
            device_id="test_battery",
            deadline=t0 + timedelta(hours=12),
            requirement=MinSocUntil(min_soc_pct=80),
            priority_penalty=5.0,
            created_at=t0,
        )

        result = solver.solve(
            manifests=[battery],
            constraint_windows=[cw],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)

    @pytest.mark.unit
    def test_solve_ev_with_energy_constraint(self) -> None:
        """Solver delivers required energy for EV."""
        solver = MILPCentralSolver()
        ev = _make_ev_charger()
        prices = _make_price_forecast(96)
        t0 = prices[0][0]

        cw = ConstraintWindow(
            window_id="ev_energy",
            device_id="test_ev",
            deadline=t0 + timedelta(hours=8),
            requirement=MinEnergyUntil(min_energy_kwh=20.0),
            priority_penalty=8.0,
            created_at=t0,
        )

        result = solver.solve(
            manifests=[ev],
            constraint_windows=[cw],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        # Verify total energy delivered is >= 20 kWh. The deadline slot is
        # inclusive (deadline_slot + 1 slots), so the window is slots[:33] —
        # summing only 32 relied on solver tie-breaking on flat prices.
        plan = result.plans[0]
        total_energy = sum(s.power_kw * 0.25 for s in plan.slots[:33])
        assert total_energy >= 19.9  # slight tolerance for numerical

    @pytest.mark.unit
    def test_solve_forbidden_window(self) -> None:
        """Solver respects forbidden window constraint."""
        solver = MILPCentralSolver()
        thermo = _make_thermostat()
        prices = _make_price_forecast(96)
        t0 = prices[0][0]

        cw = ConstraintWindow(
            window_id="quiet_hours",
            device_id="test_thermo",
            deadline=t0 + timedelta(hours=6),
            requirement=ForbiddenWindow(),
            priority_penalty=5.0,
            created_at=t0,
        )

        result = solver.solve(
            manifests=[thermo],
            constraint_windows=[cw],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        # First 6 hours (24 slots) should have zero power
        plan = result.plans[0]
        for slot in plan.slots[:24]:
            assert abs(slot.power_kw) < 0.01

    @pytest.mark.unit
    def test_forbidden_window_for_storage_forces_zero_power(self) -> None:
        """ForbiddenWindow pins storage power to zero, not just on=0."""
        solver = MILPCentralSolver()
        battery = _make_battery()
        t0 = datetime(2026, 5, 6, 0, 0, tzinfo=UTC)
        prices = [(t0 + timedelta(hours=i), -1.0) for i in range(4)]
        cw = ConstraintWindow(
            window_id="battery_forbidden",
            device_id="test_battery",
            deadline=t0 + timedelta(hours=1),
            requirement=ForbiddenWindow(),
            priority_penalty=5.0,
            created_at=t0,
        )

        result = solver.solve(
            manifests=[battery],
            constraint_windows=[cw],
            price_forecast=prices,
            horizon_minutes=240,
            resolution_minutes=60,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        for slot in result.plans[0].slots[:2]:
            assert slot.power_kw == pytest.approx(0.0)

    @pytest.mark.unit
    def test_solve_with_min_runtime(self) -> None:
        """Solver satisfies minimum runtime constraint."""
        solver = MILPCentralSolver()
        hp = _make_heat_pump()
        prices = _make_price_forecast(96)
        t0 = prices[0][0]

        cw = ConstraintWindow(
            window_id="hp_runtime",
            device_id="test_hp",
            deadline=t0 + timedelta(hours=24),
            requirement=MinRuntimePerDay(min_hours=6),
            priority_penalty=4.0,
            created_at=t0,
        )

        result = solver.solve(
            manifests=[hp],
            constraint_windows=[cw],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        # Count active slots (24 slots = 6 hours)
        plan = result.plans[0]
        active_slots = sum(1 for s in plan.slots if s.mode == "active")
        assert active_slots >= 24

    @pytest.mark.unit
    def test_min_runtime_deadline_limits_counted_slots(self) -> None:
        """MinRuntimePerDay must be satisfied before its deadline slot."""
        solver = MILPCentralSolver()
        hp = _make_heat_pump()
        prices = _make_price_forecast(8)
        t0 = prices[0][0]
        cw = ConstraintWindow(
            window_id="hp_runtime_deadline",
            device_id="test_hp",
            deadline=t0 + timedelta(minutes=45),
            requirement=MinRuntimePerDay(min_hours=1),
            priority_penalty=4.0,
            created_at=t0,
        )

        result = solver.solve(
            manifests=[hp],
            constraint_windows=[cw],
            price_forecast=prices,
            horizon_minutes=120,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        active_slots_before_deadline = sum(1 for s in result.plans[0].slots[:4] if s.mode == "active")
        assert active_slots_before_deadline >= 4

    @pytest.mark.unit
    def test_plan_change_penalty_effect(self) -> None:
        """Plan-change penalty reduces deviation from previous plan."""
        battery = _make_battery()
        prices = _make_price_forecast(96)

        # First solve without penalty
        solver_no_penalty = MILPCentralSolver(plan_change_penalty=0.0)
        result1 = solver_no_penalty.solve(
            manifests=[battery],
            constraint_windows=[],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        # Second solve with heavy penalty using first plan as previous
        solver_penalty = MILPCentralSolver(plan_change_penalty=1.0)
        result2 = solver_penalty.solve(
            manifests=[battery],
            constraint_windows=[],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
            previous_plans=result1.plans,
        )

        # With heavy penalty, plan should stay very close to previous
        assert result2.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        if result1.plans and result2.plans:
            deviations = [
                abs(s1.power_kw - s2.power_kw)
                for s1, s2 in zip(result1.plans[0].slots, result2.plans[0].slots, strict=False)
            ]
            avg_deviation = sum(deviations) / len(deviations)
            # With high penalty, deviation should be very small
            assert avg_deviation < 1.0

    @pytest.mark.unit
    def test_solve_multiple_devices(self) -> None:
        """Solver handles multiple devices simultaneously."""
        solver = MILPCentralSolver()
        devices = [_make_battery(), _make_ev_charger(), _make_heat_pump()]
        prices = _make_price_forecast(96)

        result = solver.solve(
            manifests=devices,
            constraint_windows=[],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert len(result.plans) == 3

    @pytest.mark.unit
    def test_invalid_horizon_returns_error(self) -> None:
        """Invalid horizon produces error status."""
        solver = MILPCentralSolver()
        result = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=[],
            horizon_minutes=0,
            resolution_minutes=15,
        )
        assert result.status == SolverStatus.ERROR

    @pytest.mark.unit
    def test_solve_time_reported(self) -> None:
        """Solve time is reported in results."""
        solver = MILPCentralSolver()
        result = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=_make_price_forecast(96),
            horizon_minutes=1440,
            resolution_minutes=15,
        )
        assert result.solve_time_seconds > 0


@pytest.mark.req("002:FR-008")
class TestMILPCOPIntegration:
    """Tests for COP integration with the solver."""

    @pytest.mark.unit
    def test_cop_at_temp(self) -> None:
        solver = MILPCentralSolver(outdoor_temp_c=5.0)
        hp = _make_heat_pump()
        cop = solver.cop_at_temp(hp)
        # COP at 5°C with map [(-10, 2.5), (0, 3.5), (10, 4.5)] -> 4.0
        assert abs(cop - 4.0) < 0.01

    @pytest.mark.unit
    def test_cop_at_custom_temp(self) -> None:
        solver = MILPCentralSolver()
        hp = _make_heat_pump()
        cop = solver.cop_at_temp(hp, outdoor_temp=-5.0)
        # Between (-10, 2.5) and (0, 3.5) -> 3.0
        assert abs(cop - 3.0) < 0.01


class TestMILPReasonAnnotation:
    """Tests for reason annotation in solver output."""

    @pytest.mark.unit
    def test_plan_slots_have_reason(self) -> None:
        """Every slot in solver output has a non-None reason."""
        solver = MILPCentralSolver()
        battery = _make_battery()
        prices = _make_price_forecast(96)

        result = solver.solve(
            manifests=[battery],
            constraint_windows=[],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        for plan in result.plans:
            for slot in plan.slots:
                assert slot.reason is not None
                assert slot.reason in PlanReason

    @pytest.mark.unit
    def test_reason_idle_when_off(self) -> None:
        """Inactive slots (power ~0, on < 0.5) get reason=idle."""
        solver = MILPCentralSolver()
        battery = _make_battery()
        # Flat prices → some slots will be idle
        prices = _make_price_forecast(96, base=0.30)

        result = solver.solve(
            manifests=[battery],
            constraint_windows=[],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        plan = result.plans[0]
        idle_slots = [s for s in plan.slots if abs(s.power_kw) < 0.01]
        for slot in idle_slots:
            assert slot.reason == PlanReason.IDLE

    @pytest.mark.unit
    def test_reason_constraint_when_forced(self) -> None:
        """Constraint window → affected slots get reason=constraint."""
        solver = MILPCentralSolver()
        battery = _make_battery()
        t0 = datetime(2026, 5, 6, 0, 0, tzinfo=UTC)
        prices = [(t0 + timedelta(minutes=15 * i), 0.30) for i in range(96)]

        # Force battery to reach 80% SoC by slot 48 (12h)
        deadline = t0 + timedelta(hours=12)
        cw = ConstraintWindow(
            window_id="soc_target",
            device_id="test_battery",
            deadline=deadline,
            requirement=MinSocUntil(min_soc_pct=80),
            priority_penalty=5.0,
        )

        result = solver.solve(
            manifests=[battery],
            constraint_windows=[cw],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        plan = result.plans[0]
        # At least some active slots before the deadline should be marked 'constraint'
        constrained_active = [
            s for i, s in enumerate(plan.slots[:48]) if s.reason == PlanReason.CONSTRAINT and abs(s.power_kw) > 0.01
        ]
        assert len(constrained_active) > 0

    @pytest.mark.unit
    def test_reason_cheap_grid_in_valley(self) -> None:
        """Battery charges in cheap slots → reason=cheap_grid."""
        solver = MILPCentralSolver()
        battery = _make_battery()
        t0 = datetime(2026, 5, 6, 0, 0, tzinfo=UTC)
        # Create variable prices: cheap at night, expensive during day
        prices = []
        for i in range(96):
            hour = (i * 15) / 60
            price = 0.15 if hour < 6 or hour >= 22 else 0.45
            prices.append((t0 + timedelta(minutes=15 * i), price))

        result = solver.solve(
            manifests=[battery],
            constraint_windows=[],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        plan = result.plans[0]
        # Charging slots (positive power, in cheap time) should be cheap_grid
        cheap_charging = [s for i, s in enumerate(plan.slots) if s.power_kw > 0.1 and s.reason == PlanReason.CHEAP_GRID]
        # Battery should charge during cheap periods
        assert len(cheap_charging) > 0


# --- Thermal model helpers ---


def _make_room() -> RoomManifest:
    return RoomManifest(
        device_id="test_room",
        name="Test Room",
        floor_area_m2=25.0,
        thermal_mass_kwh_per_k=2.0,
        u_value_w_per_m2k=0.5,
        window_area_m2=5.0,
        safe_default={
            "script": "script.room_safe",
            "verify": {"entity": "sensor.room", "expected": "== off", "within_seconds": 30},
        },
    )


def _make_heat_pump_for_room(room_id: str = "test_room") -> HeatPumpManifest:
    return HeatPumpManifest(
        device_id="test_hp_room",
        name="Room Heat Pump",
        max_power_kw=5.0,
        cop_map=[(-10, 2.5), (0, 3.5), (10, 4.5)],
        room_id=room_id,
        safe_default={
            "script": "script.hp_safe",
            "verify": {"entity": "sensor.hp", "expected": "== idle", "within_seconds": 30},
        },
    )


def _make_cold_weather(n_slots: int = 96) -> list[tuple[datetime, float]]:
    """Outdoor temps cycling 0-5 °C (typical winter day)."""
    import math

    t0 = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
    return [(t0 + timedelta(minutes=15 * i), 2.5 + 2.5 * math.sin(2 * math.pi * i / 96)) for i in range(n_slots)]


# --- Thermal model tests ---


@pytest.mark.req("002:FR-009")
class TestThermalModel:
    """Tests for the lumped-RC thermal model in the MILP solver."""

    @pytest.mark.unit
    def test_hold_temp_band_flat_price_cold_day(self) -> None:
        """Heat pump runs enough to hold comfort band on a cold day with flat prices."""
        solver = MILPCentralSolver()
        room = _make_room()
        hp = _make_heat_pump_for_room()
        prices = _make_price_forecast(96, base=0.30)
        weather = _make_cold_weather(96)

        # Hold the band across the whole visible day. The old value (2026-01-16)
        # predated the price series and only "worked" through the clamp-to-slot-0
        # behavior that FR-206 removed.
        deadline = prices[0][0] + timedelta(hours=24)
        cw = ConstraintWindow(
            window_id="comfort",
            device_id="test_room",
            deadline=deadline,
            requirement=HoldTempBand(min_temp_c=20.0, max_temp_c=23.0),
            priority_penalty=3.0,
        )

        result = solver.solve(
            manifests=[room, hp],
            constraint_windows=[cw],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
            weather_forecast=weather,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert result.solve_time_seconds < 5.0

        # Heat pump should run in some slots
        hp_plan = next(p for p in result.plans if p.device_id == "test_hp_room")
        active_slots = [s for s in hp_plan.slots if s.power_kw > 0.01]
        assert len(active_slots) > 0, "Heat pump must run to maintain comfort"

    @pytest.mark.unit
    def test_hold_temp_band_preheats_before_price_peak(self) -> None:
        """With double-price peak, solver shifts heating before the peak using thermal mass."""
        solver = MILPCentralSolver()
        room = _make_room()
        hp = _make_heat_pump_for_room()
        weather = _make_cold_weather(96)

        t0 = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
        # Cheap at night (slots 0-31), expensive in day (32-63), cheap again (64-95)
        prices = []
        for i in range(96):
            price = 0.15 if i < 32 or i >= 64 else 0.45
            prices.append((t0 + timedelta(minutes=15 * i), price))

        deadline = t0 + timedelta(hours=24)
        cw = ConstraintWindow(
            window_id="comfort",
            device_id="test_room",
            deadline=deadline,
            requirement=HoldTempBand(min_temp_c=19.0, max_temp_c=24.0),
            priority_penalty=5.0,
        )

        result = solver.solve(
            manifests=[room, hp],
            constraint_windows=[cw],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
            weather_forecast=weather,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)

        hp_plan = next(p for p in result.plans if p.device_id == "test_hp_room")
        # Compare heating energy in cheap vs expensive periods
        cheap_energy = sum(s.power_kw for s in hp_plan.slots[:32] if s.power_kw > 0)
        peak_energy = sum(s.power_kw for s in hp_plan.slots[32:64] if s.power_kw > 0)
        # Solver should shift heating to cheap period (pre-heat)
        assert cheap_energy >= peak_energy, (
            f"Expected more heating in cheap period ({cheap_energy:.1f}) than peak ({peak_energy:.1f})"
        )

    @pytest.mark.unit
    def test_reach_min_temp_once_legionella(self) -> None:
        """ReachMinTempOnce: hot water legionella case hits target before deadline."""
        solver = MILPCentralSolver()
        room = RoomManifest(
            device_id="hw_tank",
            name="Hot Water Tank Room",
            floor_area_m2=2.0,
            thermal_mass_kwh_per_k=0.15,  # Small tank ~50L
            u_value_w_per_m2k=0.3,
            safe_default={
                "script": "script.tank_safe",
                "verify": {"entity": "sensor.tank", "expected": "== off", "within_seconds": 30},
            },
        )
        heater = ThermostatLoadManifest(
            device_id="hw_heater",
            name="Tank Heater",
            max_power_kw=3.0,
            room_id="hw_tank",
            safe_default={
                "script": "script.heater_safe",
                "verify": {"entity": "sensor.heater", "expected": "== off", "within_seconds": 30},
            },
        )

        t0 = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
        prices = [(t0 + timedelta(minutes=15 * i), 0.30) for i in range(48)]
        weather = _make_cold_weather(48)

        deadline = t0 + timedelta(hours=12)
        cw = ConstraintWindow(
            window_id="legionella",
            device_id="hw_tank",
            deadline=deadline,
            requirement=ReachMinTempOnce(target_temp_c=60.0),
            priority_penalty=10.0,
        )

        result = solver.solve(
            manifests=[room, heater],
            constraint_windows=[cw],
            price_forecast=prices,
            horizon_minutes=720,
            resolution_minutes=15,
            weather_forecast=weather,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert result.solve_time_seconds < 5.0

        # Heater should run heavily to reach 60°C
        heater_plan = next(p for p in result.plans if p.device_id == "hw_heater")
        total_energy = sum(s.power_kw for s in heater_plan.slots if s.power_kw > 0)
        assert total_energy > 0, "Heater must run to reach legionella temperature"

    @pytest.mark.unit
    def test_room_id_links_heater_to_room(self) -> None:
        """Heat pump with room_id=None doesn't contribute to any room's thermal model."""
        solver = MILPCentralSolver()
        room = _make_room()
        hp_unlinked = HeatPumpManifest(
            device_id="hp_unlinked",
            name="Unlinked HP",
            max_power_kw=5.0,
            safe_default={
                "script": "script.hp_safe",
                "verify": {"entity": "sensor.hp", "expected": "== idle", "within_seconds": 30},
            },
        )
        # room_id is None → unlinked
        assert hp_unlinked.room_id is None

        prices = _make_price_forecast(24, base=0.30)
        weather = _make_cold_weather(24)

        result = solver.solve(
            manifests=[room, hp_unlinked],
            constraint_windows=[],
            price_forecast=prices,
            horizon_minutes=360,
            resolution_minutes=15,
            weather_forecast=weather,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)

    @pytest.mark.unit
    def test_no_weather_uses_default_outdoor_temp(self) -> None:
        """Without weather_forecast, solver uses constructor default outdoor temp."""
        solver = MILPCentralSolver(outdoor_temp_c=3.0)
        room = _make_room()
        hp = _make_heat_pump_for_room()
        prices = _make_price_forecast(24, base=0.30)

        t0 = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
        deadline = t0 + timedelta(hours=6)
        cw = ConstraintWindow(
            window_id="comfort",
            device_id="test_room",
            deadline=deadline,
            requirement=HoldTempBand(min_temp_c=19.0, max_temp_c=23.0),
            priority_penalty=3.0,
        )

        result = solver.solve(
            manifests=[room, hp],
            constraint_windows=[cw],
            price_forecast=prices,
            horizon_minutes=360,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)


# --- Grid-settlement economics tests (review 001: FR-001/FR-002) ---


class _ForecastSourceManifest:
    """Minimal duck-typed manifest whose source carries a real forecast."""

    device_id = "pv_stub"
    name = "PV Stub"

    def to_components(self) -> list[ComponentSpec]:
        return [SourceSpec(device_id=self.device_id, forecast=[2.0] * 8)]


@pytest.mark.req("002:FR-002", "002:FR-005")
class TestGridSettlement:
    """No free money: exports, terminal SoC, and runtime power are honest."""

    @pytest.mark.unit
    def test_flat_prices_battery_stays_idle(self) -> None:
        """A lone battery cannot profit under a flat tariff (no money printer)."""
        solver = MILPCentralSolver()
        result = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=_make_price_forecast(96),
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert result.objective_value == pytest.approx(0.0, abs=1e-6)
        slots = result.plans[0].slots
        assert all(abs(s.power_kw) < 0.01 for s in slots)
        assert all(s.mode == "idle" for s in slots)

    @pytest.mark.unit
    def test_zero_feed_in_kills_export_arbitrage(self) -> None:
        """With feed-in below the buy price, a lone battery has no arbitrage."""
        solver = MILPCentralSolver(feed_in_tariff=0.0)
        t0 = datetime(2026, 5, 6, 0, 0, tzinfo=UTC)
        prices = [(t0 + timedelta(minutes=15 * i), 0.10 if i < 48 else 0.40) for i in range(96)]
        result = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert result.objective_value >= -1e-6

    @pytest.mark.unit
    def test_source_production_is_negative_power(self) -> None:
        """A forecast-backed source produces (negative power) and earns credit."""
        solver = MILPCentralSolver()
        result = solver.solve(
            manifests=[_ForecastSourceManifest()],
            constraint_windows=[],
            price_forecast=_make_price_forecast(8),
            horizon_minutes=120,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        powers = [s.power_kw for s in result.plans[0].slots]
        assert all(p <= 1e-6 for p in powers)
        assert min(powers) == pytest.approx(-2.0)
        assert result.objective_value < 0

    @pytest.mark.unit
    def test_min_runtime_runs_at_rated_power(self) -> None:
        """Min-runtime slots draw rated power — on=1 at 0 kW is not compliance."""
        solver = MILPCentralSolver()
        hp = _make_heat_pump()
        prices = _make_price_forecast(96)
        cw = ConstraintWindow(
            window_id="hp_runtime",
            device_id="test_hp",
            deadline=prices[0][0] + timedelta(hours=24),
            requirement=MinRuntimePerDay(min_hours=6),
            priority_penalty=4.0,
            created_at=prices[0][0],
        )
        result = solver.solve(
            manifests=[hp],
            constraint_windows=[cw],
            price_forecast=prices,
            horizon_minutes=1440,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        rated_slots = sum(1 for s in result.plans[0].slots if s.power_kw >= 5.0 - 1e-6)
        assert rated_slots >= 24


def _make_pv(peak_kwp: float = 3.0) -> PVForecastManifest:
    return PVForecastManifest(
        device_id="pv1",
        name="Test PV",
        peak_power_kwp=peak_kwp,
        safe_default={"script": "script.pv_safe"},
    )


@pytest.mark.req("002:FR-006")
class TestPVDispatch:
    """FR-006: injected generation reaches the energy balance; curtailment only pays."""

    @pytest.mark.unit
    def test_generation_forecast_dispatches_pv(self) -> None:
        """A PV manifest with an injected series produces at the forecast bound."""
        solver = MILPCentralSolver()
        result = solver.solve(
            manifests=[_make_pv()],
            constraint_windows=[],
            price_forecast=_make_price_forecast(8),
            horizon_minutes=120,
            resolution_minutes=15,
            generation_forecast={"pv1": [3.0] * 8},
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        powers = [s.power_kw for s in result.plans[0].slots]
        assert all(p == pytest.approx(-3.0) for p in powers), powers
        assert result.objective_value < 0  # production earns, i.e. reduces import

    @pytest.mark.unit
    def test_pv_curtailed_only_when_export_costs(self) -> None:
        """Curtailment engages exactly when exporting costs money (negative feed-in).

        This is the behavior the curtailable-variable form of FR-006 buys over
        the original fixed-parameter wording (decision 2026-07-10)."""
        for feed_in, expected in ((-0.05, 0.0), (0.05, -3.0)):
            solver = MILPCentralSolver(feed_in_tariff=feed_in)
            result = solver.solve(
                manifests=[_make_pv()],
                constraint_windows=[],
                price_forecast=_make_price_forecast(8),
                horizon_minutes=120,
                resolution_minutes=15,
                generation_forecast={"pv1": [3.0] * 8},
            )
            assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
            powers = [s.power_kw for s in result.plans[0].slots]
            assert all(p == pytest.approx(expected, abs=1e-6) for p in powers), (feed_in, powers)

    @pytest.mark.unit
    def test_sim_runner_injects_pv_series(self) -> None:
        """The sim runner synthesizes a generation series for PV manifests (FR-006)."""
        from hemm_core.sim.runner import SimRunner
        from hemm_core.sim.scenario import Scenario

        scenario = Scenario(
            name="pv_dispatch",
            horizon_hours=24,
            resolution_minutes=60,
            manifests=[_make_pv().model_dump(mode="json")],
        )
        result = SimRunner().run(scenario)
        assert result.success, result.error
        pv_plan = next(p for p in result.plans if p.device_id == "pv1")
        assert min(s.power_kw for s in pv_plan.slots) < 0, "PV never dispatched by the runner"
