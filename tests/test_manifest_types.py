"""Tests for device manifest types — round-trip JSON serialization and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError as PydanticValidationError

from hemm_core.manifest.types import (
    Action,
    BatteryManifest,
    ControlClass,
    DeviceRole,
    EVChargerManifest,
    HeatPumpManifest,
    ManifestType,
    PassiveLoadManifest,
    RetryPolicy,
    RoomManifest,
    VerificationContract,
)

TESTDATA_DIR = Path(__file__).parent.parent / "testdata" / "manifests" / "simple_house"


def _make_safe_default() -> Action:
    """Create a minimal safe_default action for testing."""
    return Action(script="script.test_safe_default", description="Test safe default")


class TestManifestTypeEnum:
    """Tests for ManifestType enum."""

    @pytest.mark.unit
    def test_eight_types(self) -> None:
        assert len(ManifestType) == 8

    @pytest.mark.unit
    @pytest.mark.req("001:FR-001")
    def test_values(self) -> None:
        expected = {
            "room",
            "thermostat_load",
            "heat_pump",
            "water_heater",
            "battery",
            "pv_forecast",
            "ev_charger",
            "passive_load",
        }
        assert {t.value for t in ManifestType} == expected


class TestDeviceRole:
    """Tests for DeviceRole enum and ManifestType.role property."""

    @pytest.mark.unit
    def test_five_roles(self) -> None:
        assert len(DeviceRole) == 5

    @pytest.mark.unit
    def test_role_values(self) -> None:
        expected = {"generator", "adjustable_sink", "passive_sink", "storage", "thermal_zone"}
        assert {r.value for r in DeviceRole} == expected

    @pytest.mark.unit
    def test_every_manifest_type_has_role(self) -> None:
        for mt in ManifestType:
            assert isinstance(mt.role, DeviceRole)

    @pytest.mark.unit
    def test_role_mapping(self) -> None:
        assert ManifestType.ROOM.role == DeviceRole.THERMAL_ZONE
        assert ManifestType.THERMOSTAT_LOAD.role == DeviceRole.ADJUSTABLE_SINK
        assert ManifestType.HEAT_PUMP.role == DeviceRole.ADJUSTABLE_SINK
        assert ManifestType.WATER_HEATER.role == DeviceRole.ADJUSTABLE_SINK
        assert ManifestType.BATTERY.role == DeviceRole.STORAGE
        assert ManifestType.PV_FORECAST.role == DeviceRole.GENERATOR
        assert ManifestType.EV_CHARGER.role == DeviceRole.ADJUSTABLE_SINK
        assert ManifestType.PASSIVE_LOAD.role == DeviceRole.PASSIVE_SINK


class TestAction:
    """Tests for Action model."""

    @pytest.mark.unit
    def test_minimal(self) -> None:
        a = Action(script="script.do_thing")
        assert a.script == "script.do_thing"
        assert a.timeout_seconds == 300
        assert a.retry.max_attempts == 2
        assert a.retry.backoff_seconds == 60

    @pytest.mark.unit
    @pytest.mark.req("001:FR-008")
    def test_with_verify(self) -> None:
        a = Action(
            script="script.heat_on",
            verify=VerificationContract(entity="sensor.temp", expected=">= 60", within_seconds=300),
        )
        assert a.verify is not None
        assert a.verify.entity == "sensor.temp"


class TestRetryPolicy:
    """Tests for RetryPolicy model."""

    @pytest.mark.unit
    def test_defaults(self) -> None:
        r = RetryPolicy()
        assert r.max_attempts == 2
        assert r.backoff_seconds == 60

    @pytest.mark.unit
    def test_invalid_attempts(self) -> None:
        with pytest.raises(PydanticValidationError):
            RetryPolicy(max_attempts=0)


class TestRoomManifest:
    """Tests for Room manifest type."""

    @pytest.mark.unit
    def test_minimal(self) -> None:
        m = RoomManifest(
            device_id="room1",
            name="Test Room",
            floor_area_m2=20.0,
            safe_default=_make_safe_default(),
        )
        assert m.type == ManifestType.ROOM
        assert m.floor_area_m2 == 20.0

    @pytest.mark.unit
    def test_full(self) -> None:
        m = RoomManifest(
            device_id="room1",
            name="Living Room",
            floor_area_m2=35.0,
            thermal_mass_kwh_per_k=2.5,
            u_value_w_per_m2k=0.35,
            window_area_m2=8.0,
            south_facing_windows=True,
            insulation_class="good",
            constraint_endpoints={"hold_temp_band": ">=1"},
            safe_default=_make_safe_default(),
        )
        assert m.south_facing_windows is True
        assert "hold_temp_band" in m.constraint_endpoints

    @pytest.mark.unit
    def test_invalid_area(self) -> None:
        with pytest.raises(PydanticValidationError):
            RoomManifest(device_id="r", name="R", floor_area_m2=-1, safe_default=_make_safe_default())

    @pytest.mark.unit
    @settings(max_examples=100)
    @given(area=st.floats(min_value=1.0, max_value=500.0, allow_nan=False))
    def test_area_property(self, area: float) -> None:
        m = RoomManifest(device_id="r", name="R", floor_area_m2=area, safe_default=_make_safe_default())
        assert m.floor_area_m2 == area


class TestHeatPumpManifest:
    """Tests for HeatPump manifest type."""

    @pytest.mark.unit
    def test_minimal(self) -> None:
        m = HeatPumpManifest(device_id="hp1", name="HP", max_power_kw=5.0, safe_default=_make_safe_default())
        assert m.type == ManifestType.HEAT_PUMP
        assert m.max_power_kw == 5.0

    @pytest.mark.unit
    def test_with_cop_map(self) -> None:
        m = HeatPumpManifest(
            device_id="hp1",
            name="HP",
            max_power_kw=5.0,
            cop_map=[(-10, 2.5), (0, 3.5), (10, 4.5)],
            safe_default=_make_safe_default(),
        )
        assert m.cop_map is not None
        assert len(m.cop_map) == 3


class TestBatteryManifest:
    """Tests for Battery manifest type."""

    @pytest.mark.unit
    def test_valid(self) -> None:
        m = BatteryManifest(
            device_id="bat1",
            name="Battery",
            capacity_kwh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            safe_default=_make_safe_default(),
        )
        assert m.type == ManifestType.BATTERY
        assert m.charge_efficiency == 0.95

    @pytest.mark.unit
    def test_invalid_efficiency(self) -> None:
        with pytest.raises(PydanticValidationError):
            BatteryManifest(
                device_id="b",
                name="B",
                capacity_kwh=10,
                max_charge_kw=5,
                max_discharge_kw=5,
                charge_efficiency=1.5,
                safe_default=_make_safe_default(),
            )

    @pytest.mark.unit
    @settings(max_examples=100)
    @given(
        capacity=st.floats(min_value=0.1, max_value=200.0, allow_nan=False),
        efficiency=st.floats(min_value=0.01, max_value=1.0, allow_nan=False),
    )
    def test_battery_property(self, capacity: float, efficiency: float) -> None:
        m = BatteryManifest(
            device_id="b",
            name="B",
            capacity_kwh=capacity,
            max_charge_kw=capacity / 2,
            max_discharge_kw=capacity / 2,
            charge_efficiency=efficiency,
            discharge_efficiency=efficiency,
            safe_default=_make_safe_default(),
        )
        assert m.capacity_kwh == capacity
        assert 0 < m.charge_efficiency <= 1


class TestEVChargerManifest:
    """Tests for EVCharger manifest type."""

    @pytest.mark.unit
    def test_valid(self) -> None:
        m = EVChargerManifest(
            device_id="ev1",
            name="EV",
            max_charge_kw=11.0,
            safe_default=_make_safe_default(),
        )
        assert m.type == ManifestType.EV_CHARGER
        assert m.phases == 3


class TestPassiveLoadManifest:
    """Tests for PassiveLoad manifest type."""

    @pytest.mark.unit
    def test_minimal(self) -> None:
        m = PassiveLoadManifest(
            device_id="base1",
            name="Kitchen",
            typical_daily_kwh=8.0,
            safe_default=_make_safe_default(),
        )
        assert m.type == ManifestType.PASSIVE_LOAD
        assert m.typical_daily_kwh == 8.0
        assert m.load_profile_entity is None

    @pytest.mark.unit
    def test_with_entity(self) -> None:
        m = PassiveLoadManifest(
            device_id="base1",
            name="Kitchen",
            typical_daily_kwh=8.0,
            load_profile_entity="sensor.kitchen_power",
            safe_default=_make_safe_default(),
        )
        assert m.load_profile_entity == "sensor.kitchen_power"

    @pytest.mark.unit
    def test_invalid_zero_kwh(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            PassiveLoadManifest(
                device_id="b",
                name="B",
                typical_daily_kwh=0.0,
                safe_default=_make_safe_default(),
            )

    @pytest.mark.unit
    def test_roundtrip(self) -> None:
        original = PassiveLoadManifest(
            device_id="base1",
            name="Base Load",
            typical_daily_kwh=12.0,
            load_profile_entity="sensor.base_load",
            safe_default=_make_safe_default(),
        )
        restored = PassiveLoadManifest.model_validate_json(original.model_dump_json())
        assert restored == original


class TestHeatPumpSourceSink:
    """Tests for heat pump source_type/sink_type fields."""

    @pytest.mark.unit
    def test_defaults(self) -> None:
        m = HeatPumpManifest(device_id="hp1", name="HP", max_power_kw=5.0, safe_default=_make_safe_default())
        assert m.source_type == "air"
        assert m.sink_type == "water"

    @pytest.mark.unit
    def test_ground_source(self) -> None:
        m = HeatPumpManifest(
            device_id="hp1",
            name="HP",
            max_power_kw=8.0,
            source_type="ground",
            sink_type="water",
            safe_default=_make_safe_default(),
        )
        assert m.source_type == "ground"

    @pytest.mark.unit
    def test_air_to_air(self) -> None:
        m = HeatPumpManifest(
            device_id="hp1",
            name="HP",
            max_power_kw=3.0,
            source_type="air",
            sink_type="air",
            safe_default=_make_safe_default(),
        )
        assert m.sink_type == "air"

    @pytest.mark.unit
    def test_invalid_source_type(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            HeatPumpManifest(
                device_id="hp1",
                name="HP",
                max_power_kw=5.0,
                source_type="fire",
                safe_default=_make_safe_default(),
            )


class TestPVSourceKind:
    """Tests for PV forecast source_kind field."""

    @pytest.mark.unit
    def test_default_is_pv(self) -> None:
        from hemm_core.manifest.types import PVForecastManifest

        m = PVForecastManifest(
            device_id="pv1",
            name="PV",
            peak_power_kwp=10.0,
            safe_default=_make_safe_default(),
        )
        assert m.source_kind == "pv"

    @pytest.mark.unit
    def test_wind(self) -> None:
        from hemm_core.manifest.types import PVForecastManifest

        m = PVForecastManifest(
            device_id="wind1",
            name="Wind",
            peak_power_kwp=5.0,
            source_kind="wind",
            azimuth_deg=None,
            tilt_deg=None,
            safe_default=_make_safe_default(),
        )
        assert m.source_kind == "wind"
        assert m.azimuth_deg is None

    @pytest.mark.unit
    def test_chp(self) -> None:
        from hemm_core.manifest.types import PVForecastManifest

        m = PVForecastManifest(
            device_id="chp1",
            name="CHP",
            peak_power_kwp=2.0,
            source_kind="chp",
            azimuth_deg=None,
            tilt_deg=None,
            safe_default=_make_safe_default(),
        )
        assert m.source_kind == "chp"

    @pytest.mark.unit
    def test_invalid_source_kind(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        from hemm_core.manifest.types import PVForecastManifest

        with pytest.raises(PydanticValidationError):
            PVForecastManifest(
                device_id="x",
                name="X",
                peak_power_kwp=1.0,
                source_kind="nuclear",
                safe_default=_make_safe_default(),
            )


class TestSafeDefaultMandatory:
    """Tests that safe_default is enforced as mandatory."""

    @pytest.mark.unit
    @pytest.mark.req("001:FR-002")
    def test_missing_safe_default_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            RoomManifest(device_id="r", name="R", floor_area_m2=20.0)  # type: ignore[call-arg]

    @pytest.mark.unit
    @pytest.mark.req("001:FR-002")
    def test_empty_script_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            RoomManifest(
                device_id="r",
                name="R",
                floor_area_m2=20.0,
                safe_default=Action(script=""),
            )


class TestJsonRoundTrip:
    """Tests for JSON serialization round-trips."""

    @pytest.mark.unit
    def test_room_roundtrip(self) -> None:
        original = RoomManifest(
            device_id="room1",
            name="Test Room",
            floor_area_m2=25.0,
            constraint_endpoints={"hold_temp_band": ">=1"},
            safe_default=_make_safe_default(),
        )
        json_str = original.model_dump_json()
        restored = RoomManifest.model_validate_json(json_str)
        assert restored == original

    @pytest.mark.unit
    def test_battery_roundtrip(self) -> None:
        original = BatteryManifest(
            device_id="bat1",
            name="Battery",
            capacity_kwh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            safe_default=_make_safe_default(),
        )
        json_str = original.model_dump_json()
        restored = BatteryManifest.model_validate_json(json_str)
        assert restored == original


class TestControlClass:
    """Tests for control_class field on manifests."""

    @pytest.mark.unit
    def test_control_class_default_is_planned(self) -> None:
        """Manifest without explicit control_class defaults to 'planned'."""
        m = BatteryManifest(
            device_id="bat1",
            name="Battery",
            capacity_kwh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            safe_default=_make_safe_default(),
        )
        assert m.control_class == ControlClass.PLANNED

    @pytest.mark.unit
    def test_control_class_enum_validation(self) -> None:
        """Invalid control_class value raises ValidationError."""
        with pytest.raises(PydanticValidationError):
            BatteryManifest(
                device_id="bat1",
                name="Battery",
                capacity_kwh=10.0,
                max_charge_kw=5.0,
                max_discharge_kw=5.0,
                control_class="invalid_class",
                safe_default=_make_safe_default(),
            )

    @pytest.mark.unit
    def test_control_class_passive(self) -> None:
        """control_class can be set to 'passive'."""
        m = RoomManifest(
            device_id="room1",
            name="Kitchen",
            floor_area_m2=15.0,
            control_class="passive",
            safe_default=_make_safe_default(),
        )
        assert m.control_class == ControlClass.PASSIVE

    @pytest.mark.unit
    def test_control_class_reactive(self) -> None:
        """control_class can be set to 'reactive'."""
        m = EVChargerManifest(
            device_id="ev1",
            name="Wallbox",
            max_charge_kw=11.0,
            control_class="reactive",
            safe_default=_make_safe_default(),
        )
        assert m.control_class == ControlClass.REACTIVE

    @pytest.mark.unit
    def test_control_class_in_all_device_types(self) -> None:
        """Every device type accepts control_class field."""
        from hemm_core.manifest.types import (
            PVForecastManifest,
            ThermostatLoadManifest,
            WaterHeaterManifest,
        )

        manifests = [
            RoomManifest(device_id="r", name="R", floor_area_m2=20.0, safe_default=_make_safe_default()),
            ThermostatLoadManifest(device_id="t", name="T", max_power_kw=2.0, safe_default=_make_safe_default()),
            HeatPumpManifest(device_id="h", name="H", max_power_kw=5.0, safe_default=_make_safe_default()),
            WaterHeaterManifest(
                device_id="w", name="W", volume_liters=200, max_power_kw=3.0, safe_default=_make_safe_default()
            ),
            BatteryManifest(
                device_id="b",
                name="B",
                capacity_kwh=10,
                max_charge_kw=5,
                max_discharge_kw=5,
                safe_default=_make_safe_default(),
            ),
            PVForecastManifest(device_id="p", name="P", peak_power_kwp=10.0, safe_default=_make_safe_default()),
            EVChargerManifest(device_id="e", name="E", max_charge_kw=11.0, safe_default=_make_safe_default()),
            PassiveLoadManifest(device_id="pl", name="PL", typical_daily_kwh=8.0, safe_default=_make_safe_default()),
        ]
        for m in manifests:
            assert m.control_class == ControlClass.PLANNED

    @pytest.mark.unit
    def test_envelope_tolerance_default(self) -> None:
        """Default envelope_tolerance_pct is 15.0."""
        m = BatteryManifest(
            device_id="bat1",
            name="Battery",
            capacity_kwh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            safe_default=_make_safe_default(),
        )
        assert m.envelope_tolerance_pct == 15.0

    @pytest.mark.unit
    def test_control_class_roundtrip_json(self) -> None:
        """control_class survives JSON serialization."""
        m = EVChargerManifest(
            device_id="ev1",
            name="Wallbox",
            max_charge_kw=11.0,
            control_class="reactive",
            safe_default=_make_safe_default(),
        )
        restored = EVChargerManifest.model_validate_json(m.model_dump_json())
        assert restored.control_class == ControlClass.REACTIVE

    @pytest.mark.unit
    def test_ev_charger_roundtrip(self) -> None:
        original = EVChargerManifest(
            device_id="ev1",
            name="EV",
            max_charge_kw=11.0,
            battery_capacity_kwh=77.0,
            safe_default=_make_safe_default(),
        )
        json_str = original.model_dump_json()
        restored = EVChargerManifest.model_validate_json(json_str)
        assert restored == original


class TestTestdataManifests:
    """Tests that all testdata manifests load and validate."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "filename",
        [
            "room_living.json",
            "heat_pump.json",
            "water_heater.json",
            "battery.json",
            "pv_forecast.json",
            "ev_charger.json",
            "thermostat_load.json",
            "passive_load.json",
        ],
    )
    def test_simple_house_manifest_valid(self, filename: str) -> None:
        """Every manifest in testdata/manifests/simple_house/ must validate."""
        from hemm_core.manifest.validator import validate_manifest

        filepath = TESTDATA_DIR / filename
        assert filepath.exists(), f"Missing testdata file: {filepath}"
        data: dict[str, Any] = json.loads(filepath.read_text(encoding="utf-8"))
        manifest = validate_manifest(data)
        assert manifest.device_id
        assert manifest.safe_default.script

    @pytest.mark.unit
    def test_all_eight_types_covered(self) -> None:
        """The simple house set must cover all 8 manifest types."""
        types_seen: set[str] = set()
        for filepath in TESTDATA_DIR.glob("*.json"):
            data: dict[str, Any] = json.loads(filepath.read_text(encoding="utf-8"))
            types_seen.add(data["type"])
        assert types_seen == {t.value for t in ManifestType}
