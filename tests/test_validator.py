"""Tests for the manifest validator."""

from __future__ import annotations

import pytest

from hemm_core.manifest.validator import ValidationError, validate_manifest


@pytest.mark.req("001:FR-001", "001:FR-003")
class TestValidatorBasics:
    """Basic validator tests."""

    @pytest.mark.unit
    def test_missing_type(self) -> None:
        with pytest.raises(ValidationError, match="Missing required field 'type'"):
            validate_manifest({"device_id": "x", "name": "X"})

    @pytest.mark.unit
    def test_unknown_type(self) -> None:
        with pytest.raises(ValidationError, match="Unknown manifest type"):
            validate_manifest({"type": "flux_capacitor", "device_id": "x", "name": "X"})

    @pytest.mark.unit
    def test_missing_safe_default(self) -> None:
        with pytest.raises(ValidationError, match="safe_default"):
            validate_manifest(
                {
                    "type": "room",
                    "device_id": "r1",
                    "name": "Room",
                    "floor_area_m2": 20.0,
                }
            )

    @pytest.mark.unit
    def test_valid_room(self) -> None:
        manifest = validate_manifest(
            {
                "type": "room",
                "device_id": "r1",
                "name": "Room",
                "floor_area_m2": 20.0,
                "safe_default": {"script": "script.safe"},
            }
        )
        assert manifest.device_id == "r1"

    @pytest.mark.unit
    def test_valid_battery(self) -> None:
        manifest = validate_manifest(
            {
                "type": "battery",
                "device_id": "bat1",
                "name": "Battery",
                "capacity_kwh": 10.0,
                "max_charge_kw": 5.0,
                "max_discharge_kw": 5.0,
                "safe_default": {"script": "script.bat_safe"},
            }
        )
        assert manifest.device_id == "bat1"


@pytest.mark.req("001:FR-007")
class TestConstraintEndpointValidation:
    """Tests for constraint endpoint version validation."""

    @pytest.mark.unit
    def test_valid_endpoints(self) -> None:
        manifest = validate_manifest(
            {
                "type": "room",
                "device_id": "r1",
                "name": "Room",
                "floor_area_m2": 20.0,
                "constraint_endpoints": {"hold_temp_band": ">=1"},
                "safe_default": {"script": "script.safe"},
            }
        )
        assert "hold_temp_band" in manifest.constraint_endpoints

    @pytest.mark.unit
    def test_unknown_constraint_type(self) -> None:
        with pytest.raises(ValidationError, match="Unknown constraint type"):
            validate_manifest(
                {
                    "type": "room",
                    "device_id": "r1",
                    "name": "Room",
                    "floor_area_m2": 20.0,
                    "constraint_endpoints": {"time_travel": ">=1"},
                    "safe_default": {"script": "script.safe"},
                }
            )

    @pytest.mark.unit
    def test_invalid_version_specifier(self) -> None:
        with pytest.raises(ValidationError, match="Invalid version specifier"):
            validate_manifest(
                {
                    "type": "room",
                    "device_id": "r1",
                    "name": "Room",
                    "floor_area_m2": 20.0,
                    "constraint_endpoints": {"hold_temp_band": "abc"},
                    "safe_default": {"script": "script.safe"},
                }
            )

    @pytest.mark.unit
    def test_unsatisfied_version(self) -> None:
        """Requesting a version that doesn't exist yet should fail."""
        with pytest.raises(ValidationError, match="requires version"):
            validate_manifest(
                {
                    "type": "room",
                    "device_id": "r1",
                    "name": "Room",
                    "floor_area_m2": 20.0,
                    "constraint_endpoints": {"hold_temp_band": ">=99"},
                    "safe_default": {"script": "script.safe"},
                }
            )


@pytest.mark.req("001:FR-012")
class TestValidatorErrorMessages:
    """Tests that error messages are clear and actionable."""

    @pytest.mark.unit
    def test_multiple_errors_reported(self) -> None:
        """Multiple constraint endpoint errors should all be reported."""
        with pytest.raises(ValidationError) as exc_info:
            validate_manifest(
                {
                    "type": "room",
                    "device_id": "r1",
                    "name": "Room",
                    "floor_area_m2": 20.0,
                    "constraint_endpoints": {
                        "unknown_one": ">=1",
                        "unknown_two": ">=1",
                    },
                    "safe_default": {"script": "script.safe"},
                }
            )
        assert len(exc_info.value.errors) == 2

    @pytest.mark.unit
    def test_pydantic_errors_formatted_clearly(self) -> None:
        """Pydantic validation errors should be reformatted as clear messages."""
        with pytest.raises(ValidationError) as exc_info:
            validate_manifest(
                {
                    "type": "battery",
                    "device_id": "bat1",
                    "name": "Battery",
                    "capacity_kwh": -5,  # invalid
                    "max_charge_kw": 5.0,
                    "max_discharge_kw": 5.0,
                    "safe_default": {"script": "script.bat_safe"},
                }
            )
        assert any("capacity_kwh" in e for e in exc_info.value.errors)
