"""Tests for the distributed solver (Backend B)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hemm_core.manifest.constraints import MinSocUntil
from hemm_core.manifest.messages import ConstraintWindow
from hemm_core.manifest.types import BatteryManifest, EVChargerManifest, HeatPumpManifest, ThermostatLoadManifest
from hemm_core.solvers.distributed import DistributedSolver
from hemm_core.solvers.protocol import SolverStatus

T0 = datetime(2026, 5, 6, 0, 0, tzinfo=UTC)


def _make_battery() -> BatteryManifest:
    return BatteryManifest(
        device_id="bat_1",
        name="Test Battery",
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


def _make_ev() -> EVChargerManifest:
    return EVChargerManifest(
        device_id="ev_1",
        name="Test EV",
        max_charge_kw=11.0,
        min_charge_kw=1.4,
        phases=3,
        battery_capacity_kwh=60.0,
        safe_default={
            "script": "script.ev_safe",
            "verify": {"entity": "sensor.ev", "expected": "== 0", "within_seconds": 30},
        },
    )


def _make_heat_pump() -> HeatPumpManifest:
    return HeatPumpManifest(
        device_id="hp_1",
        name="Test HP",
        max_power_kw=5.0,
        cop_map=[(-10, 2.5), (0, 3.5), (10, 4.5)],
        safe_default={
            "script": "script.hp_safe",
            "verify": {"entity": "sensor.hp", "expected": "== idle", "within_seconds": 30},
        },
    )


def _make_thermostat() -> ThermostatLoadManifest:
    return ThermostatLoadManifest(
        device_id="thermo_1",
        name="Test Thermostat",
        max_power_kw=2.0,
        safe_default={
            "script": "script.thermo_safe",
            "verify": {"entity": "sensor.thermo", "expected": "== off", "within_seconds": 30},
        },
    )


def _make_price_forecast(n_slots: int = 96) -> list[tuple[datetime, float]]:
    """Varying price forecast."""
    prices = []
    for i in range(n_slots):
        hour = (i * 15 / 60) % 24
        if hour < 6 or hour > 22:
            price = 0.15
        elif 17 <= hour <= 20:
            price = 0.50
        else:
            price = 0.30
        prices.append((T0 + timedelta(minutes=i * 15), price))
    return prices


class TestDistributedSolverProtocol:
    """Tests that the distributed solver satisfies the solver protocol."""

    @pytest.mark.unit
    def test_has_name(self) -> None:
        solver = DistributedSolver(mode="price_iteration")
        assert solver.name == "distributed_price_iteration"

    @pytest.mark.unit
    def test_has_name_admm(self) -> None:
        solver = DistributedSolver(mode="admm")
        assert solver.name == "distributed_admm"

    @pytest.mark.unit
    def test_returns_solver_result(self) -> None:
        solver = DistributedSolver(max_iterations=5)
        result = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=_make_price_forecast(),
        )
        assert isinstance(result.status, SolverStatus)
        assert result.solve_time_seconds >= 0

    @pytest.mark.unit
    def test_empty_manifests(self) -> None:
        solver = DistributedSolver(max_iterations=5)
        result = solver.solve(
            manifests=[],
            constraint_windows=[],
            price_forecast=_make_price_forecast(),
        )
        assert result.status == SolverStatus.OPTIMAL
        assert result.plans == []


class TestDistributedSolverPriceIteration:
    """Tests for price iteration mode."""

    @pytest.mark.unit
    def test_single_battery(self) -> None:
        solver = DistributedSolver(mode="price_iteration", max_iterations=10)
        result = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=_make_price_forecast(),
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert len(result.plans) == 1
        assert result.plans[0].device_id == "bat_1"
        assert len(result.plans[0].slots) == 96

    @pytest.mark.unit
    def test_multiple_devices(self) -> None:
        solver = DistributedSolver(mode="price_iteration", max_iterations=10)
        manifests = [_make_battery(), _make_ev(), _make_heat_pump(), _make_thermostat()]
        result = solver.solve(
            manifests=manifests,
            constraint_windows=[],
            price_forecast=_make_price_forecast(),
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert len(result.plans) == 4

    @pytest.mark.unit
    def test_respects_constraint_windows(self) -> None:
        solver = DistributedSolver(mode="price_iteration", max_iterations=10)
        cw = ConstraintWindow(
            window_id="soc1",
            device_id="bat_1",
            deadline=T0 + timedelta(hours=8),
            requirement=MinSocUntil(min_soc_pct=80),
            priority_penalty=5.0,
        )
        result = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[cw],
            price_forecast=_make_price_forecast(),
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert len(result.plans) == 1

    @pytest.mark.unit
    def test_plan_change_penalty(self) -> None:
        solver = DistributedSolver(mode="price_iteration", max_iterations=10, plan_change_penalty=0.1)
        # First solve
        result1 = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=_make_price_forecast(),
        )
        # Second solve with previous plans
        result2 = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=_make_price_forecast(),
            previous_plans=result1.plans,
        )
        assert result2.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)

    @pytest.mark.unit
    def test_iterations_reported(self) -> None:
        solver = DistributedSolver(mode="price_iteration", max_iterations=10)
        result = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=_make_price_forecast(),
        )
        assert result.iterations > 0
        assert result.iterations <= 10

    @pytest.mark.unit
    def test_convergence_diagnostic(self) -> None:
        solver = DistributedSolver(mode="price_iteration", max_iterations=50)
        result = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=_make_price_forecast(),
        )
        assert "converged" in result.diagnostics
        assert "n_consumers" in result.diagnostics


class TestDistributedSolverADMM:
    """Tests for ADMM mode."""

    @pytest.mark.unit
    def test_admm_single_device(self) -> None:
        solver = DistributedSolver(mode="admm", max_iterations=15)
        result = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=_make_price_forecast(),
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert len(result.plans) == 1

    @pytest.mark.unit
    def test_admm_multiple_devices(self) -> None:
        solver = DistributedSolver(mode="admm", max_iterations=15)
        manifests = [_make_battery(), _make_heat_pump(), _make_thermostat()]
        result = solver.solve(
            manifests=manifests,
            constraint_windows=[],
            price_forecast=_make_price_forecast(),
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert len(result.plans) == 3

    @pytest.mark.unit
    def test_admm_convergence(self) -> None:
        solver = DistributedSolver(mode="admm", max_iterations=50, rho=0.1)
        result = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=_make_price_forecast(),
        )
        assert result.diagnostics.get("mode") == "admm"


class TestDistributedSolverEdgeCases:
    """Edge case tests."""

    @pytest.mark.unit
    def test_invalid_horizon(self) -> None:
        solver = DistributedSolver()
        result = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=_make_price_forecast(),
            horizon_minutes=0,
        )
        assert result.status == SolverStatus.ERROR

    @pytest.mark.unit
    def test_empty_price_forecast(self) -> None:
        solver = DistributedSolver(max_iterations=5)
        result = solver.solve(
            manifests=[_make_battery()],
            constraint_windows=[],
            price_forecast=[],
        )
        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)

    @pytest.mark.unit
    def test_time_limit_respected(self) -> None:
        solver = DistributedSolver(max_iterations=1000, time_limit_seconds=0.5)
        manifests = [_make_battery(), _make_ev(), _make_heat_pump(), _make_thermostat()]
        result = solver.solve(
            manifests=manifests,
            constraint_windows=[],
            price_forecast=_make_price_forecast(),
        )
        assert result.solve_time_seconds < 5.0  # Should respect time limit
