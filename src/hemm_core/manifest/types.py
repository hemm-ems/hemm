"""Device manifest types — the manifest type catalog."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from hemm_core.manifest.components import (
    DEFAULT_COP_MAP,
    DEFAULT_THERMAL_MASS_KWH_PER_K,
    INSULATION_U_VALUE,
    ComponentSpec,
    ConverterSpec,
    NodeSpec,
    Primitive,
    SinkSpec,
    SourceSpec,
    StorageSpec,
)


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
    POOL_PUMP = "pool_pump"

    @property
    def primitives(self) -> tuple[Primitive, ...]:
        """Return the distinct solver primitives this manifest type can produce."""
        return _TYPE_PRIMITIVES[self]


_TYPE_PRIMITIVES: dict[ManifestType, tuple[Primitive, ...]] = {
    ManifestType.ROOM: (Primitive.NODE,),
    ManifestType.THERMOSTAT_LOAD: (Primitive.CONVERTER, Primitive.SINK),
    ManifestType.HEAT_PUMP: (Primitive.CONVERTER, Primitive.SINK),
    ManifestType.WATER_HEATER: (Primitive.NODE, Primitive.CONVERTER, Primitive.STORAGE),
    ManifestType.BATTERY: (Primitive.STORAGE,),
    ManifestType.PV_FORECAST: (Primitive.SOURCE,),
    ManifestType.EV_CHARGER: (Primitive.STORAGE,),
    ManifestType.PASSIVE_LOAD: (Primitive.SINK,),
    ManifestType.POOL_PUMP: (Primitive.SINK,),
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
    writes_entity: str | None = Field(
        default=None,
        description=(
            "HA entity_id that this action's script writes directly, used to detect self-confirming verification"
        ),
    )
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

    def to_components(self) -> list[ComponentSpec]:
        """Compile this named manifest into solver primitive components."""
        msg = f"{type(self).__name__} must implement to_components()"
        raise NotImplementedError(msg)


class RoomManifest(_ManifestBase):
    """Room manifest — thermally modeled room with comfort band."""

    type: ManifestType = ManifestType.ROOM
    floor_area_m2: float = Field(gt=0, description="Floor area in m²")
    thermal_mass_kwh_per_k: float | None = Field(default=None, gt=0, description="Thermal mass in kWh/K")
    u_value_w_per_m2k: float | None = Field(default=None, gt=0, description="U-value in W/(m²·K)")
    window_area_m2: float | None = Field(default=None, ge=0, description="Window area in m²")
    south_facing_windows: bool = False
    insulation_class: str | None = Field(default=None, description="'good', 'medium', 'poor' — beginner tier shortcut")

    @model_validator(mode="after")
    def _reject_unmodeled_solar_gains(self) -> RoomManifest:
        # FR-205: no solver backend models passive solar gains yet, so accepting
        # this flag would be a silent no-op. window_area_m2 still binds (envelope
        # losses). Re-allow once a per-zone gains series drives the room node.
        if self.south_facing_windows:
            msg = (
                "south_facing_windows is not modeled by any solver backend yet "
                "(solar gains are ignored); set it to false (FR-205)"
            )
            raise ValueError(msg)
        return self

    def to_components(self) -> list[ComponentSpec]:
        # Resolve thermal_mass + UA exactly as the Backend-A room RC block does
        # (solvers/milp_central.py): envelope = floor + window area; U-value falls
        # back to the insulation class; both carry the solver defaults so the
        # NodeSpec is a complete, parity-exact solver input.
        thermal_mass = self.thermal_mass_kwh_per_k or DEFAULT_THERMAL_MASS_KWH_PER_K
        envelope_area = self.floor_area_m2 + (self.window_area_m2 or 0.0)
        u_val = self.u_value_w_per_m2k
        if u_val is None:
            u_val = INSULATION_U_VALUE.get(self.insulation_class or "medium", 0.5)
        ua = u_val * envelope_area / 1000.0  # W/K → kW/K
        return [
            NodeSpec(
                device_id=self.device_id,
                bus=f"thermal:{self.device_id}",
                quantity="thermal",
                thermal_mass=thermal_mass,
                ua=ua,
                ambient_ctx="outdoor_temp",
                comfort_band=None,
                initial=None,
            )
        ]


class ThermostatLoadManifest(_ManifestBase):
    """Thermostat load manifest — simple hysteresis-based heater.

    HEMM decides *when* heating is allowed; the thermostat decides *whether*
    to heat within that allowance.
    """

    type: ManifestType = ManifestType.THERMOSTAT_LOAD
    max_power_kw: float = Field(gt=0, description="Maximum power draw in kW")
    hysteresis_k: float = Field(default=0.5, gt=0, description="Hysteresis band in K")
    room_id: str | None = Field(default=None, description="device_id of the RoomManifest this heater serves")

    def to_components(self) -> list[ComponentSpec]:
        if self.room_id:
            return [
                ConverterSpec(
                    device_id=self.device_id,
                    output_bus=f"thermal:{self.room_id}",
                    max_input_kw=self.max_power_kw,
                    factor_map=[(0.0, 1.0)],
                    factor_ctx="none",
                )
            ]
        return [SinkSpec(device_id=self.device_id, max_power_kw=self.max_power_kw, controllable=True)]


class HeatPumpManifest(_ManifestBase):
    """Heat pump manifest — heat pump with COP map."""

    type: ManifestType = ManifestType.HEAT_PUMP
    max_power_kw: float = Field(gt=0, description="Maximum electrical power in kW")
    room_id: str | None = Field(default=None, description="device_id of the RoomManifest this heat pump serves")
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

    @model_validator(mode="after")
    def _reject_unmodeled_defrost(self) -> HeatPumpManifest:
        # FR-205: defrost lockout has no solver model; a non-zero value would be
        # a silent no-op. min_modulation_pct IS enforced (semi-continuous floor).
        if self.defrost_lockout_minutes != 0:
            msg = (
                "defrost_lockout_minutes is not modeled by any solver backend yet; "
                "set it to 0 (FR-205)"
            )
            raise ValueError(msg)
        return self

    def to_components(self) -> list[ComponentSpec]:
        min_power_kw = self.max_power_kw * self.min_modulation_pct / 100.0
        if self.room_id:
            return [
                ConverterSpec(
                    device_id=self.device_id,
                    input_bus="elec",
                    output_bus=f"thermal:{self.room_id}",
                    max_input_kw=self.max_power_kw,
                    min_input_kw=min_power_kw,
                    factor_map=self.cop_map or DEFAULT_COP_MAP,
                    factor_ctx="outdoor_temp",
                )
            ]
        return [
            SinkSpec(
                device_id=self.device_id,
                min_power_kw=min_power_kw,
                max_power_kw=self.max_power_kw,
                controllable=True,
            )
        ]


class WaterHeaterManifest(_ManifestBase):
    """Water heater manifest — hot water tank."""

    type: ManifestType = ManifestType.WATER_HEATER
    volume_liters: float = Field(gt=0, description="Tank volume in liters")
    room_id: str | None = Field(default=None, description="device_id of the RoomManifest this water heater serves")
    max_power_kw: float = Field(gt=0, description="Heating element power in kW")
    standby_loss_w: float = Field(default=50, ge=0, description="Standby heat loss in Watts")
    insulation_class: str | None = Field(default=None, description="'good', 'medium', 'poor'")
    loss_coefficient_w_per_k: float | None = Field(default=None, gt=0)
    heating_efficiency: float = Field(
        default=0.98,
        gt=0,
        le=1,
        description="Electrical-to-tank heating efficiency (element + piping losses)",
    )

    def to_components(self) -> list[ComponentSpec]:
        node_id = f"thermal:{self.device_id}"
        thermal_mass = self.volume_liters * 4.186 / 3600.0
        ua = None
        if self.loss_coefficient_w_per_k is not None:
            ua = self.loss_coefficient_w_per_k / 1000.0

        # heating_efficiency binds on both energy paths: the converter factor
        # (node temperature q_in) and the storage charge leg (stored energy).
        return [
            NodeSpec(
                device_id=self.device_id,
                bus=node_id,
                quantity="thermal",
                thermal_mass=thermal_mass,
                ua=ua,
                ambient_ctx="outdoor_temp",
                comfort_band=None,
                initial=None,
            ),
            ConverterSpec(
                device_id=self.device_id,
                output_bus=node_id,
                max_input_kw=self.max_power_kw,
                factor_map=[(0.0, self.heating_efficiency)],
                factor_ctx="none",
            ),
            StorageSpec(
                device_id=self.device_id,
                node=node_id,
                capacity=thermal_mass,
                charge_efficiency=self.heating_efficiency,
                leakage=self.standby_loss_w / 1000.0,
            ),
        ]


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

    def to_components(self) -> list[ComponentSpec]:
        return [
            StorageSpec(
                device_id=self.device_id,
                capacity=self.capacity_kwh,
                max_charge_kw=self.max_charge_kw,
                max_discharge_kw=self.max_discharge_kw,
                charge_efficiency=self.charge_efficiency,
                discharge_efficiency=self.discharge_efficiency,
                min_level=self.capacity_kwh * self.min_soc_pct / 100.0,
                max_level=self.capacity_kwh * self.max_soc_pct / 100.0,
                charge_only=False,
            )
        ]


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

    def to_components(self) -> list[ComponentSpec]:
        return [SourceSpec(device_id=self.device_id, forecast=None)]


class EVChargerManifest(_ManifestBase):
    """EV charger manifest — EV charger with plug-in state and targets."""

    type: ManifestType = ManifestType.EV_CHARGER
    max_charge_kw: float = Field(gt=0, description="Maximum charge power in kW")
    min_charge_kw: float = Field(default=0, ge=0, description="Minimum charge power when active")
    phases: int = Field(default=3, ge=1, le=3, description="Number of phases")
    plug_state_entity: str | None = Field(default=None, description="HA entity for plug-in state")
    soc_entity: str | None = Field(default=None, description="HA entity for current SoC")
    battery_capacity_kwh: float | None = Field(default=None, gt=0, description="EV battery capacity")
    charge_efficiency: float = Field(
        default=0.9,
        gt=0,
        le=1,
        description="Grid-to-EV-battery charging efficiency (onboard AC charger + cable losses)",
    )

    @model_validator(mode="after")
    def _validate_phase_consistency(self) -> EVChargerManifest:
        # FR-205: phases must bind. 32 A × 230 V per phase caps the plausible
        # charge power; a 1-phase 11 kW claim is a manifest error, not a hint.
        max_plausible_kw = self.phases * 32 * 230 / 1000.0
        if self.max_charge_kw > max_plausible_kw + 1e-9:
            msg = (
                f"max_charge_kw={self.max_charge_kw} exceeds {max_plausible_kw:.2f} kW "
                f"(32 A × 230 V × {self.phases} phase(s)); fix phases or max_charge_kw (FR-205)"
            )
            raise ValueError(msg)
        if self.min_charge_kw > self.max_charge_kw:
            msg = f"min_charge_kw={self.min_charge_kw} exceeds max_charge_kw={self.max_charge_kw}"
            raise ValueError(msg)
        return self

    def to_components(self) -> list[ComponentSpec]:
        # charge_only: no V2G path is modeled, so there is deliberately no
        # discharge_efficiency field (it would be accepted-but-ignored, FR-205).
        return [
            StorageSpec(
                device_id=self.device_id,
                capacity=self.battery_capacity_kwh,
                max_charge_kw=self.max_charge_kw,
                min_charge_kw=self.min_charge_kw,
                charge_efficiency=self.charge_efficiency,
                charge_only=True,
                max_level=self.battery_capacity_kwh,
                min_level=0.0,
            )
        ]


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

    def to_components(self) -> list[ComponentSpec]:
        power_kw = self.typical_daily_kwh / 24.0
        return [
            SinkSpec(
                device_id=self.device_id,
                controllable=False,
                min_power_kw=power_kw,
                max_power_kw=power_kw,
            )
        ]


class PoolPumpManifest(_ManifestBase):
    """Pool pump manifest — steerable electrical circulation pump."""

    type: ManifestType = ManifestType.POOL_PUMP
    max_power_kw: float = Field(gt=0, description="Maximum motor power draw in kW")

    def to_components(self) -> list[ComponentSpec]:
        return [
            SinkSpec(
                device_id=self.device_id,
                bus="elec",
                min_power_kw=0.0,
                max_power_kw=self.max_power_kw,
                controllable=True,
            )
        ]


# Discriminated union of all manifest types
DeviceManifest = Annotated[
    RoomManifest
    | ThermostatLoadManifest
    | HeatPumpManifest
    | WaterHeaterManifest
    | BatteryManifest
    | PVForecastManifest
    | EVChargerManifest
    | PassiveLoadManifest
    | PoolPumpManifest,
    Field(discriminator="type"),
]
