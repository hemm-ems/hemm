"""Solver protocol — the contract all solver backends must satisfy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from hemm_core.manifest.messages import ConstraintWindow, PlanMessage


class SolverStatus(StrEnum):
    """Solver result status."""

    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass(frozen=True)
class SolverResult:
    """Result from a solver run."""

    status: SolverStatus
    plans: list[PlanMessage] = field(default_factory=list)
    objective_value: float | None = None
    solve_time_seconds: float = 0.0
    iterations: int = 1
    diagnostics: dict[str, object] = field(default_factory=dict)


class SolverProtocol(Protocol):
    """Protocol for solver backends.

    All solver backends must implement this interface.
    """

    @property
    def name(self) -> str:
        """Solver backend name."""
        ...

    def solve(
        self,
        manifests: list[object],
        constraint_windows: list[ConstraintWindow],
        price_forecast: list[tuple[datetime, float]],
        horizon_minutes: int,
        resolution_minutes: int,
        previous_plans: list[PlanMessage] | None = None,
        weather_forecast: list[tuple[datetime, float]] | None = None,
        generation_forecast: dict[str, list[float]] | None = None,
        initial_state: dict[str, dict[str, float]] | None = None,
        internal_gains: dict[str, list[float]] | None = None,
    ) -> SolverResult:
        """Solve the optimization problem.

        Args:
            manifests: Device manifests (DeviceManifest union types).
            constraint_windows: Active constraint windows.
            price_forecast: Price forecast as (timestamp, €/kWh) pairs.
            horizon_minutes: Planning horizon in minutes.
            resolution_minutes: Time resolution per slot.
            previous_plans: Previous plans for plan-change penalty.
            weather_forecast: Outdoor temperature forecast as (timestamp, °C) pairs.
            generation_forecast: Per-device generation series in kW (positive =
                available production), overlaid onto forecast-less source
                components at build time (FR-006).
            initial_state: Per-device measured starting state (RW1 FR-105). Keyed
                by device_id, each value a dict with optional ``soc_kwh`` (storage
                stored energy) and ``temp_c`` (thermal-node temperature). When a
                value is absent the solver falls back to its neutral defaults
                (SoC 50 %, 20 °C), so omitting it is behaviour-preserving.
            internal_gains: Per-zone internal-gain series in kW, keyed by the
                zone's device_id and overlaid onto its thermal node (FR-208).
                Positive = heat gain (occupants, appliances); negative =
                extraction, e.g. a hot-water draw on a tank node (FR-207).
                Omitting it is behaviour-preserving.

        Returns:
            SolverResult with plans for each device.
        """
        ...
