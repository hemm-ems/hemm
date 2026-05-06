"""Manifest validator with clear error messages."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError as PydanticValidationError

from hemm.manifest.constraints import CONSTRAINT_VERSIONS, ConstraintType
from hemm.manifest.types import (
    BatteryManifest,
    DeviceManifest,
    EVChargerManifest,
    HeatPumpManifest,
    ManifestType,
    PVForecastManifest,
    RoomManifest,
    ThermostatLoadManifest,
    WaterHeaterManifest,
)
from hemm.manifest.version import VersionSpecifier


class ValidationError(Exception):
    """Manifest validation error with clear, actionable messages."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Manifest validation failed: {'; '.join(errors)}")


_TYPE_TO_MODEL: dict[str, type[Any]] = {
    ManifestType.ROOM: RoomManifest,
    ManifestType.THERMOSTAT_LOAD: ThermostatLoadManifest,
    ManifestType.HEAT_PUMP: HeatPumpManifest,
    ManifestType.WATER_HEATER: WaterHeaterManifest,
    ManifestType.BATTERY: BatteryManifest,
    ManifestType.PV_FORECAST: PVForecastManifest,
    ManifestType.EV_CHARGER: EVChargerManifest,
}


def validate_manifest(data: dict[str, Any]) -> DeviceManifest:
    """Validate a manifest dictionary and return the typed model.

    Raises ValidationError with clear error messages on failure.
    """
    errors: list[str] = []

    # Check type field exists
    manifest_type = data.get("type")
    if not manifest_type:
        msg = "Missing required field 'type'. Must be one of: " + ", ".join(t.value for t in ManifestType)
        raise ValidationError([msg])

    if manifest_type not in _TYPE_TO_MODEL:
        msg = f"Unknown manifest type '{manifest_type}'. Must be one of: " + ", ".join(t.value for t in ManifestType)
        raise ValidationError([msg])

    # Check safe_default exists before Pydantic validation
    if "safe_default" not in data:
        errors.append("Missing mandatory field 'safe_default'. Every device must define a fallback action.")

    if errors:
        raise ValidationError(errors)

    # Validate with Pydantic
    model_class = _TYPE_TO_MODEL[manifest_type]
    try:
        manifest = model_class.model_validate(data)
    except PydanticValidationError as e:
        errors = []
        for err in e.errors():
            loc = " → ".join(str(x) for x in err["loc"])
            errors.append(f"{loc}: {err['msg']}")
        raise ValidationError(errors) from e

    # Validate constraint_endpoints version specifiers
    errors.extend(_validate_constraint_endpoints(manifest.constraint_endpoints))

    if errors:
        raise ValidationError(errors)

    return manifest  # type: ignore[no-any-return]


def _validate_constraint_endpoints(endpoints: dict[str, str]) -> list[str]:
    """Validate constraint endpoint version specifiers against known vocabulary."""
    errors: list[str] = []
    for constraint_name, spec_str in endpoints.items():
        # Check constraint type is known
        try:
            ct = ConstraintType(constraint_name)
        except ValueError:
            known = ", ".join(t.value for t in ConstraintType)
            errors.append(f"Unknown constraint type '{constraint_name}'. Known types: {known}")
            continue

        # Parse version specifier
        try:
            spec = VersionSpecifier.parse(spec_str)
        except ValueError as e:
            errors.append(f"Constraint '{constraint_name}': {e}")
            continue

        # Check against current vocabulary version
        current_version = CONSTRAINT_VERSIONS[ct]
        if not spec.matches(current_version):
            errors.append(
                f"Constraint '{constraint_name}' requires version {spec_str}, "
                f"but current vocabulary provides v{current_version}."
            )

    return errors
