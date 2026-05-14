"""Device manifest types — the manifest type catalog."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


class DeviceRole(StrEnum):
    """Abstract energy role of a device in the home energy system.

    - generator: produces energy (PV, wind, CHP)
    - adjustable_sink: consumes energy, HEMM can steer (HP, WH, thermostat)
    - passive_sink: consumes energy, not steerable (kitchen, lighting baseline)
    - storage: stores and releases energy bidirectionally (battery)
    - thermal_zone: passive thermal model, no direct power (room)
    """

    GENERATOR = "generator"
    ADJUSTABLE_SINK = "adjustable_sink"
    PASSIVE_SINK = "passive_sink"
    STORAGE = "storage"
    THERMAL_ZONE = "thermal_zone"


class ManifestType(StrEnum):
    """Manifest types in HEMM's catalog."""

    ROOM = "room"
    THERMOSTAT_LOAD = "thermostat_load"
    HEAT_PUMP = "heat_pump"
    WATER_HEATER = "water_heater"
    BATTERY = "battery"
    PV_FORECAST = "pv_forecast"
    EV_CHARGER = "ev_charger"
    PASSIVE_LOAD = "passive_load"

    @property
    def role(self) -> DeviceRole:
        """Return the abstract energy role for this manifest type."""
        return _TYPE_ROLES[self]


_TYPE_ROLES: dict[ManifestType, DeviceRole] = {
    ManifestType.ROOM: DeviceRole.THERMAL_ZONE,
    ManifestType.THERMOSTAT_LOAD: DeviceRole.ADJUSTABLE_SINK,
    ManifestType.HEAT_PUMP: DeviceRole.ADJUSTABLE_SINK,
    ManifestType.WATER_HEATER: DeviceRole.ADJUSTABLE_SINK,
    ManifestType.BATTERY: DeviceRole.STORAGE,
    ManifestType.PV_FORECAST: DeviceRole.GENERATOR,
    ManifestType.EV_CHARGER: DeviceRole.ADJUSTABLE_SINK,
    ManifestType.PASSIVE_LOAD: DeviceRole.PASSIVE_SINK,
}


class ControlClass(StrEnum):
    """Control class determines how HEMM treats a device and which HA-side pattern applies.

    - passive: observe only, never steer, never replan (e.g. kettle, oven)
    - reactive: publish setpoint + envelope, HA does sub-second loop (e.g. wallbox PWM)
    - planned: full optimization, HA watchdog calls hemm.replan on drift (e.g. heat pump, battery)
    """

    PASSIVE = "passive"
    REACTIVE = "reactive"
    PLANNED = "planned"


class RetryPolicy(BaseModel):
    """Retry policy for actuator actions."""

    max_attempts: int = Field(default=2, ge=1, le=10)
    backoff_seconds: float = Field(default=60, ge=0)


class VerificationContract(BaseModel):
    """Verification contract — checks that the world changed as expected."""

    entity: str = Field(description="HA entity_id to check")
    expected: str = Field(description="Expected value expression, e.g. '>= 60', '== off'")
    within_seconds: float = Field(gt=0, description="Time to wait for verification")


class Action(BaseModel):
    """An actuator action with verification contract."""

    script: str = Field(description="HA script entity to call")
    verify: VerificationContract | None = None
    timeout_seconds: float = Field(default=300, gt=0)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    description: str = ""


class CostFunction(BaseModel):
    """Cost function shape for a device.

    Describes how the device's energy consumption maps to cost.
    """

    type: str = Field(description="Cost function type: 'linear', 'piecewise_linear', 'quadratic'")
    parameters: dict[str, Any] = Field(default_factory=dict)


class TieredConfigHint(BaseModel):
    """Hints for the tiered config flow (beginner/advanced/pro)."""

    tier: str = Field(description="'beginner', 'advanced', or 'pro'")
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    defaults: dict[str, Any] = Field(default_factory=dict)


class _ManifestBase(BaseModel):
    """Base fields shared by all manifest types."""

    device_id: str = Field(description="Unique device identifier within the HEMM instance")
    name: str = Field(description="Human-readable device name")
    control_class: ControlClass = Field(
        default=ControlClass.PLANNED,
        description="Control class: passive (observe), reactive (envelope), planned (full optimization)",
    )
    constraint_endpoints: dict[str, str] = Field(
        default_factory=dict,
        description="Supported constraint types with version specifiers, e.g. {'hold_temp_band': '>=1'}",
    )
    actions: dict[str, Action] = Field(default_factory=dict, description="Named actuator actions")
    safe_default: Action = Field(description="Mandatory fallback action on HEMM failure")
    cost_function: CostFunction | None = None
    tiered_config: list[TieredConfigHint] = Field(default_factory=list)
    envelope_tolerance_pct: float = Field(
        default=15.0,
        ge=0,
        le=100,
        description="Envelope tolerance in percent (Phase 2 — not yet used by solver)",
    )

    @model_validator(mode="after")
    def _validate_safe_default_has_script(self) -> _ManifestBase:
        if not self.safe_default.script:
            msg = "safe_default must have a script defined"
            raise ValueError(msg)
        return self


class RoomManifest(_ManifestBase):
    """Room manifest — thermally modeled room with comfort band."""

    type: ManifestType = ManifestType.ROOM
    floor_area_m2: float = Field(gt=0, description="Floor area in m²")
    thermal_mass_kwh_per_k: float | None = Field(default=None, gt=0, description="Thermal mass in kWh/K")
    u_value_w_per_m2k: float | None = Field(default=None, gt=0, description="U-value in W/(m²·K)")
    window_area_m2: float | None = Field(default=None, ge=0, description="Window area in m²")
    south_facing_windows: bool = False
    insulation_class: str | None = Field(default=None, description="'good', 'medium', 'poor' — beginner tier shortcut")


class ThermostatLoadManifest(_ManifestBase):
    """Thermostat load manifest — simple hysteresis-based heater.

    HEMM decides *when* heating is allowed; the thermostat decides *whether*
    to heat within that allowance.
    """

    type: ManifestType = ManifestType.THERMOSTAT_LOAD
    max_power_kw: float = Field(gt=0, description="Maximum power draw in kW")
    hysteresis_k: float = Field(default=0.5, gt=0, description="Hysteresis band in K")


class HeatPumpManifest(_ManifestBase):
    """Heat pump manifest — heat pump with COP map."""

    type: ManifestType = ManifestType.HEAT_PUMP
    max_power_kw: float = Field(gt=0, description="Maximum electrical power in kW")
    cop_map: list[tuple[float, float]] | None = Field(
        default=None, description="COP curve: list of (outdoor_temp_c, cop) tuples"
    )
    vendor_model: str | None = Field(default=None, description="Vendor model identifier for COP lookup")
    min_modulation_pct: float = Field(default=0, ge=0, le=100)
    defrost_lockout_minutes: float = Field(default=0, ge=0)
    source_type: Literal["air", "ground", "water"] = Field(
        default="air", description="Heat source type: air, ground, or water"
    )
    sink_type: Literal["air", "water"] = Field(
        default="water", description="Heat sink type: air (split AC) or water (radiator/floor)"
    )


class WaterHeaterManifest(_ManifestBase):
    """Water heater manifest — hot water tank."""

    type: ManifestType = ManifestType.WATER_HEATER
    volume_liters: float = Field(gt=0, description="Tank volume in liters")
    max_power_kw: float = Field(gt=0, description="Heating element power in kW")
    standby_loss_w: float = Field(default=50, ge=0, description="Standby heat loss in Watts")
    insulation_class: str | None = Field(default=None, description="'good', 'medium', 'poor'")
    loss_coefficient_w_per_k: float | None = Field(default=None, gt=0)


class BatteryManifest(_ManifestBase):
    """Battery manifest — house battery with charge/discharge efficiency."""

    type: ManifestType = ManifestType.BATTERY
    capacity_kwh: float = Field(gt=0, description="Total capacity in kWh")
    max_charge_kw: float = Field(gt=0, description="Max charge power in kW")
    max_discharge_kw: float = Field(gt=0, description="Max discharge power in kW")
    charge_efficiency: float = Field(default=0.95, gt=0, le=1)
    discharge_efficiency: float = Field(default=0.95, gt=0, le=1)
    min_soc_pct: float = Field(default=10, ge=0, le=100)
    max_soc_pct: float = Field(default=100, ge=0, le=100)


class PVForecastManifest(_ManifestBase):
    """Generator manifest — PV, wind, or CHP with forecast source.

    Kept as PVForecastManifest for backward compatibility. The source_kind
    field generalizes this to any non-dispatchable generation source.
    """

    type: ManifestType = ManifestType.PV_FORECAST
    peak_power_kwp: float = Field(gt=0, description="Peak power in kWp")
    source_kind: Literal["pv", "wind", "chp"] = Field(
        default="pv", description="Generation source kind: pv, wind, or chp"
    )
    azimuth_deg: float | None = Field(default=180, ge=0, lt=360, description="Panel/turbine azimuth (PV/wind only)")
    tilt_deg: float | None = Field(default=30, ge=0, le=90, description="Panel tilt angle (PV only)")
    forecast_adapter: str = Field(default="solcast", description="Forecast source adapter name")
    forecast_entity: str | None = Field(default=None, description="HA entity for forecast data")


class EVChargerManifest(_ManifestBase):
    """EV charger manifest — EV charger with plug-in state and targets."""

    type: ManifestType = ManifestType.EV_CHARGER
    max_charge_kw: float = Field(gt=0, description="Maximum charge power in kW")
    min_charge_kw: float = Field(default=0, ge=0, description="Minimum charge power when active")
    phases: int = Field(default=3, ge=1, le=3, description="Number of phases")
    plug_state_entity: str | None = Field(default=None, description="HA entity for plug-in state")
    soc_entity: str | None = Field(default=None, description="HA entity for current SoC")
    battery_capacity_kwh: float | None = Field(default=None, gt=0, description="EV battery capacity")


class PassiveLoadManifest(_ManifestBase):
    """Passive load manifest — non-steerable consumption as forecast input.

    Represents base-load that HEMM cannot control (kitchen, lighting, etc.).
    The solver subtracts this from available capacity in the power balance.
    """

    type: ManifestType = ManifestType.PASSIVE_LOAD
    typical_daily_kwh: float = Field(gt=0, description="Typical daily consumption in kWh")
    load_profile_entity: str | None = Field(
        default=None, description="HA entity tracking actual consumption for forecasting"
    )


# Discriminated union of all manifest types
DeviceManifest = Annotated[
    RoomManifest
    | ThermostatLoadManifest
    | HeatPumpManifest
    | WaterHeaterManifest
    | BatteryManifest
    | PVForecastManifest
    | EVChargerManifest
    | PassiveLoadManifest,
    Field(discriminator="type"),
]
