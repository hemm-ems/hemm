"""RW1 FR-105/FR-106 — the solver starts from measured state, not hardcoded defaults.

These tests prove the new ``initial_state`` argument and per-slot weather are
actually consumed by both backends (a change in the measured start changes the
plan). Omitting them is covered by the wider regression suite / golden parity,
which stays bit-identical.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hemm_core.manifest.components import DEFAULT_COP_MAP, ConverterSpec
from hemm_core.manifest.constraints import MinSocUntil, ReachMinTempOnce
from hemm_core.manifest.messages import ConstraintWindow
from hemm_core.manifest.types import BatteryManifest, HeatPumpManifest, RoomManifest
from hemm_core.solvers.consumers import ConverterConsumer
from hemm_core.solvers.distributed import DistributedSolver
from hemm_core.solvers.milp_central import MILPCentralSolver
from hemm_core.solvers.protocol import SolverStatus

_DT_HOURS = 0.25  # 15-minute slots


def _prices(n: int = 96, value: float = 0.30) -> list[tuple[datetime, float]]:
    t0 = datetime(2026, 5, 7, tzinfo=UTC)
    return [(t0 + timedelta(minutes=15 * i), value) for i in range(n)]


def _battery() -> BatteryManifest:
    return BatteryManifest(
        device_id="bat",
        name="Battery",
        capacity_kwh=10.0,
        max_charge_kw=5.0,
        max_discharge_kw=5.0,
        min_soc_pct=10,
        max_soc_pct=90,
        safe_default={"script": "script.bat_safe"},
    )


def _soc_window(t0: datetime) -> ConstraintWindow:
    return ConstraintWindow(
        window_id="reach_soc",
        device_id="bat",
        deadline=t0 + timedelta(hours=12),
        requirement=MinSocUntil(min_soc_pct=80),
        priority_penalty=5.0,
        created_at=t0,
    )


def _charge_kwh(plan) -> float:
    return sum(max(0.0, slot.power_kw) * _DT_HOURS for slot in plan.slots)


class TestBackendAInitialState:
    @pytest.mark.unit
    def test_battery_measured_soc_reduces_required_charge(self) -> None:
        """A near-full measured SoC needs far less charging to meet a MinSoc target."""
        solver = MILPCentralSolver()
        prices = _prices()
        cw = _soc_window(prices[0][0])

        default = solver.solve([_battery()], [cw], prices, 1440, 15)
        measured = solver.solve([_battery()], [cw], prices, 1440, 15, initial_state={"bat": {"soc_kwh": 8.5}})

        assert default.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert measured.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        # Default starts at 5 kWh and must charge to 8 kWh; starting at 8.5 kWh
        # the 80 % target is already met, so charging drops by a clear margin.
        assert _charge_kwh(default.plans[0]) > _charge_kwh(measured.plans[0]) + 1.0

    @pytest.mark.unit
    def test_room_measured_temperature_avoids_heating(self) -> None:
        """A warm measured room already satisfies ReachMinTempOnce → no heat pump run."""
        solver = MILPCentralSolver()
        prices = _prices()
        room = RoomManifest(
            device_id="room",
            name="Room",
            floor_area_m2=20.0,
            insulation_class="medium",
            safe_default={"script": "script.room_safe"},
        )
        heat_pump = HeatPumpManifest(
            device_id="hp",
            name="Heat Pump",
            max_power_kw=3.0,
            room_id="room",
            safe_default={"script": "script.hp_safe"},
        )
        cw = ConstraintWindow(
            window_id="reach_temp",
            device_id="room",
            deadline=prices[0][0] + timedelta(hours=6),
            requirement=ReachMinTempOnce(target_temp_c=22.0),
            priority_penalty=5.0,
            created_at=prices[0][0],
        )

        cold = solver.solve([room, heat_pump], [cw], prices, 1440, 15)
        warm = solver.solve([room, heat_pump], [cw], prices, 1440, 15, initial_state={"room": {"temp_c": 25.0}})

        def hp_energy(result) -> float:
            plan = next(p for p in result.plans if p.device_id == "hp")
            return sum(max(0.0, s.power_kw) * _DT_HOURS for s in plan.slots)

        assert hp_energy(cold) > hp_energy(warm)


class TestBackendBInitialState:
    @pytest.mark.unit
    def test_battery_measured_soc_reduces_required_charge(self) -> None:
        """Backend B's StorageConsumer also starts from the measured level."""
        solver = DistributedSolver()
        prices = _prices()
        cw = _soc_window(prices[0][0])

        default = solver.solve([_battery()], [cw], prices, 1440, 15)
        measured = solver.solve([_battery()], [cw], prices, 1440, 15, initial_state={"bat": {"soc_kwh": 8.5}})

        assert _charge_kwh(default.plans[0]) > _charge_kwh(measured.plans[0]) + 1.0


class TestBackendBWeather:
    @pytest.mark.unit
    def test_converter_cop_tracks_per_slot_outdoor_temperature(self) -> None:
        """A per-slot weather series changes the COP factor per slot (FR-106)."""
        converter = ConverterSpec(
            device_id="hp",
            output_bus="thermal:room",
            max_input_kw=3.0,
            factor_map=DEFAULT_COP_MAP,
            factor_ctx="outdoor_temp",
        )
        consumer = ConverterConsumer(manifest=None, component=converter, outdoor_temps=[-15.0, 15.0])
        # DEFAULT_COP_MAP: COP 2.0 at -15 °C, 5.0 at 15 °C.
        assert consumer._factor_at_slot(0) == pytest.approx(2.0)
        assert consumer._factor_at_slot(1) == pytest.approx(5.0)
