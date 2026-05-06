"""Solver protocol — the contract all solver backends must satisfy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from hemm.manifest.messages import ConstraintWindow, PlanMessage


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
    ) -> SolverResult:
        """Solve the optimization problem.

        Args:
            manifests: Device manifests (DeviceManifest union types).
            constraint_windows: Active constraint windows.
            price_forecast: Price forecast as (timestamp, €/kWh) pairs.
            horizon_minutes: Planning horizon in minutes.
            resolution_minutes: Time resolution per slot.
            previous_plans: Previous plans for plan-change penalty.

        Returns:
            SolverResult with plans for each device.
        """
        ...
