"""Exogenous simulation inputs produced by occupant profiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ExogenousSlot:
    """One solver slot of exogenous household demand."""

    timestamp: datetime
    presence: int = 0
    electric_load_kw: float = 0.0
    internal_gain_kw: float = 0.0
    dhw_energy_kwh: float = 0.0
    comfort_min_c: dict[str, float] = field(default_factory=dict)
    comfort_max_c: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ExogenousForecast:
    """Aligned exogenous forecast for one solver horizon."""

    slots: list[ExogenousSlot]
    main_fuse_kw: float | None = None

    def electric_loads(self, n_slots: int) -> list[float]:
        return [self.slots[i].electric_load_kw if i < len(self.slots) else 0.0 for i in range(n_slots)]

    def internal_gains(self, n_slots: int) -> list[float]:
        return [self.slots[i].internal_gain_kw if i < len(self.slots) else 0.0 for i in range(n_slots)]

    def dhw_energy(self, n_slots: int) -> list[float]:
        return [self.slots[i].dhw_energy_kwh if i < len(self.slots) else 0.0 for i in range(n_slots)]
