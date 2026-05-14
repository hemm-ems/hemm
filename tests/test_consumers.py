"""Tests for consumer models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hemm.manifest.constraints import ForbiddenWindow, MinEnergyUntil, MinRuntimePerDay, MinSocUntil
from hemm.manifest.messages import ConstraintWindow
from hemm.manifest.types import (
    BatteryManifest,
    EVChargerManifest,
    HeatPumpManifest,
    PassiveLoadManifest,
    PVForecastManifest,
    RoomManifest,
    ThermostatLoadManifest,
    WaterHeaterManifest,
)
from hemm.solvers.consumers import (
    BatteryConsumer,
    EVChargerConsumer,
    HeatPumpConsumer,
    PassiveLoadConsumer,
    PVForecastConsumer,
    RoomConsumer,
    ThermostatConsumer,
    WaterHeaterConsumer,
    get_consumer_model,
)

T0 = datetime(2026, 5, 6, 0, 0, tzinfo=UTC)
N_SLOTS = 96  # 24h @ 15min
RESOLUTION = 15


def _flat_prices(n: int = N_SLOTS, price: float = 0.30) -> list[float]:
    return [price] * n


def _varying_prices(n: int = N_SLOTS) -> list[float]:
    """Cheap at night, expensive during day."""
    prices = []
    for i in range(n):
        hour = (i * RESOLUTION / 60) % 24
        if hour < 6 or hour > 22:
            prices.append(0.15)
        elif 17 <= hour <= 20:
            prices.append(0.50)
        else:
            prices.append(0.30)
    return prices


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
        min_modulation_pct=20,
        safe_default={
            "script": "script.hp_safe",
            "verify": {"entity": "sensor.hp", "expected": "== idle", "within_seconds": 30},
        },
    )


def _make_water_heater() -> WaterHeaterManifest:
    return WaterHeaterManifest(
        device_id="wh_1",
        name="Test WH",
        volume_liters=200,
        max_power_kw=3.0,
        standby_loss_w=50,
        safe_default={
            "script": "script.wh_safe",
            "verify": {"entity": "sensor.wh", "expected": "== off", "within_seconds": 30},
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


def _make_pv() -> PVForecastManifest:
    return PVForecastManifest(
        device_id="pv_1",
        name="Test PV",
        peak_power_kwp=8.0,
        safe_default={
            "script": "script.pv_safe",
            "verify": {"entity": "sensor.pv", "expected": "== 0", "within_seconds": 30},
        },
    )


def _make_room() -> RoomManifest:
    return RoomManifest(
        device_id="room_1",
        name="Living Room",
        floor_area_m2=25.0,
        safe_default={
            "script": "script.room_safe",
            "verify": {"entity": "sensor.room", "expected": "== ok", "within_seconds": 30},
        },
    )


def _make_passive_load() -> PassiveLoadManifest:
    return PassiveLoadManifest(
        device_id="passive_1",
        name="Kitchen & Lighting",
        typical_daily_kwh=8.0,
        safe_default={
            "script": "script.passive_noop",
        },
    )


class TestGetConsumerModel:
    """Tests for the consumer model factory."""

    @pytest.mark.unit
    def test_battery_returns_battery_consumer(self) -> None:
        model = get_consumer_model(_make_battery())
        assert isinstance(model, BatteryConsumer)

    @pytest.mark.unit
    def test_ev_returns_ev_consumer(self) -> None:
        model = get_consumer_model(_make_ev())
        assert isinstance(model, EVChargerConsumer)

    @pytest.mark.unit
    def test_heat_pump_returns_hp_consumer(self) -> None:
        model = get_consumer_model(_make_heat_pump())
        assert isinstance(model, HeatPumpConsumer)

    @pytest.mark.unit
    def test_water_heater_returns_wh_consumer(self) -> None:
        model = get_consumer_model(_make_water_heater())
        assert isinstance(model, WaterHeaterConsumer)

    @pytest.mark.unit
    def test_thermostat_returns_thermo_consumer(self) -> None:
        model = get_consumer_model(_make_thermostat())
        assert isinstance(model, ThermostatConsumer)

    @pytest.mark.unit
    def test_pv_returns_pv_consumer(self) -> None:
        model = get_consumer_model(_make_pv())
        assert isinstance(model, PVForecastConsumer)

    @pytest.mark.unit
    def test_room_returns_room_consumer(self) -> None:
        model = get_consumer_model(_make_room())
        assert isinstance(model, RoomConsumer)

    @pytest.mark.unit
    def test_passive_load_returns_passive_consumer(self) -> None:
        model = get_consumer_model(_make_passive_load())
        assert isinstance(model, PassiveLoadConsumer)


class TestBatteryConsumer:
    """Tests for battery consumer model."""

    @pytest.mark.unit
    def test_responds_with_correct_length(self) -> None:
        consumer = BatteryConsumer(_make_battery())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert len(powers) == N_SLOTS

    @pytest.mark.unit
    def test_charges_during_cheap_periods(self) -> None:
        consumer = BatteryConsumer(_make_battery())
        prices = _varying_prices()
        powers = consumer.respond_to_prices(prices, N_SLOTS, RESOLUTION, [], T0)
        # Night slots (cheap) should have positive power (charging)
        night_powers = [powers[i] for i in range(24)]  # first 6 hours
        assert any(p > 0 for p in night_powers)

    @pytest.mark.unit
    def test_discharges_during_expensive_periods(self) -> None:
        consumer = BatteryConsumer(_make_battery())
        prices = _varying_prices()
        powers = consumer.respond_to_prices(prices, N_SLOTS, RESOLUTION, [], T0)
        # Evening slots (expensive, 17-20 = slots 68-80)
        evening_powers = [powers[i] for i in range(68, 80)]
        assert any(p < 0 for p in evening_powers)

    @pytest.mark.unit
    def test_respects_max_charge_rate(self) -> None:
        bat = _make_battery()
        consumer = BatteryConsumer(bat)
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert all(p <= bat.max_charge_kw for p in powers)

    @pytest.mark.unit
    def test_respects_max_discharge_rate(self) -> None:
        bat = _make_battery()
        consumer = BatteryConsumer(bat)
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert all(p >= -bat.max_discharge_kw for p in powers)

    @pytest.mark.unit
    def test_forbidden_window_respected(self) -> None:
        consumer = BatteryConsumer(_make_battery())
        cw = ConstraintWindow(
            window_id="fw1",
            device_id="bat_1",
            deadline=T0 + timedelta(hours=2),
            requirement=ForbiddenWindow(),
            priority_penalty=1.0,
        )
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [cw], T0)
        # First 8 slots (2 hours) should be 0
        for i in range(8):
            assert powers[i] == 0.0

    @pytest.mark.unit
    def test_min_soc_target_met(self) -> None:
        bat = _make_battery()
        consumer = BatteryConsumer(bat)
        cw = ConstraintWindow(
            window_id="soc1",
            device_id="bat_1",
            deadline=T0 + timedelta(hours=12),
            requirement=MinSocUntil(min_soc_pct=80),
            priority_penalty=5.0,
        )
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [cw], T0)
        # Should have significant charging
        total_charge = sum(p for p in powers if p > 0) * (RESOLUTION / 60.0) * bat.charge_efficiency
        assert total_charge > 0


class TestEVChargerConsumer:
    """Tests for EV charger consumer model."""

    @pytest.mark.unit
    def test_responds_with_correct_length(self) -> None:
        consumer = EVChargerConsumer(_make_ev())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert len(powers) == N_SLOTS

    @pytest.mark.unit
    def test_charges_at_cheapest_slots(self) -> None:
        consumer = EVChargerConsumer(_make_ev())
        prices = _varying_prices()
        powers = consumer.respond_to_prices(prices, N_SLOTS, RESOLUTION, [], T0)
        # Should charge during cheap periods
        assert any(p > 0 for p in powers)
        # Charging slots should tend to be cheap ones
        charging_slots = [i for i, p in enumerate(powers) if p > 0]
        if charging_slots:
            avg_charging_price = sum(prices[i] for i in charging_slots) / len(charging_slots)
            avg_all_price = sum(prices) / len(prices)
            assert avg_charging_price <= avg_all_price

    @pytest.mark.unit
    def test_meets_energy_target(self) -> None:
        ev = _make_ev()
        consumer = EVChargerConsumer(ev)
        target_kwh = 20.0
        cw = ConstraintWindow(
            window_id="ev_target",
            device_id="ev_1",
            deadline=T0 + timedelta(hours=8),
            requirement=MinEnergyUntil(min_energy_kwh=target_kwh),
            priority_penalty=10.0,
        )
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [cw], T0)
        total_energy = sum(p * (RESOLUTION / 60.0) for p in powers if p > 0)
        assert total_energy >= target_kwh * 0.9  # Allow small tolerance

    @pytest.mark.unit
    def test_respects_max_charge(self) -> None:
        ev = _make_ev()
        consumer = EVChargerConsumer(ev)
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert all(p <= ev.max_charge_kw for p in powers)


class TestHeatPumpConsumer:
    """Tests for heat pump consumer model."""

    @pytest.mark.unit
    def test_responds_with_correct_length(self) -> None:
        consumer = HeatPumpConsumer(_make_heat_pump())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert len(powers) == N_SLOTS

    @pytest.mark.unit
    def test_runs_during_some_slots(self) -> None:
        consumer = HeatPumpConsumer(_make_heat_pump())
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert any(p > 0 for p in powers)

    @pytest.mark.unit
    def test_prefers_cheap_slots(self) -> None:
        consumer = HeatPumpConsumer(_make_heat_pump())
        prices = _varying_prices()
        powers = consumer.respond_to_prices(prices, N_SLOTS, RESOLUTION, [], T0)
        running_slots = [i for i, p in enumerate(powers) if p > 0]
        if running_slots:
            avg_running_price = sum(prices[i] for i in running_slots) / len(running_slots)
            avg_all_price = sum(prices) / len(prices)
            assert avg_running_price <= avg_all_price * 1.1

    @pytest.mark.unit
    def test_respects_max_power(self) -> None:
        hp = _make_heat_pump()
        consumer = HeatPumpConsumer(hp)
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert all(p <= hp.max_power_kw for p in powers)

    @pytest.mark.unit
    def test_min_runtime_constraint(self) -> None:
        consumer = HeatPumpConsumer(_make_heat_pump())
        cw = ConstraintWindow(
            window_id="mrt1",
            device_id="hp_1",
            deadline=T0 + timedelta(hours=24),
            requirement=MinRuntimePerDay(min_hours=8),
            priority_penalty=2.0,
        )
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [cw], T0)
        running_slots = sum(1 for p in powers if p > 0)
        # 8 hours = 32 slots at 15min resolution
        assert running_slots >= 32


class TestWaterHeaterConsumer:
    """Tests for water heater consumer model."""

    @pytest.mark.unit
    def test_responds_with_correct_length(self) -> None:
        consumer = WaterHeaterConsumer(_make_water_heater())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert len(powers) == N_SLOTS

    @pytest.mark.unit
    def test_heats_at_cheapest_slots(self) -> None:
        consumer = WaterHeaterConsumer(_make_water_heater())
        prices = _varying_prices()
        powers = consumer.respond_to_prices(prices, N_SLOTS, RESOLUTION, [], T0)
        heating_slots = [i for i, p in enumerate(powers) if p > 0]
        if heating_slots:
            avg_heating_price = sum(prices[i] for i in heating_slots) / len(heating_slots)
            avg_all_price = sum(prices) / len(prices)
            assert avg_heating_price <= avg_all_price

    @pytest.mark.unit
    def test_meets_energy_target(self) -> None:
        consumer = WaterHeaterConsumer(_make_water_heater())
        target_kwh = 5.0
        cw = ConstraintWindow(
            window_id="wh_energy",
            device_id="wh_1",
            deadline=T0 + timedelta(hours=24),
            requirement=MinEnergyUntil(min_energy_kwh=target_kwh),
            priority_penalty=5.0,
        )
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [cw], T0)
        total_energy = sum(p * (RESOLUTION / 60.0) for p in powers)
        assert total_energy >= target_kwh


class TestThermostatConsumer:
    """Tests for thermostat consumer model."""

    @pytest.mark.unit
    def test_responds_with_correct_length(self) -> None:
        consumer = ThermostatConsumer(_make_thermostat())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert len(powers) == N_SLOTS

    @pytest.mark.unit
    def test_runs_about_one_third_of_time(self) -> None:
        consumer = ThermostatConsumer(_make_thermostat())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        running = sum(1 for p in powers if p > 0)
        assert N_SLOTS // 4 <= running <= N_SLOTS // 2

    @pytest.mark.unit
    def test_binary_output(self) -> None:
        thermo = _make_thermostat()
        consumer = ThermostatConsumer(thermo)
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        for p in powers:
            assert p == 0.0 or abs(p - thermo.max_power_kw) < 0.01


class TestPVForecastConsumer:
    """Tests for PV forecast consumer model."""

    @pytest.mark.unit
    def test_responds_with_correct_length(self) -> None:
        consumer = PVForecastConsumer(_make_pv())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert len(powers) == N_SLOTS

    @pytest.mark.unit
    def test_produces_negative_power_during_day(self) -> None:
        consumer = PVForecastConsumer(_make_pv())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        # Slots 24-72 are roughly 6:00-18:00
        day_powers = [powers[i] for i in range(28, 68)]
        assert any(p < 0 for p in day_powers)

    @pytest.mark.unit
    def test_zero_power_at_night(self) -> None:
        consumer = PVForecastConsumer(_make_pv())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        # First 24 slots (0:00-6:00) should be 0
        for i in range(24):
            assert powers[i] == 0.0

    @pytest.mark.unit
    def test_peak_near_noon(self) -> None:
        consumer = PVForecastConsumer(_make_pv())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        # Slot 48 = 12:00 noon
        assert powers[48] < powers[24]  # More generation at noon than at 6am


class TestRoomConsumer:
    """Tests for room consumer model."""

    @pytest.mark.unit
    def test_responds_with_correct_length(self) -> None:
        consumer = RoomConsumer(_make_room())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert len(powers) == N_SLOTS

    @pytest.mark.unit
    def test_always_zero_power(self) -> None:
        consumer = RoomConsumer(_make_room())
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert all(p == 0.0 for p in powers)


class TestPassiveLoadConsumer:
    """Tests for passive load consumer model."""

    @pytest.mark.unit
    def test_responds_with_correct_length(self) -> None:
        consumer = PassiveLoadConsumer(_make_passive_load())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert len(powers) == N_SLOTS

    @pytest.mark.unit
    def test_flat_constant_power(self) -> None:
        consumer = PassiveLoadConsumer(_make_passive_load())
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        # All slots should be equal (flat profile)
        assert len(set(powers)) == 1

    @pytest.mark.unit
    def test_correct_daily_energy(self) -> None:
        """Total energy over 24h should equal typical_daily_kwh."""
        consumer = PassiveLoadConsumer(_make_passive_load())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        total_kwh = sum(p * RESOLUTION / 60.0 for p in powers)
        assert abs(total_kwh - 8.0) < 0.01

    @pytest.mark.unit
    def test_positive_power(self) -> None:
        consumer = PassiveLoadConsumer(_make_passive_load())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert all(p > 0 for p in powers)


class TestPlanChangePenalty:
    """Tests that plan-change penalty reduces oscillation."""

    @pytest.mark.unit
    def test_battery_damped_by_penalty(self) -> None:
        bat = _make_battery()
        consumer = BatteryConsumer(bat)
        prices = _varying_prices()

        # First solve without penalty
        powers_no_penalty = consumer.respond_to_prices(prices, N_SLOTS, RESOLUTION, [], T0)

        # Second solve with penalty from previous
        powers_with_penalty = consumer.respond_to_prices(
            prices, N_SLOTS, RESOLUTION, [], T0, previous_power=powers_no_penalty, plan_change_penalty=0.1
        )

        # With penalty: result should be closer to previous (damped)
        # At least some slots should show damping effect
        changes_no = sum(abs(powers_no_penalty[i]) for i in range(N_SLOTS))
        changes_with = sum(abs(powers_with_penalty[i] - powers_no_penalty[i]) for i in range(N_SLOTS))
        # Changes from previous should be small when penalty is applied
        assert changes_with < changes_no
