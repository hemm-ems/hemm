"""Tests for the solver protocol and MILP central solver."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hemm.manifest.constraints import ForbiddenWindow, MinEnergyUntil, MinRuntimePerDay, MinSocUntil
from hemm.manifest.messages import ConstraintWindow
from hemm.manifest.types import BatteryManifest, EVChargerManifest, HeatPumpManifest, ThermostatLoadManifest
from hemm.solvers.milp_central import DEFAULT_COP_MAP, MILPCentralSolver, _piecewise_cop
from hemm.solvers.protocol import SolverResult, SolverStatus

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
        # Verify total energy delivered is >= 20 kWh
        plan = result.plans[0]
        total_energy = sum(s.power_kw * 0.25 for s in plan.slots[:32])  # first 8 hours
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
