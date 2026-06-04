"""Primitive component model for solver-relevant manifest behavior."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Primitive(StrEnum):
    """Solver primitive emitted by a named manifest type."""

    SOURCE = "source"
    SINK = "sink"
    STORAGE = "storage"
    CONVERTER = "converter"
    NODE = "node"


DEFAULT_COP_MAP: list[tuple[float, float]] = [
    (-15.0, 2.0),
    (-10.0, 2.5),
    (-5.0, 3.0),
    (0.0, 3.5),
    (5.0, 4.0),
    (10.0, 4.5),
    (15.0, 5.0),
]

# Thermal-node defaults — kept here as the single source so the Backend-A node
# builder (Phase 3) and to_components() resolve identical values (golden parity).
# Mirror solvers/milp_central.py (_DEFAULT_THERMAL_MASS_KWH_PER_K, _INSULATION_U_VALUE).
DEFAULT_THERMAL_MASS_KWH_PER_K: float = 2.0
INSULATION_U_VALUE: dict[str, float] = {"good": 0.25, "medium": 0.5, "poor": 1.0}


class ComponentSpec(BaseModel):
    """Base component specification shared by all primitives."""

    device_id: str = Field(description="Owning manifest device identifier")
    primitive: Primitive = Field(description="Solver primitive kind")
    bus: str = Field(default="elec", description="Bus or node this component is attached to")


class SourceSpec(ComponentSpec):
    """Non-dispatchable source component."""

    primitive: Literal[Primitive.SOURCE] = Primitive.SOURCE
    forecast: list[float] | None = None


class SinkSpec(ComponentSpec):
    """Load component."""

    primitive: Literal[Primitive.SINK] = Primitive.SINK
    min_power_kw: float = 0.0
    max_power_kw: float
    controllable: bool = True


class StorageSpec(ComponentSpec):
    """Conserved-quantity storage component."""

    primitive: Literal[Primitive.STORAGE] = Primitive.STORAGE
    capacity: float | None
    max_charge_kw: float | None = None
    max_discharge_kw: float = 0.0
    charge_efficiency: float = 1.0
    discharge_efficiency: float = 1.0
    min_level: float = 0.0
    max_level: float | None = None
    charge_only: bool = False
    leakage: float | None = None
    node: str | None = None


class ConverterSpec(ComponentSpec):
    """Converter from one bus to another with an optional context-dependent factor."""

    primitive: Literal[Primitive.CONVERTER] = Primitive.CONVERTER
    input_bus: str = "elec"
    output_bus: str
    max_input_kw: float
    factor_map: list[tuple[float, float]]
    factor_ctx: str = "outdoor_temp"

    def factor_at(self, ctx: float) -> float:
        """Return the converter factor at a context value using clamped linear interpolation."""
        if not self.factor_map:
            return 1.0

        sorted_map = sorted(self.factor_map, key=lambda item: item[0])
        if ctx <= sorted_map[0][0]:
            return sorted_map[0][1]
        if ctx >= sorted_map[-1][0]:
            return sorted_map[-1][1]

        for i in range(len(sorted_map) - 1):
            x1, y1 = sorted_map[i]
            x2, y2 = sorted_map[i + 1]
            if x1 <= ctx <= x2:
                ratio = (ctx - x1) / (x2 - x1)
                return y1 + ratio * (y2 - y1)

        return sorted_map[-1][1]


class NodeSpec(ComponentSpec):
    """Conserved-quantity node component."""

    primitive: Literal[Primitive.NODE] = Primitive.NODE
    quantity: str = "thermal"
    thermal_mass: float | None = None
    ua: float | None = None
    ambient_ctx: str = "outdoor_temp"
    comfort_band: tuple[float, float] | None = None
    initial: float | None = None
