"""Constraint vocabulary v1 — vendor-agnostic constraint types."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ConstraintType(StrEnum):
    """Known constraint types in HEMM vocabulary v1."""

    REACH_MIN_TEMP_ONCE = "reach_min_temp_once"
    HOLD_TEMP_BAND = "hold_temp_band"
    MIN_SOC_UNTIL = "min_soc_until"
    MIN_ENERGY_UNTIL = "min_energy_until"
    FORBIDDEN_WINDOW = "forbidden_window"
    MIN_RUNTIME_PER_DAY = "min_runtime_per_day"
    MAX_RUNTIME_PER_DAY = "max_runtime_per_day"


class ConstraintVersion(BaseModel):
    """Tracks the version of a constraint type."""

    constraint_type: ConstraintType
    version: int = 1


class ReachMinTempOnce(BaseModel):
    """Reach temperature X at least once before deadline.

    Use case: hot water legionella cycle, pre-heating.
    """

    type: Literal["reach_min_temp_once"] = "reach_min_temp_once"
    target_temp_c: float = Field(gt=0, le=100, description="Target temperature in °C")
    description: str = "Reach target temperature at least once before deadline"


class HoldTempBand(BaseModel):
    """Keep temperature within [min, max] band.

    Use case: room comfort temperature bands.
    """

    type: Literal["hold_temp_band"] = "hold_temp_band"
    min_temp_c: float = Field(description="Minimum temperature in °C")
    max_temp_c: float = Field(description="Maximum temperature in °C")
    description: str = "Hold temperature within comfort band"


class MinSocUntil(BaseModel):
    """State of charge >= X% by time T.

    Use case: battery must be at 80% by morning, EV SoC target.
    Targets the *state variable* (percentage).
    """

    type: Literal["min_soc_until"] = "min_soc_until"
    min_soc_pct: float = Field(ge=0, le=100, description="Minimum SoC in percent")
    description: str = "Minimum state of charge by deadline"


class MinEnergyUntil(BaseModel):
    """Cumulative energy >= X kWh by time T.

    Use case: EV needs 60 kWh charged by departure.
    Targets the *cumulative energy flow* (kWh), not a state variable.
    """

    type: Literal["min_energy_until"] = "min_energy_until"
    min_energy_kwh: float = Field(gt=0, description="Minimum cumulative energy in kWh")
    description: str = "Minimum cumulative energy delivered by deadline"


class ForbiddenWindow(BaseModel):
    """Must not run during time window.

    Use case: utility lockout periods, quiet hours.
    """

    type: Literal["forbidden_window"] = "forbidden_window"
    description: str = "Device must not operate during this window"


class MinRuntimePerDay(BaseModel):
    """Minimum runtime hours per day.

    Use case: circulation pump must run at least 2h/day.
    """

    type: Literal["min_runtime_per_day"] = "min_runtime_per_day"
    min_hours: float = Field(gt=0, le=24, description="Minimum runtime in hours per day")
    description: str = "Minimum daily runtime requirement"


class MaxRuntimePerDay(BaseModel):
    """Maximum runtime hours per day.

    Use case: compressor wear limit.
    """

    type: Literal["max_runtime_per_day"] = "max_runtime_per_day"
    max_hours: float = Field(gt=0, le=24, description="Maximum runtime in hours per day")
    description: str = "Maximum daily runtime limit"


# Discriminated union of all constraint requirement types
ConstraintRequirement = Annotated[
    ReachMinTempOnce
    | HoldTempBand
    | MinSocUntil
    | MinEnergyUntil
    | ForbiddenWindow
    | MinRuntimePerDay
    | MaxRuntimePerDay,
    Field(discriminator="type"),
]


# Current versions of all constraint types
CONSTRAINT_VERSIONS: dict[ConstraintType, int] = {
    ConstraintType.REACH_MIN_TEMP_ONCE: 1,
    ConstraintType.HOLD_TEMP_BAND: 1,
    ConstraintType.MIN_SOC_UNTIL: 1,
    ConstraintType.MIN_ENERGY_UNTIL: 1,
    ConstraintType.FORBIDDEN_WINDOW: 1,
    ConstraintType.MIN_RUNTIME_PER_DAY: 1,
    ConstraintType.MAX_RUNTIME_PER_DAY: 1,
}


class ConstraintVocabulary(BaseModel):
    """The full constraint vocabulary with version information."""

    version: str = "1.0"
    constraints: dict[ConstraintType, int] = Field(default_factory=lambda: dict(CONSTRAINT_VERSIONS))
