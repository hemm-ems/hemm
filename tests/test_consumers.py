"""Tests for primitive consumer models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from hemm_core.manifest.components import ConverterSpec, NodeSpec, SinkSpec, SourceSpec, StorageSpec
from hemm_core.manifest.constraints import ForbiddenWindow, MinEnergyUntil, MinRuntimePerDay, MinSocUntil
from hemm_core.manifest.messages import ConstraintWindow
from hemm_core.manifest.types import (
    BatteryManifest,
    EVChargerManifest,
    HeatPumpManifest,
    PassiveLoadManifest,
    PVForecastManifest,
    RoomManifest,
    ThermostatLoadManifest,
    WaterHeaterManifest,
)
from hemm_core.solvers.consumers import (
    ConverterConsumer,
    NodeConsumer,
    SinkConsumer,
    SourceConsumer,
    StorageConsumer,
    get_consumer_model,
)

T0 = datetime(2026, 5, 6, 0, 0, tzinfo=UTC)
N_SLOTS = 96
RESOLUTION = 15


def _safe_default() -> dict[str, str]:
    return {"script": "script.safe"}


def _flat_prices(n: int = N_SLOTS, price: float = 0.30) -> list[float]:
    return [price] * n


def _varying_prices(n: int = N_SLOTS) -> list[float]:
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


def _manifest_stub() -> SimpleNamespace:
    return SimpleNamespace(device_id="primitive_1", type="primitive")


def _make_storage(*, charge_only: bool = False) -> StorageSpec:
    return StorageSpec(
        device_id="primitive_1",
        capacity=10.0,
        max_charge_kw=5.0,
        max_discharge_kw=0.0 if charge_only else 5.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        min_level=1.0,
        max_level=9.0,
        charge_only=charge_only,
    )


def _make_converter() -> ConverterSpec:
    return ConverterSpec(
        device_id="primitive_1",
        input_bus="elec",
        output_bus="thermal:primitive_1",
        max_input_kw=4.0,
        factor_map=[(-10.0, 2.0), (10.0, 4.0)],
        factor_ctx="outdoor_temp",
    )


def _make_sink(*, controllable: bool = True) -> SinkSpec:
    return SinkSpec(
        device_id="primitive_1",
        min_power_kw=0.0,
        max_power_kw=1.2,
        controllable=controllable,
    )


class TestGetConsumerModel:
    """Tests for the manifest-to-primitive compile entry."""

    @pytest.mark.unit
    def test_storage_manifest_returns_storage_consumer(self) -> None:
        manifest = BatteryManifest(
            device_id="bat_1",
            name="Storage",
            capacity_kwh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            safe_default=_safe_default(),
        )
        assert isinstance(get_consumer_model(manifest), StorageConsumer)

    @pytest.mark.unit
    def test_charge_only_manifest_returns_storage_consumer(self) -> None:
        manifest = EVChargerManifest(
            device_id="ev_1",
            name="Charge Only",
            max_charge_kw=11.0,
            battery_capacity_kwh=60.0,
            safe_default=_safe_default(),
        )
        assert isinstance(get_consumer_model(manifest), StorageConsumer)

    @pytest.mark.unit
    def test_converter_manifest_returns_converter_consumer(self) -> None:
        manifest = HeatPumpManifest(
            device_id="conv_1",
            name="Converter",
            max_power_kw=5.0,
            room_id="node_1",
            safe_default=_safe_default(),
        )
        assert isinstance(get_consumer_model(manifest), ConverterConsumer)

    @pytest.mark.unit
    def test_multi_component_manifest_returns_electrical_consumer(self) -> None:
        manifest = WaterHeaterManifest(
            device_id="multi_1",
            name="Multi Component",
            volume_liters=200,
            max_power_kw=3.0,
            safe_default=_safe_default(),
        )
        assert isinstance(get_consumer_model(manifest), ConverterConsumer)

    @pytest.mark.unit
    def test_sink_manifests_return_sink_consumer(self) -> None:
        assert isinstance(
            get_consumer_model(
                ThermostatLoadManifest(
                    device_id="sink_1",
                    name="Sink",
                    max_power_kw=2.0,
                    safe_default=_safe_default(),
                )
            ),
            SinkConsumer,
        )
        assert isinstance(
            get_consumer_model(
                PassiveLoadManifest(
                    device_id="fixed_1",
                    name="Fixed Sink",
                    typical_daily_kwh=8.0,
                    safe_default=_safe_default(),
                )
            ),
            SinkConsumer,
        )

    @pytest.mark.unit
    def test_source_and_node_manifests_return_primitive_consumers(self) -> None:
        assert isinstance(
            get_consumer_model(
                PVForecastManifest(
                    device_id="source_1",
                    name="Source",
                    peak_power_kwp=8.0,
                    safe_default=_safe_default(),
                )
            ),
            SourceConsumer,
        )
        assert isinstance(
            get_consumer_model(
                RoomManifest(
                    device_id="node_1",
                    name="Node",
                    floor_area_m2=25.0,
                    safe_default=_safe_default(),
                )
            ),
            NodeConsumer,
        )


class TestStorageConsumer:
    """Tests for storage response."""

    @pytest.mark.unit
    def test_responds_with_correct_length(self) -> None:
        consumer = StorageConsumer(_manifest_stub(), _make_storage())
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert len(powers) == N_SLOTS

    @pytest.mark.unit
    def test_charges_during_cheap_periods(self) -> None:
        consumer = StorageConsumer(_manifest_stub(), _make_storage())
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert any(p > 0 for p in powers[:24])

    @pytest.mark.unit
    def test_discharges_during_expensive_periods(self) -> None:
        consumer = StorageConsumer(_manifest_stub(), _make_storage())
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert any(p < 0 for p in powers[68:80])

    @pytest.mark.unit
    def test_respects_power_limits(self) -> None:
        storage = _make_storage()
        consumer = StorageConsumer(_manifest_stub(), storage)
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert all(p <= (storage.max_charge_kw or 0.0) for p in powers)
        assert all(p >= -storage.max_discharge_kw for p in powers)

    @pytest.mark.unit
    def test_forbidden_window_respected(self) -> None:
        consumer = StorageConsumer(_manifest_stub(), _make_storage())
        cw = ConstraintWindow(
            window_id="fw1",
            device_id="primitive_1",
            deadline=T0 + timedelta(hours=2),
            requirement=ForbiddenWindow(),
            priority_penalty=1.0,
        )
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [cw], T0)
        assert all(p == 0.0 for p in powers[:8])

    @pytest.mark.unit
    def test_min_soc_target_met_by_deadline(self) -> None:
        storage = _make_storage(charge_only=True)
        consumer = StorageConsumer(_manifest_stub(), storage)
        cw = ConstraintWindow(
            window_id="soc1",
            device_id="primitive_1",
            deadline=T0 + timedelta(hours=12),
            requirement=MinSocUntil(min_soc_pct=80),
            priority_penalty=5.0,
        )
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [cw], T0)
        assert all(p >= 0 for p in powers), "charge_only device must never discharge"
        charged = sum(p for p in powers[:49] if p > 0) * (RESOLUTION / 60.0) * storage.charge_efficiency
        assert charged >= 3.0

    @pytest.mark.unit
    def test_charge_only_storage_meets_energy_target(self) -> None:
        storage = _make_storage(charge_only=True)
        consumer = StorageConsumer(_manifest_stub(), storage)
        target_kwh = 8.0
        cw = ConstraintWindow(
            window_id="target",
            device_id="primitive_1",
            deadline=T0 + timedelta(hours=8),
            requirement=MinEnergyUntil(min_energy_kwh=target_kwh),
            priority_penalty=10.0,
        )
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [cw], T0)
        assert all(p >= 0 for p in powers), "charge_only device must never discharge"
        delivered = sum(p * (RESOLUTION / 60.0) for p in powers if p > 0)
        assert delivered >= target_kwh * 0.99


class TestConverterConsumer:
    """Tests for converter response."""

    @pytest.mark.unit
    def test_no_target_returns_zero(self) -> None:
        consumer = ConverterConsumer(_manifest_stub(), _make_converter(), outdoor_temp_c=10.0)
        powers = consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert powers == [0.0] * N_SLOTS

    @pytest.mark.unit
    def test_prefers_cheapest_slots_for_runtime(self) -> None:
        consumer = ConverterConsumer(_manifest_stub(), _make_converter(), outdoor_temp_c=10.0)
        cw = ConstraintWindow(
            window_id="runtime",
            device_id="primitive_1",
            deadline=T0 + timedelta(hours=24),
            requirement=MinRuntimePerDay(min_hours=4),
            priority_penalty=2.0,
        )
        prices = _varying_prices()
        powers = consumer.respond_to_prices(prices, N_SLOTS, RESOLUTION, [cw], T0)
        running_slots = [i for i, p in enumerate(powers) if p > 0]
        assert len(running_slots) >= 16
        assert sum(prices[i] for i in running_slots) / len(running_slots) <= sum(prices) / len(prices)

    @pytest.mark.unit
    def test_respects_max_input_power(self) -> None:
        converter = _make_converter()
        consumer = ConverterConsumer(_manifest_stub(), converter, outdoor_temp_c=10.0)
        cw = ConstraintWindow(
            window_id="runtime",
            device_id="primitive_1",
            deadline=T0 + timedelta(hours=24),
            requirement=MinRuntimePerDay(min_hours=2),
            priority_penalty=2.0,
        )
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [cw], T0)
        assert all(p <= converter.max_input_kw for p in powers)

    @pytest.mark.unit
    def test_storage_leakage_sets_energy_target(self) -> None:
        converter = ConverterSpec(
            device_id="primitive_1",
            output_bus="thermal:primitive_1",
            max_input_kw=3.0,
            factor_map=[(0.0, 1.0)],
            factor_ctx="none",
        )
        storage = StorageSpec(device_id="primitive_1", node="thermal:primitive_1", capacity=1.0, leakage=0.05)
        consumer = ConverterConsumer(_manifest_stub(), converter, storage=storage)
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        delivered = sum(p * RESOLUTION / 60.0 for p in powers)
        assert delivered >= 1.19


class TestSinkConsumer:
    """Tests for sink response."""

    @pytest.mark.unit
    def test_controllable_sink_is_idle_without_target(self) -> None:
        consumer = SinkConsumer(_manifest_stub(), _make_sink(controllable=True))
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert powers == [0.0] * N_SLOTS

    @pytest.mark.unit
    def test_controllable_sink_picks_cheapest_slots(self) -> None:
        sink = _make_sink(controllable=True)
        consumer = SinkConsumer(_manifest_stub(), sink)
        cw = ConstraintWindow(
            window_id="energy",
            device_id="primitive_1",
            deadline=T0 + timedelta(hours=24),
            requirement=MinEnergyUntil(min_energy_kwh=2.4),
            priority_penalty=3.0,
        )
        prices = _varying_prices()
        powers = consumer.respond_to_prices(prices, N_SLOTS, RESOLUTION, [cw], T0)
        active = [i for i, p in enumerate(powers) if p > 0]
        assert active
        assert sum(prices[i] for i in active) / len(active) <= sum(prices) / len(prices)
        assert sum(p * RESOLUTION / 60.0 for p in powers) >= 2.4
        assert all(p <= sink.max_power_kw for p in powers)

    @pytest.mark.unit
    def test_non_controllable_sink_is_flat(self) -> None:
        sink = _make_sink(controllable=False)
        consumer = SinkConsumer(_manifest_stub(), sink)
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert powers == [sink.max_power_kw] * N_SLOTS


class TestSourceConsumer:
    """Tests for source response."""

    @pytest.mark.unit
    def test_forecast_emits_negative_power(self) -> None:
        source = SourceSpec(device_id="primitive_1", forecast=[0.0, 1.5, 2.0])
        consumer = SourceConsumer(_manifest_stub(), source)
        assert consumer.respond_to_prices(_flat_prices(4), 4, RESOLUTION, [], T0) == [0.0, -1.5, -2.0, -2.0]

    @pytest.mark.unit
    def test_missing_forecast_is_zero(self) -> None:
        source = SourceSpec(device_id="primitive_1", forecast=None)
        consumer = SourceConsumer(_manifest_stub(), source)
        assert consumer.respond_to_prices(_flat_prices(), N_SLOTS, RESOLUTION, [], T0) == [0.0] * N_SLOTS


class TestNodeConsumer:
    """Tests for node response."""

    @pytest.mark.unit
    def test_always_zero_power(self) -> None:
        node = NodeSpec(device_id="primitive_1", bus="thermal:primitive_1")
        consumer = NodeConsumer(_manifest_stub(), node)
        powers = consumer.respond_to_prices(_varying_prices(), N_SLOTS, RESOLUTION, [], T0)
        assert len(powers) == N_SLOTS
        assert all(p == 0.0 for p in powers)


class TestPlanChangePenalty:
    """Tests that plan-change penalty dampens changes."""

    @pytest.mark.unit
    def test_storage_damped_by_penalty(self) -> None:
        consumer = StorageConsumer(_manifest_stub(), _make_storage())
        prices = _varying_prices()
        powers_no_penalty = consumer.respond_to_prices(prices, N_SLOTS, RESOLUTION, [], T0)
        powers_with_penalty = consumer.respond_to_prices(
            prices,
            N_SLOTS,
            RESOLUTION,
            [],
            T0,
            previous_power=powers_no_penalty,
            plan_change_penalty=0.1,
        )
        changes_no = sum(abs(p) for p in powers_no_penalty)
        changes_with = sum(abs(powers_with_penalty[i] - powers_no_penalty[i]) for i in range(N_SLOTS))
        assert changes_with < changes_no
