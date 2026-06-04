"""Manifest validator with clear error messages."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError as PydanticValidationError

from hemm_core.manifest.components import ComponentSpec, ConverterSpec, NodeSpec, Primitive, StorageSpec
from hemm_core.manifest.constraints import (
    CONSTRAINT_VERSIONS,
    ConstraintType,
    HoldTempBand,
    MinSocUntil,
    ReachMinTempOnce,
)
from hemm_core.manifest.messages import ConstraintWindow
from hemm_core.manifest.types import (
    BatteryManifest,
    DeviceManifest,
    EVChargerManifest,
    HeatPumpManifest,
    ManifestType,
    PassiveLoadManifest,
    PoolPumpManifest,
    PVForecastManifest,
    RoomManifest,
    ThermostatLoadManifest,
    WaterHeaterManifest,
)
from hemm_core.manifest.version import VersionSpecifier


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
    ManifestType.PASSIVE_LOAD: PassiveLoadManifest,
    ManifestType.POOL_PUMP: PoolPumpManifest,
}


def primitives_for_type(manifest_type: str | ManifestType) -> tuple[Primitive, ...]:
    """Return the solver primitives compiled by a manifest type."""
    try:
        resolved_type = ManifestType(manifest_type)
    except ValueError as e:
        msg = f"Unknown manifest type '{manifest_type}'. Must be one of: " + ", ".join(t.value for t in ManifestType)
        raise ValidationError([msg]) from e
    return resolved_type.primitives


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


def validate_constraint_targets(
    manifests: list[DeviceManifest],
    constraint_windows: list[ConstraintWindow],
) -> None:
    """Validate that constraint windows target primitive state vars that exist."""
    components_by_device = {manifest.device_id: list(manifest.to_components()) for manifest in manifests}
    components = [component for device_components in components_by_device.values() for component in device_components]

    errors: list[str] = []
    errors.extend(_validate_converter_output_buses(components))

    state_vars_by_device = _state_vars_by_device(components_by_device)
    for cw in constraint_windows:
        state_vars = state_vars_by_device.get(cw.device_id)
        if state_vars is None:
            errors.append(
                f"Constraint window '{cw.window_id}' targets unknown device '{cw.device_id}' "
                f"for requirement '{cw.requirement.type}'."
            )
            continue

        missing = _missing_capability(cw)
        if missing is not None and missing[0] not in state_vars:
            _, capability = missing
            errors.append(
                f"Device '{cw.device_id}' cannot satisfy requirement '{cw.requirement.type}': "
                f"missing primitive capability '{capability}'."
            )

    if errors:
        raise ValidationError(errors)


def _state_vars_by_device(components_by_device: dict[str, list[ComponentSpec]]) -> dict[str, set[str]]:
    state_vars: dict[str, set[str]] = {}
    for device_id, components in components_by_device.items():
        device_vars = {"power", "on"}
        if any(isinstance(component, StorageSpec) and component.capacity is not None for component in components):
            device_vars.add("level")
        if any(isinstance(component, NodeSpec) and component.quantity == "thermal" for component in components):
            device_vars.add("temp")
        state_vars[device_id] = device_vars
    return state_vars


def _missing_capability(cw: ConstraintWindow) -> tuple[str, str] | None:
    req = cw.requirement
    if isinstance(req, MinSocUntil):
        return ("level", "storage level")
    if isinstance(req, (HoldTempBand, ReachMinTempOnce)):
        return ("temp", "thermal node temperature")
    return None


def _validate_converter_output_buses(components: list[ComponentSpec]) -> list[str]:
    node_buses = {component.bus for component in components if isinstance(component, NodeSpec)}
    errors: list[str] = []
    for component in components:
        if isinstance(component, ConverterSpec) and component.output_bus not in node_buses:
            errors.append(
                f"Converter '{component.device_id}' output_bus '{component.output_bus}' "
                "does not reference a compiled node."
            )
    return errors
