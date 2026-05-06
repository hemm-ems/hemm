"""Simulation runner — orchestrates multi-day optimization simulation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from hemm.constraints import ConstraintWindowManager
from hemm.manifest.messages import ConstraintWindow, PlanMessage
from hemm.manifest.validator import validate_manifest
from hemm.sim.scenario import Scenario
from hemm.sim.synthetic import generate_price_series
from hemm.solvers.milp_central import MILPCentralSolver
from hemm.solvers.protocol import SolverResult, SolverStatus


@dataclass
class SimMetrics:
    """Metrics collected during simulation."""

    total_cost_eur: float = 0.0
    total_energy_kwh: float = 0.0
    plan_changes: int = 0
    constraint_violations: int = 0
    solve_times: list[float] = field(default_factory=list)
    solver_statuses: list[str] = field(default_factory=list)


@dataclass
class SimResult:
    """Result from a simulation run."""

    scenario_name: str
    days_simulated: int
    total_solve_time_seconds: float
    metrics: SimMetrics
    plans: list[PlanMessage] = field(default_factory=list)
    solver_results: list[SolverResult] = field(default_factory=list)
    success: bool = True
    error: str | None = None


class SimRunner:
    """Simulation runner for multi-day scenarios.

    Runs the solver repeatedly over a multi-day horizon,
    collecting metrics and verifying constraints.
    """

    def __init__(
        self,
        solver: Any | None = None,
        outdoor_temp_c: float = 5.0,
    ) -> None:
        self._solver = solver or MILPCentralSolver(outdoor_temp_c=outdoor_temp_c)
        self._constraint_mgr = ConstraintWindowManager()

    def run(self, scenario: Scenario) -> SimResult:
        """Run a complete simulation for a scenario.

        Args:
            scenario: Scenario definition.

        Returns:
            SimResult with metrics and plans.
        """
        start_time = time.monotonic()
        metrics = SimMetrics()

        # Parse and validate manifests
        try:
            manifests = self._parse_manifests(scenario.manifests)
        except Exception as e:
            return SimResult(
                scenario_name=scenario.name,
                days_simulated=0,
                total_solve_time_seconds=0.0,
                metrics=metrics,
                success=False,
                error=f"Manifest validation failed: {e}",
            )

        # Set up constraint windows
        self._constraint_mgr.clear()
        for cw_data in scenario.constraint_windows:
            cw = ConstraintWindow(**cw_data)
            self._constraint_mgr.add(cw)

        # Run simulation day by day
        all_plans: list[PlanMessage] = []
        all_results: list[SolverResult] = []
        previous_plans: list[PlanMessage] | None = None

        t0 = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)

        for day in range(scenario.days):
            day_start = t0 + timedelta(days=day)

            # Generate price forecast for this day
            price_forecast = generate_price_series(
                start=day_start,
                hours=scenario.horizon_hours,
                resolution_minutes=scenario.resolution_minutes,
                **self._price_params(scenario),
            )

            # Get active constraint windows
            active_windows = self._constraint_mgr.get_active(now=day_start)

            # Solve
            result = self._solver.solve(
                manifests=manifests,
                constraint_windows=active_windows,
                price_forecast=price_forecast,
                horizon_minutes=scenario.horizon_hours * 60,
                resolution_minutes=scenario.resolution_minutes,
                previous_plans=previous_plans,
            )

            all_results.append(result)
            metrics.solve_times.append(result.solve_time_seconds)
            metrics.solver_statuses.append(result.status.value)

            if result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
                all_plans.extend(result.plans)
                # Track plan changes
                if previous_plans:
                    metrics.plan_changes += 1
                previous_plans = result.plans

                # Accumulate cost
                for plan in result.plans:
                    for i, slot in enumerate(plan.slots):
                        price = price_forecast[i][1] if i < len(price_forecast) else 0.30
                        dt_hours = scenario.resolution_minutes / 60.0
                        metrics.total_cost_eur += slot.power_kw * dt_hours * price
                        metrics.total_energy_kwh += abs(slot.power_kw) * dt_hours
            else:
                metrics.constraint_violations += 1

        total_time = time.monotonic() - start_time

        return SimResult(
            scenario_name=scenario.name,
            days_simulated=scenario.days,
            total_solve_time_seconds=total_time,
            metrics=metrics,
            plans=all_plans,
            solver_results=all_results,
            success=all(r.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE) for r in all_results),
        )

    def _parse_manifests(self, manifest_dicts: list[dict[str, Any]]) -> list[Any]:
        """Parse and validate manifest dictionaries."""
        manifests = []
        for data in manifest_dicts:
            manifest = validate_manifest(data)
            manifests.append(manifest)
        return manifests

    def _price_params(self, scenario: Scenario) -> dict[str, Any]:
        """Extract price generation parameters from scenario."""
        params: dict[str, Any] = {}
        if scenario.price_params:
            if "base_price" in scenario.price_params:
                params["base_price"] = scenario.price_params["base_price"]
            if "peak_price" in scenario.price_params:
                params["peak_price"] = scenario.price_params["peak_price"]
            if "off_peak_price" in scenario.price_params:
                params["off_peak_price"] = scenario.price_params["off_peak_price"]
        return params
