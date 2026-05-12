"""Backend B — Distributed solver with price iteration (ADMM optional).

Each consumer solves its own sub-problem given a price signal.
The coordinator iterates prices until convergence or max iterations.
Features: operating band, plan-change penalty, ADMM augmented Lagrangian.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from hemm.manifest.messages import ConstraintWindow, PlanMessage, PlanSlot
from hemm.solvers.consumers import ConsumerModel, get_consumer_model
from hemm.solvers.protocol import SolverResult, SolverStatus
from hemm.time import Clock, WallClock

# Convergence tolerance for total power imbalance (kW)
DEFAULT_CONVERGENCE_TOL = 0.1
# Default max iterations
DEFAULT_MAX_ITERATIONS = 50
# Default penalty rho for ADMM
DEFAULT_RHO = 0.05
# Price update step size
DEFAULT_STEP_SIZE = 0.01


@dataclass
class IterationLog:
    """Log entry for one iteration of the distributed solver."""

    iteration: int
    total_load_kw: float
    target_load_kw: float
    imbalance_kw: float
    max_device_change_kw: float
    prices_updated: bool


class DistributedSolver:
    """Distributed solver using price iteration.

    Coordinator sends price signals to consumer models.
    Each consumer optimizes locally given prices.
    Coordinator adjusts prices to balance total load.

    Two modes:
    - 'price_iteration': simple price adjustment based on load imbalance
    - 'admm': Alternating Direction Method of Multipliers for faster convergence
    """

    def __init__(
        self,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        convergence_tol: float = DEFAULT_CONVERGENCE_TOL,
        rho: float = DEFAULT_RHO,
        step_size: float = DEFAULT_STEP_SIZE,
        mode: str = "price_iteration",
        plan_change_penalty: float = 0.01,
        outdoor_temp_c: float = 5.0,
        time_limit_seconds: float = 30.0,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._max_iterations = max_iterations
        self._convergence_tol = convergence_tol
        self._rho = rho
        self._step_size = step_size
        self._mode = mode
        self._plan_change_penalty = plan_change_penalty
        self._outdoor_temp_c = outdoor_temp_c
        self._time_limit_seconds = time_limit_seconds
        self._clock: Clock = clock if clock is not None else WallClock()

    @property
    def name(self) -> str:
        """Solver backend name."""
        return f"distributed_{self._mode}"

    def solve(
        self,
        manifests: list[Any],
        constraint_windows: list[ConstraintWindow],
        price_forecast: list[tuple[datetime, float]],
        horizon_minutes: int = 1440,
        resolution_minutes: int = 15,
        previous_plans: list[PlanMessage] | None = None,
    ) -> SolverResult:
        """Solve via distributed price iteration."""
        start_time = self._clock.monotonic()

        n_slots = horizon_minutes // resolution_minutes
        if n_slots <= 0:
            return SolverResult(status=SolverStatus.ERROR, diagnostics={"error": "Invalid horizon/resolution"})

        # Build time axis
        t0 = price_forecast[0][0] if price_forecast else self._clock.now()
        prices = self._align_prices(price_forecast, n_slots)

        # Create consumer models for each device
        consumers: list[tuple[str, ConsumerModel]] = []
        device_constraints: dict[str, list[ConstraintWindow]] = {}

        for manifest in manifests:
            did = manifest.device_id
            consumer = get_consumer_model(manifest, outdoor_temp_c=self._outdoor_temp_c)
            if consumer is not None:
                consumers.append((did, consumer))
            # Gather per-device constraints
            device_constraints[did] = [cw for cw in constraint_windows if cw.device_id == did]

        if not consumers:
            return SolverResult(
                status=SolverStatus.OPTIMAL,
                plans=[],
                solve_time_seconds=self._clock.monotonic() - start_time,
                iterations=0,
            )

        # Build previous plan map
        prev_map: dict[str, list[float]] = {}
        if previous_plans:
            for plan in previous_plans:
                prev_map[plan.device_id] = [s.power_kw for s in plan.slots[:n_slots]]

        # Initialize coordinator prices (start from market prices)
        coord_prices = list(prices)

        # ADMM dual variables (one per device per slot)
        duals: dict[str, list[float]] = {did: [0.0] * n_slots for did, _ in consumers}

        # Target load per slot (0 = minimize total consumption, or could be based on PV)
        target_load = [0.0] * n_slots

        # Iteration
        iteration_logs: list[IterationLog] = []
        device_powers: dict[str, list[float]] = {did: [0.0] * n_slots for did, _ in consumers}
        converged = False
        final_iteration = 0

        for iteration in range(self._max_iterations):
            if self._clock.monotonic() - start_time > self._time_limit_seconds:
                break

            final_iteration = iteration + 1
            max_device_change = 0.0

            # Step 1: Each consumer solves given current prices
            for did, consumer in consumers:
                # Build effective prices for this consumer (market + dual)
                effective_prices = [coord_prices[t] + duals[did][t] for t in range(n_slots)]

                prev_power = prev_map.get(did)
                constraints = device_constraints.get(did, [])

                new_powers = consumer.respond_to_prices(
                    prices=effective_prices,
                    n_slots=n_slots,
                    resolution_minutes=resolution_minutes,
                    constraints=constraints,
                    t0=t0,
                    previous_power=prev_power,
                    plan_change_penalty=self._plan_change_penalty,
                )

                # Track max change for convergence
                old_powers = device_powers[did]
                change = max(abs(new_powers[t] - old_powers[t]) for t in range(n_slots))
                max_device_change = max(max_device_change, change)

                device_powers[did] = new_powers

            # Step 2: Compute total load per slot
            total_load = [sum(device_powers[did][t] for did, _ in consumers) for t in range(n_slots)]

            # Check convergence (imbalance from target)
            imbalance = max(abs(total_load[t] - target_load[t]) for t in range(n_slots))

            log = IterationLog(
                iteration=iteration,
                total_load_kw=sum(total_load) / n_slots,
                target_load_kw=sum(target_load) / n_slots,
                imbalance_kw=imbalance,
                max_device_change_kw=max_device_change,
                prices_updated=True,
            )
            iteration_logs.append(log)

            # Convergence check: if device responses barely change, we've converged
            if max_device_change < self._convergence_tol and iteration > 0:
                converged = True
                break

            # Step 3: Update prices
            if self._mode == "admm":
                # ADMM: update dual variables
                for did, _ in consumers:
                    for t in range(n_slots):
                        residual = device_powers[did][t] - target_load[t] / max(len(consumers), 1)
                        duals[did][t] += self._rho * residual
            else:
                # Simple price iteration: raise price where load is high, lower where low
                for t in range(n_slots):
                    excess = total_load[t] - target_load[t]
                    coord_prices[t] += self._step_size * excess
                    # Floor at 0
                    coord_prices[t] = max(0.0, coord_prices[t])

        # Build plans from final device powers
        plans = self._build_plans(device_powers, consumers, t0, n_slots, resolution_minutes, horizon_minutes)

        solve_time = self._clock.monotonic() - start_time

        # Calculate objective (total energy cost)
        obj_value = sum(
            prices[t] * sum(device_powers[did][t] for did, _ in consumers) * (resolution_minutes / 60.0)
            for t in range(n_slots)
        )

        status = SolverStatus.OPTIMAL if converged else SolverStatus.FEASIBLE

        return SolverResult(
            status=status,
            plans=plans,
            objective_value=obj_value,
            solve_time_seconds=solve_time,
            iterations=final_iteration,
            diagnostics={
                "mode": self._mode,
                "converged": converged,
                "final_imbalance_kw": iteration_logs[-1].imbalance_kw if iteration_logs else 0.0,
                "n_consumers": len(consumers),
                "n_slots": n_slots,
            },
        )

    def _align_prices(self, price_forecast: list[tuple[datetime, float]], n_slots: int) -> list[float]:
        """Align price forecast to solver slots."""
        if not price_forecast:
            return [0.30] * n_slots
        prices: list[float] = []
        for i in range(n_slots):
            if i < len(price_forecast):
                prices.append(price_forecast[i][1])
            else:
                prices.append(price_forecast[-1][1])
        return prices

    def _build_plans(
        self,
        device_powers: dict[str, list[float]],
        consumers: list[tuple[str, ConsumerModel]],
        t0: datetime,
        n_slots: int,
        resolution_minutes: int,
        horizon_minutes: int,
    ) -> list[PlanMessage]:
        """Build plan messages from device power allocations."""
        plans: list[PlanMessage] = []
        now = self._clock.now()

        for did, _ in consumers:
            powers = device_powers[did]
            slots: list[PlanSlot] = []
            for t in range(n_slots):
                start = t0 + timedelta(minutes=t * resolution_minutes)
                end = start + timedelta(minutes=resolution_minutes)
                mode = "active" if abs(powers[t]) > 0.01 else "idle"
                slots.append(PlanSlot(start=start, end=end, power_kw=powers[t], mode=mode))

            plans.append(
                PlanMessage(
                    device_id=did,
                    created_at=now,
                    horizon_minutes=horizon_minutes,
                    slots=slots,
                    solver_backend=self.name,
                )
            )

        return plans
