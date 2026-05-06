"""JSON Schema export for manifest types and constraint vocabulary."""

from __future__ import annotations

import json
from typing import Any

from hemm.manifest.constraints import (
    ConstraintVocabulary,
    ForbiddenWindow,
    HoldTempBand,
    MaxRuntimePerDay,
    MinEnergyUntil,
    MinRuntimePerDay,
    MinSocUntil,
    ReachMinTempOnce,
)
from hemm.manifest.messages import ConstraintWindow, PlanMessage, PriceMessage
from hemm.manifest.types import (
    BatteryManifest,
    EVChargerManifest,
    HeatPumpManifest,
    PVForecastManifest,
    RoomManifest,
    ThermostatLoadManifest,
    WaterHeaterManifest,
)

_MANIFEST_SCHEMAS: dict[str, type[Any]] = {
    "room": RoomManifest,
    "thermostat_load": ThermostatLoadManifest,
    "heat_pump": HeatPumpManifest,
    "water_heater": WaterHeaterManifest,
    "battery": BatteryManifest,
    "pv_forecast": PVForecastManifest,
    "ev_charger": EVChargerManifest,
}

_CONSTRAINT_SCHEMAS: dict[str, type[Any]] = {
    "reach_min_temp_once": ReachMinTempOnce,
    "hold_temp_band": HoldTempBand,
    "min_soc_until": MinSocUntil,
    "min_energy_until": MinEnergyUntil,
    "forbidden_window": ForbiddenWindow,
    "min_runtime_per_day": MinRuntimePerDay,
    "max_runtime_per_day": MaxRuntimePerDay,
}

_MESSAGE_SCHEMAS: dict[str, type[Any]] = {
    "plan_message": PlanMessage,
    "price_message": PriceMessage,
    "constraint_window": ConstraintWindow,
    "constraint_vocabulary": ConstraintVocabulary,
}


def get_manifest_schema(manifest_type: str) -> dict[str, Any]:
    """Get JSON Schema for a specific manifest type."""
    if manifest_type not in _MANIFEST_SCHEMAS:
        available = ", ".join(_MANIFEST_SCHEMAS)
        msg = f"Unknown manifest type '{manifest_type}'. Available: {available}"
        raise ValueError(msg)
    result: dict[str, Any] = _MANIFEST_SCHEMAS[manifest_type].model_json_schema()
    return result


def get_constraint_schema(constraint_type: str) -> dict[str, Any]:
    """Get JSON Schema for a specific constraint type."""
    if constraint_type not in _CONSTRAINT_SCHEMAS:
        available = ", ".join(_CONSTRAINT_SCHEMAS)
        msg = f"Unknown constraint type '{constraint_type}'. Available: {available}"
        raise ValueError(msg)
    result: dict[str, Any] = _CONSTRAINT_SCHEMAS[constraint_type].model_json_schema()
    return result


def get_message_schema(message_type: str) -> dict[str, Any]:
    """Get JSON Schema for a message type."""
    if message_type not in _MESSAGE_SCHEMAS:
        available = ", ".join(_MESSAGE_SCHEMAS)
        msg = f"Unknown message type '{message_type}'. Available: {available}"
        raise ValueError(msg)
    result: dict[str, Any] = _MESSAGE_SCHEMAS[message_type].model_json_schema()
    return result


def get_all_schemas() -> dict[str, dict[str, Any]]:
    """Get all schemas as a dict keyed by name."""
    schemas: dict[str, dict[str, Any]] = {}
    for name, model in _MANIFEST_SCHEMAS.items():
        schemas[f"manifest/{name}"] = model.model_json_schema()
    for name, model in _CONSTRAINT_SCHEMAS.items():
        schemas[f"constraint/{name}"] = model.model_json_schema()
    for name, model in _MESSAGE_SCHEMAS.items():
        schemas[f"message/{name}"] = model.model_json_schema()
    return schemas


def export_schemas_json(indent: int = 2) -> str:
    """Export all schemas as a single JSON string."""
    return json.dumps(get_all_schemas(), indent=indent)
