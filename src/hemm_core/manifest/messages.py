"""Plan, price, and constraint-window messages."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from hemm_core.manifest.constraints import ConstraintRequirement


class PlanReason(StrEnum):
    """Why the solver chose this setpoint for a given slot.

    Published as sensor.hemm_<dev>_reason in HA.
    """

    PV_SURPLUS = "pv_surplus"
    CHEAP_GRID = "cheap_grid"
    EXPENSIVE_GRID = "expensive_grid"
    MANUAL = "manual"
    SAFETY_DEFAULT = "safety_default"
    CONSTRAINT = "constraint"
    IDLE = "idle"


class PlanSlot(BaseModel):
    """A single time slot in a plan message."""

    start: datetime
    end: datetime
    power_kw: float = Field(description="Planned power for this slot (positive=consume, negative=produce)")
    mode: str | None = Field(default=None, description="Operating mode hint, e.g. 'heat', 'cool', 'idle'")
    reason: PlanReason = Field(default=PlanReason.IDLE, description="Why this setpoint was chosen")
    # Phase 2 stubs — envelope bounds (populated by coordinator post-solve, not by solver)
    envelope_min_kw: float | None = Field(default=None, description="Lower envelope bound in kW (Phase 2)")
    envelope_max_kw: float | None = Field(default=None, description="Upper envelope bound in kW (Phase 2)")


class PlanMessage(BaseModel):
    """Plan message — solver → consumer / actuator layer.

    Contains the planned consumption/production per time slot for a device.
    """

    device_id: str
    created_at: datetime
    horizon_minutes: int = Field(gt=0)
    slots: list[PlanSlot] = Field(min_length=1)
    solver_backend: str = Field(default="milp_central", description="Which solver produced this plan")


class PriceSlot(BaseModel):
    """A single time slot in a price message (Backend B internal)."""

    start: datetime
    end: datetime
    base_price: float = Field(description="Energy price in €/kWh for this slot")
    target_load_band: tuple[float, float] = Field(description="Target consumption band [min_kw, max_kw]")
    penalty_weight: float = Field(default=1.0, ge=0, description="Penalty weight rho for deviation")


class PriceMessage(BaseModel):
    """Price message — Backend B coordinator → consumer.

    {base_price, target_band, penalty_weight} per slot over the horizon.
    """

    device_id: str
    iteration: int = Field(ge=0, description="Price iteration round number")
    created_at: datetime
    slots: list[PriceSlot] = Field(min_length=1)


class ConstraintWindow(BaseModel):
    """Constraint-window message — registered demand with numeric flex.

    Created via hemm.add_constraint_window service.
    """

    window_id: str = Field(description="Unique identifier for this constraint window")
    device_id: str
    deadline: datetime
    requirement: ConstraintRequirement
    flex_cost_per_hour_early: float = Field(
        default=0.0, ge=0, description="€ penalty per hour pulled forward from deadline"
    )
    priority_penalty: float = Field(default=1.0, gt=0, description="Priority weight — higher penalty wins in conflicts")
    ttl_seconds: float | None = Field(default=None, gt=0, description="Time-to-live; window expires after TTL")
    created_at: datetime | None = None
