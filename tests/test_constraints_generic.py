"""Generic (primitive-targeted) constraint tests (feature 003).

Scaffold created in T003. Tests are added in T022 (003:FR-008): constraints
resolve to primitive state vars/flows (storage level / node thermal state /
flow integral), and a constraint targeting a state a device's primitives do not
provide is rejected at validation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hemm_core.manifest.constraints import HoldTempBand, MinSocUntil
from hemm_core.manifest.messages import ConstraintWindow
from hemm_core.manifest.types import (
    EVChargerManifest,
    HeatPumpManifest,
    PoolPumpManifest,
    WaterHeaterManifest,
)
from hemm_core.manifest.validator import ValidationError, validate_constraint_targets
from hemm_core.solvers.milp_central import MILPCentralSolver
from hemm_core.solvers.protocol import SolverStatus

# REQ: 003:FR-008


def _safe_default() -> dict[str, str]:
    return {"script": "script.safe_default"}


def _prices(n_slots: int, base: float = 0.30) -> list[tuple[datetime, float]]:
    t0 = datetime(2026, 5, 7, 0, 0, tzinfo=UTC)
    return [(t0 + timedelta(minutes=15 * i), base) for i in range(n_slots)]


@pytest.mark.req("003:FR-008")
class TestPrimitiveTargetedConstraints:
    @pytest.mark.unit
    def test_hold_temp_band_targets_water_heater_thermal_node(self) -> None:
        dhw = WaterHeaterManifest(
            device_id="dhw",
            name="Domestic Hot Water",
            volume_liters=200.0,
            max_power_kw=3.0,
            standby_loss_w=45.0,
            safe_default=_safe_default(),
        )
        prices = _prices(24)
        t0 = prices[0][0]
        constraint = ConstraintWindow(
            window_id="dhw_comfort",
            device_id="dhw",
            deadline=t0 + timedelta(hours=6),
            requirement=HoldTempBand(min_temp_c=45.0, max_temp_c=80.0),
            priority_penalty=100.0,
        )

        result = MILPCentralSolver().solve(
            manifests=[dhw],
            constraint_windows=[constraint],
            price_forecast=prices,
            horizon_minutes=360,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        plan = next(plan for plan in result.plans if plan.device_id == "dhw")
        assert any(slot.power_kw > 0.01 for slot in plan.slots)

    @pytest.mark.unit
    def test_min_soc_until_targets_ev_storage_level(self) -> None:
        ev = EVChargerManifest(
            device_id="ev",
            name="Garage EV",
            max_charge_kw=11.0,
            battery_capacity_kwh=60.0,
            safe_default=_safe_default(),
        )
        prices = _prices(24)
        t0 = prices[0][0]
        constraint = ConstraintWindow(
            window_id="ev_soc",
            device_id="ev",
            deadline=t0 + timedelta(hours=3),
            requirement=MinSocUntil(min_soc_pct=60.0),
            priority_penalty=10.0,
        )

        result = MILPCentralSolver().solve(
            manifests=[ev],
            constraint_windows=[constraint],
            price_forecast=prices,
            horizon_minutes=360,
            resolution_minutes=15,
        )

        assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        plan = next(plan for plan in result.plans if plan.device_id == "ev")
        delivered_kwh = sum(slot.power_kw * 0.25 for slot in plan.slots[:13])
        assert delivered_kwh >= 6.0

    @pytest.mark.unit
    def test_bad_target_constraint_is_rejected_by_solve_path(self) -> None:
        pool_pump = PoolPumpManifest(
            device_id="pool_pump",
            name="Pool Pump",
            max_power_kw=1.2,
            safe_default=_safe_default(),
        )
        prices = _prices(4)
        constraint = ConstraintWindow(
            window_id="pool_soc",
            device_id="pool_pump",
            deadline=prices[0][0] + timedelta(hours=1),
            requirement=MinSocUntil(min_soc_pct=80.0),
        )

        with pytest.raises(ValidationError) as exc_info:
            MILPCentralSolver().solve(
                manifests=[pool_pump],
                constraint_windows=[constraint],
                price_forecast=prices,
                horizon_minutes=60,
                resolution_minutes=15,
            )

        message = str(exc_info.value)
        assert "pool_pump" in message
        assert "min_soc_until" in message
        assert "storage level" in message

    @pytest.mark.unit
    def test_converter_output_bus_must_reference_compiled_node(self) -> None:
        heat_pump = HeatPumpManifest(
            device_id="heat_pump",
            name="Heat Pump",
            max_power_kw=5.0,
            room_id="missing_room",
            safe_default=_safe_default(),
        )

        with pytest.raises(ValidationError) as exc_info:
            validate_constraint_targets([heat_pump], [])

        message = str(exc_info.value)
        assert "heat_pump" in message
        assert "thermal:missing_room" in message
        assert "compiled node" in message
