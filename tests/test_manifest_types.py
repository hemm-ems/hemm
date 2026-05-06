"""Tests for device manifest types — round-trip JSON serialization and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError as PydanticValidationError

from hemm.manifest.types import (
    Action,
    BatteryManifest,
    EVChargerManifest,
    HeatPumpManifest,
    ManifestType,
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
    def test_seven_types(self) -> None:
        assert len(ManifestType) == 7

    @pytest.mark.unit
    def test_values(self) -> None:
        expected = {"room", "thermostat_load", "heat_pump", "water_heater", "battery", "pv_forecast", "ev_charger"}
        assert {t.value for t in ManifestType} == expected


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


class TestSafeDefaultMandatory:
    """Tests that safe_default is enforced as mandatory."""

    @pytest.mark.unit
    def test_missing_safe_default_raises(self) -> None:
        with pytest.raises(PydanticValidationError):
            RoomManifest(device_id="r", name="R", floor_area_m2=20.0)  # type: ignore[call-arg]

    @pytest.mark.unit
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
        ],
    )
    def test_simple_house_manifest_valid(self, filename: str) -> None:
        """Every manifest in testdata/manifests/simple_house/ must validate."""
        from hemm.manifest.validator import validate_manifest

        filepath = TESTDATA_DIR / filename
        assert filepath.exists(), f"Missing testdata file: {filepath}"
        data: dict[str, Any] = json.loads(filepath.read_text(encoding="utf-8"))
        manifest = validate_manifest(data)
        assert manifest.device_id
        assert manifest.safe_default.script

    @pytest.mark.unit
    def test_all_seven_types_covered(self) -> None:
        """The simple house set must cover all 7 manifest types."""
        types_seen: set[str] = set()
        for filepath in TESTDATA_DIR.glob("*.json"):
            data: dict[str, Any] = json.loads(filepath.read_text(encoding="utf-8"))
            types_seen.add(data["type"])
        assert types_seen == {t.value for t in ManifestType}
