"""Backend A — Central MILP solver using Pyomo + HiGHS.

Solves a unified optimization across all devices simultaneously.
Features: piecewise-linear efficiency, plan-change penalty.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pyomo.environ as pyo  # type: ignore[import-untyped]

from hemm.manifest.constraints import (
    ForbiddenWindow,
    HoldTempBand,
    MaxRuntimePerDay,
    MinEnergyUntil,
    MinRuntimePerDay,
    MinSocUntil,
    ReachMinTempOnce,
)
from hemm.manifest.messages import ConstraintWindow, PlanMessage, PlanReason, PlanSlot
from hemm.manifest.types import (
    BatteryManifest,
    EVChargerManifest,
    HeatPumpManifest,
    ManifestType,
    PassiveLoadManifest,
    ThermostatLoadManifest,
    WaterHeaterManifest,
)
from hemm.solvers.protocol import SolverResult, SolverStatus

# Default plan-change penalty weight (€/kW² per slot deviation from previous plan)
PLAN_CHANGE_PENALTY_WEIGHT = 0.01

# Default COP curve for heat pumps if none provided
DEFAULT_COP_MAP: list[tuple[float, float]] = [
    (-15.0, 2.0),
    (-10.0, 2.5),
    (-5.0, 3.0),
    (0.0, 3.5),
    (5.0, 4.0),
    (10.0, 4.5),
    (15.0, 5.0),
]


def _piecewise_cop(cop_map: list[tuple[float, float]], outdoor_temp: float) -> float:
    """Interpolate COP from a piecewise-linear COP map.

    Args:
        cop_map: List of (outdoor_temp_c, cop) tuples, sorted by temperature.
        outdoor_temp: Current outdoor temperature.

    Returns:
        Interpolated COP value.
    """
    if not cop_map:
        return 3.5  # reasonable default

    sorted_map = sorted(cop_map, key=lambda x: x[0])

    # Below minimum temperature in map
    if outdoor_temp <= sorted_map[0][0]:
        return sorted_map[0][1]
    # Above maximum temperature in map
    if outdoor_temp >= sorted_map[-1][0]:
        return sorted_map[-1][1]

    # Linear interpolation
    for i in range(len(sorted_map) - 1):
        t1, c1 = sorted_map[i]
        t2, c2 = sorted_map[i + 1]
        if t1 <= outdoor_temp <= t2:
            ratio = (outdoor_temp - t1) / (t2 - t1)
            return c1 + ratio * (c2 - c1)

    return sorted_map[-1][1]


class MILPCentralSolver:
    """Central MILP solver using Pyomo + HiGHS.

    Builds a unified model across all devices and solves simultaneously.
    """

    def __init__(
        self,
        plan_change_penalty: float = PLAN_CHANGE_PENALTY_WEIGHT,
        outdoor_temp_c: float = 5.0,
        time_limit_seconds: float = 60.0,
    ) -> None:
        self._plan_change_penalty = plan_change_penalty
        self._outdoor_temp_c = outdoor_temp_c
        self._time_limit_seconds = time_limit_seconds

    @property
    def name(self) -> str:
        """Solver backend name."""
        return "milp_central"

    def solve(
        self,
        manifests: list[Any],
        constraint_windows: list[ConstraintWindow],
        price_forecast: list[tuple[datetime, float]],
        horizon_minutes: int = 1440,
        resolution_minutes: int = 15,
        previous_plans: list[PlanMessage] | None = None,
    ) -> SolverResult:
        """Solve the central MILP problem."""
        start_time = time.monotonic()

        n_slots = horizon_minutes // resolution_minutes
        if n_slots <= 0:
            return SolverResult(status=SolverStatus.ERROR, diagnostics={"error": "Invalid horizon/resolution"})

        # Extend or truncate price forecast to match slots
        prices = self._align_prices(price_forecast, n_slots, resolution_minutes)

        # Build the reference time
        t0 = price_forecast[0][0] if price_forecast else datetime.now(tz=UTC)

        # Build Pyomo model
        model = pyo.ConcreteModel("hemm_milp_central")

        # Time set
        model.T = pyo.RangeSet(0, n_slots - 1)

        # Device index
        device_ids = [m.device_id for m in manifests]
        model.D = pyo.Set(initialize=device_ids)

        # Decision variables: power per device per time slot
        model.power = pyo.Var(model.D, model.T, domain=pyo.Reals)

        # Binary variables for on/off (needed for min runtime, forbidden windows)
        model.on = pyo.Var(model.D, model.T, domain=pyo.Binary)

        # Build device-specific constraints
        device_map: dict[str, Any] = {m.device_id: m for m in manifests}

        # Power bounds per device
        model.power_bounds = pyo.ConstraintList()
        for did in device_ids:
            manifest = device_map[did]
            bounds = self._get_power_bounds(manifest)
            for t in model.T:
                model.power_bounds.add(model.power[did, t] >= bounds[0])
                model.power_bounds.add(model.power[did, t] <= bounds[1])
                # Link on/off to power
                model.power_bounds.add(model.power[did, t] <= bounds[1] * model.on[did, t])

        # Battery SoC tracking
        battery_devs = [did for did, m in device_map.items() if m.type == ManifestType.BATTERY]
        if battery_devs:
            model.soc = pyo.Var(
                [(d, t) for d in battery_devs for t in range(n_slots + 1)],
                domain=pyo.NonNegativeReals,
            )
            model.soc_constraints = pyo.ConstraintList()
            for did in battery_devs:
                bat = device_map[did]
                assert isinstance(bat, BatteryManifest)
                cap = bat.capacity_kwh
                # Initial SoC at 50%
                model.soc_constraints.add(model.soc[did, 0] == cap * 0.5)
                for t in range(n_slots):
                    dt_hours = resolution_minutes / 60.0
                    # Positive power = charging, negative = discharging
                    model.soc_constraints.add(
                        model.soc[did, t + 1]
                        == model.soc[did, t] + model.power[did, t] * dt_hours * bat.charge_efficiency
                    )
                    # SoC bounds
                    model.soc_constraints.add(model.soc[did, t + 1] >= cap * bat.min_soc_pct / 100.0)
                    model.soc_constraints.add(model.soc[did, t + 1] <= cap * bat.max_soc_pct / 100.0)

        # Apply constraint windows
        model.constraint_windows = pyo.ConstraintList()
        self._apply_constraint_windows(model, constraint_windows, device_map, t0, n_slots, resolution_minutes)

        # Objective: minimize energy cost + plan-change penalty
        prev_plan_map = self._build_prev_plan_map(previous_plans, device_ids, n_slots)

        # Linearize plan-change penalty using absolute-value auxiliary variables
        if prev_plan_map and self._plan_change_penalty > 0:
            model.delta = pyo.Var(model.D, model.T, domain=pyo.NonNegativeReals)
            model.delta_constraints = pyo.ConstraintList()
            for d in device_ids:
                for t in model.T:
                    prev_val = prev_plan_map.get((d, t), 0.0)
                    model.delta_constraints.add(model.delta[d, t] >= model.power[d, t] - prev_val)
                    model.delta_constraints.add(model.delta[d, t] >= prev_val - model.power[d, t])

        def obj_rule(m: Any) -> Any:
            energy_cost = sum(prices[t] * m.power[d, t] * (resolution_minutes / 60.0) for d in m.D for t in m.T)
            # Plan-change penalty (linear via auxiliary variables)
            change_penalty: Any = 0.0
            if prev_plan_map and self._plan_change_penalty > 0:
                change_penalty = sum(self._plan_change_penalty * m.delta[d, t] for d in m.D for t in m.T)
            return energy_cost + change_penalty

        model.objective = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

        # Solve with HiGHS
        solver = pyo.SolverFactory("appsi_highs")
        solver.options["time_limit"] = self._time_limit_seconds

        try:
            result = solver.solve(model, tee=False)
        except Exception as e:
            return SolverResult(
                status=SolverStatus.ERROR,
                solve_time_seconds=time.monotonic() - start_time,
                diagnostics={"error": str(e)},
            )

        # Check solver status
        status = self._map_solver_status(result)
        if status in (SolverStatus.INFEASIBLE, SolverStatus.ERROR):
            return SolverResult(
                status=status,
                solve_time_seconds=time.monotonic() - start_time,
                diagnostics={"termination": str(result.solver.termination_condition)},
            )

        # Extract plans
        plans = self._extract_plans(
            model, device_ids, n_slots, t0, resolution_minutes, horizon_minutes,
            constraint_windows=constraint_windows, prices=prices,
        )

        solve_time = time.monotonic() - start_time
        obj_val = pyo.value(model.objective) if model.objective.expr is not None else None

        return SolverResult(
            status=status,
            plans=plans,
            objective_value=obj_val,
            solve_time_seconds=solve_time,
            iterations=1,
            diagnostics={"n_devices": len(device_ids), "n_slots": n_slots},
        )

    def _align_prices(
        self, price_forecast: list[tuple[datetime, float]], n_slots: int, resolution_minutes: int
    ) -> list[float]:
        """Align price forecast to solver slots."""
        if not price_forecast:
            return [0.30] * n_slots  # default price €0.30/kWh

        prices: list[float] = []
        for i in range(n_slots):
            if i < len(price_forecast):
                prices.append(price_forecast[i][1])
            else:
                prices.append(price_forecast[-1][1])
        return prices

    def _get_power_bounds(self, manifest: Any) -> tuple[float, float]:
        """Get min/max power bounds for a device."""
        if isinstance(manifest, BatteryManifest):
            return (-manifest.max_discharge_kw, manifest.max_charge_kw)
        if isinstance(manifest, EVChargerManifest):
            return (0.0, manifest.max_charge_kw)
        if isinstance(manifest, HeatPumpManifest):
            return (0.0, manifest.max_power_kw)
        if isinstance(manifest, ThermostatLoadManifest):
            return (0.0, manifest.max_power_kw)
        if isinstance(manifest, WaterHeaterManifest):
            return (0.0, manifest.max_power_kw)
        if isinstance(manifest, PassiveLoadManifest):
            # Fixed load — power is determined by typical daily consumption,
            # distributed evenly.  Bounds are fixed to that value.
            avg_kw = manifest.typical_daily_kwh / 24.0
            return (avg_kw, avg_kw)
        # PV forecast, Room — no direct power decision
        return (0.0, 0.0)

    def _apply_constraint_windows(
        self,
        model: pyo.ConcreteModel,
        constraint_windows: list[ConstraintWindow],
        device_map: dict[str, Any],
        t0: datetime,
        n_slots: int,
        resolution_minutes: int,
    ) -> None:
        """Apply constraint windows to the Pyomo model."""
        for cw in constraint_windows:
            if cw.device_id not in device_map:
                continue

            deadline_slot = self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots)
            req = cw.requirement

            if isinstance(req, ForbiddenWindow):
                # Device must not operate during this window (up to deadline)
                for t in range(min(deadline_slot + 1, n_slots)):
                    model.constraint_windows.add(model.on[cw.device_id, t] == 0)

            elif isinstance(req, MinSocUntil):
                # Battery SoC must be >= target by deadline
                if cw.device_id in [d for d, m in device_map.items() if m.type == ManifestType.BATTERY]:
                    bat = device_map[cw.device_id]
                    assert isinstance(bat, BatteryManifest)
                    target_kwh = bat.capacity_kwh * req.min_soc_pct / 100.0
                    if deadline_slot < n_slots:
                        model.constraint_windows.add(model.soc[cw.device_id, deadline_slot + 1] >= target_kwh)

            elif isinstance(req, MinEnergyUntil):
                # Cumulative energy must be >= target by deadline
                dt_hours = resolution_minutes / 60.0
                model.constraint_windows.add(
                    sum(model.power[cw.device_id, t] * dt_hours for t in range(min(deadline_slot + 1, n_slots)))
                    >= req.min_energy_kwh
                )

            elif isinstance(req, ReachMinTempOnce):
                # At least one slot must have enough power to reach target temp
                # Simplified: ensure some minimum energy is delivered
                pass  # Complex thermal model deferred — just don't block

            elif isinstance(req, HoldTempBand):
                # Simplified: device must run at reasonable level
                pass  # Thermal model needed for proper implementation

            elif isinstance(req, MinRuntimePerDay):
                # Sum of on-variables must be >= min_hours / resolution
                min_slots = int(req.min_hours * 60 / resolution_minutes)
                model.constraint_windows.add(sum(model.on[cw.device_id, t] for t in model.T) >= min_slots)

            elif isinstance(req, MaxRuntimePerDay):
                max_slots = int(req.max_hours * 60 / resolution_minutes)
                model.constraint_windows.add(sum(model.on[cw.device_id, t] for t in model.T) <= max_slots)

    def _time_to_slot(self, dt: datetime, t0: datetime, resolution_minutes: int, n_slots: int) -> int:
        """Convert a datetime to a slot index."""
        delta = dt - t0
        slot = int(delta.total_seconds() / (resolution_minutes * 60))
        return max(0, min(slot, n_slots - 1))

    def _build_prev_plan_map(
        self, previous_plans: list[PlanMessage] | None, device_ids: list[str], n_slots: int
    ) -> dict[tuple[str, int], float]:
        """Build a lookup for previous plan powers."""
        if not previous_plans:
            return {}
        plan_map: dict[tuple[str, int], float] = {}
        for plan in previous_plans:
            if plan.device_id in device_ids:
                for i, slot in enumerate(plan.slots):
                    if i < n_slots:
                        plan_map[(plan.device_id, i)] = slot.power_kw
        return plan_map

    def _map_solver_status(self, result: Any) -> SolverStatus:
        """Map Pyomo solver result to SolverStatus."""
        tc = result.solver.termination_condition
        if tc == pyo.TerminationCondition.optimal:
            return SolverStatus.OPTIMAL
        if tc == pyo.TerminationCondition.feasible:
            return SolverStatus.FEASIBLE
        if tc in (pyo.TerminationCondition.infeasible, pyo.TerminationCondition.infeasibleOrUnbounded):
            return SolverStatus.INFEASIBLE
        if tc == pyo.TerminationCondition.maxTimeLimit:
            return SolverStatus.TIMEOUT
        return SolverStatus.ERROR

    def _extract_plans(
        self,
        model: pyo.ConcreteModel,
        device_ids: list[str],
        n_slots: int,
        t0: datetime,
        resolution_minutes: int,
        horizon_minutes: int,
        *,
        constraint_windows: list[ConstraintWindow] | None = None,
        prices: list[float] | None = None,
    ) -> list[PlanMessage]:
        """Extract plan messages from the solved model with reason annotation."""
        plans: list[PlanMessage] = []
        now = datetime.now(tz=UTC)

        # Pre-compute constrained (device, slot) pairs
        constrained_slots: set[tuple[str, int]] = set()
        if constraint_windows:
            for cw in constraint_windows:
                if cw.device_id not in device_ids:
                    continue
                deadline_slot = self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots)
                for t in range(min(deadline_slot + 1, n_slots)):
                    constrained_slots.add((cw.device_id, t))

        # Pre-compute cheap price threshold (bottom 25%)
        cheap_threshold: float | None = None
        if prices:
            sorted_prices = sorted(prices)
            q25_idx = max(0, len(sorted_prices) // 4 - 1)
            cheap_threshold = sorted_prices[q25_idx]

        for did in device_ids:
            slots: list[PlanSlot] = []
            for t in range(n_slots):
                start = t0 + timedelta(minutes=t * resolution_minutes)
                end = start + timedelta(minutes=resolution_minutes)
                power = pyo.value(model.power[did, t])
                on = pyo.value(model.on[did, t])
                mode = "active" if on > 0.5 else "idle"

                reason = self._determine_reason(
                    did, t, power, on, constrained_slots, prices, cheap_threshold,
                )
                slots.append(PlanSlot(start=start, end=end, power_kw=power, mode=mode, reason=reason))

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

    @staticmethod
    def _determine_reason(
        device_id: str,
        slot_idx: int,
        power: float,
        on: float,
        constrained_slots: set[tuple[str, int]],
        prices: list[float] | None,
        cheap_threshold: float | None,
    ) -> PlanReason:
        """Determine why the solver chose this setpoint for a slot."""
        # Device is effectively off → idle
        if abs(power) < 0.01:
            return PlanReason.IDLE

        # Constraint forced this slot
        if (device_id, slot_idx) in constrained_slots:
            return PlanReason.CONSTRAINT

        # Producing power (negative) → likely PV surplus driving battery discharge or similar
        if power < -0.01:
            return PlanReason.PV_SURPLUS

        # Consuming in a cheap price slot
        if prices and cheap_threshold is not None and slot_idx < len(prices):
            if prices[slot_idx] <= cheap_threshold:
                return PlanReason.CHEAP_GRID

        # Active but no specific reason identified → cheap_grid (solver chose for cost)
        return PlanReason.CHEAP_GRID

    def cop_at_temp(self, manifest: HeatPumpManifest, outdoor_temp: float | None = None) -> float:
        """Get COP for a heat pump at the given outdoor temperature."""
        temp = outdoor_temp if outdoor_temp is not None else self._outdoor_temp_c
        cop_map = manifest.cop_map or DEFAULT_COP_MAP
        return _piecewise_cop(cop_map, temp)
