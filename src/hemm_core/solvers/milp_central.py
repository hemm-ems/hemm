"""Backend A — Central MILP solver using Pyomo + HiGHS.

Solves a unified optimization across all devices simultaneously.
Features: piecewise-linear efficiency, plan-change penalty.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pyomo.environ as pyo  # type: ignore[import-untyped]

from hemm_core.manifest.components import (
    DEFAULT_COP_MAP,
    ComponentSpec,
    ConverterSpec,
    NodeSpec,
    Primitive,
    SinkSpec,
    SourceSpec,
    StorageSpec,
)
from hemm_core.manifest.constraints import (
    ForbiddenWindow,
    HoldTempBand,
    MaxRuntimePerDay,
    MinEnergyUntil,
    MinRuntimePerDay,
    MinSocUntil,
    ReachMinTempOnce,
)
from hemm_core.manifest.messages import ConstraintWindow, PlanMessage, PlanReason, PlanSlot
from hemm_core.solvers.protocol import SolverResult, SolverStatus
from hemm_core.time import Clock, WallClock

# Default plan-change penalty weight (€/kW² per slot deviation from previous plan)
PLAN_CHANGE_PENALTY_WEIGHT = 0.01

# Default indoor temperature for initial condition (°C)
_DEFAULT_INDOOR_TEMP_C = 20.0

# Big-M for ReachMinTempOnce linearisation (°C headroom)
_BIG_M_TEMP = 50.0


def _piecewise_cop(cop_map: list[tuple[float, float]], outdoor_temp: float) -> float:
    """Backward-compatible wrapper around ConverterSpec.factor_at()."""
    if not cop_map:
        return 3.5  # reasonable default
    converter = ConverterSpec(
        device_id="_compat",
        output_bus="thermal:_compat",
        max_input_kw=0.0,
        factor_map=cop_map,
    )
    return converter.factor_at(outdoor_temp)


class MILPCentralSolver:
    """Central MILP solver using Pyomo + HiGHS.

    Builds a unified model across all devices and solves simultaneously.
    """

    def __init__(
        self,
        plan_change_penalty: float = PLAN_CHANGE_PENALTY_WEIGHT,
        outdoor_temp_c: float = 5.0,
        time_limit_seconds: float = 60.0,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._plan_change_penalty = plan_change_penalty
        self._outdoor_temp_c = outdoor_temp_c
        self._time_limit_seconds = time_limit_seconds
        self._clock: Clock = clock if clock is not None else WallClock()

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
        weather_forecast: list[tuple[datetime, float]] | None = None,
    ) -> SolverResult:
        """Solve the central MILP problem."""
        start_time = self._clock.monotonic()

        n_slots = horizon_minutes // resolution_minutes
        if n_slots <= 0:
            return SolverResult(status=SolverStatus.ERROR, diagnostics={"error": "Invalid horizon/resolution"})

        # Extend or truncate price forecast to match slots
        prices = self._align_prices(price_forecast, n_slots, resolution_minutes)

        # Build the reference time
        t0 = price_forecast[0][0] if price_forecast else self._clock.now()

        # Build Pyomo model
        model = pyo.ConcreteModel("hemm_milp_central")

        # Time set
        model.T = pyo.RangeSet(0, n_slots - 1)

        # Device index
        device_ids = [m.device_id for m in manifests]
        model.D = pyo.Set(initialize=device_ids)

        components_by_device: dict[str, list[ComponentSpec]] = {
            manifest.device_id: list(manifest.to_components()) for manifest in manifests
        }
        components = [component for device_components in components_by_device.values() for component in device_components]
        storage_components = {
            component.device_id: component for component in components if isinstance(component, StorageSpec)
        }
        node_components = {component.device_id: component for component in components if isinstance(component, NodeSpec)}

        # Decision variables: power per device per time slot
        model.power = pyo.Var(model.D, model.T, domain=pyo.Reals)

        # Binary variables for on/off (needed for min runtime, forbidden windows)
        model.on = pyo.Var(model.D, model.T, domain=pyo.Binary)

        # Build device-specific constraints from primitive components
        model.power_bounds = pyo.ConstraintList()
        model.component_constraints = pyo.ConstraintList()

        if storage_components:
            model.soc = pyo.Var(
                [(d, t) for d in storage_components for t in range(n_slots + 1)],
                domain=pyo.NonNegativeReals,
            )

        outdoor_temps = self._align_weather(weather_forecast, n_slots)
        if node_components:
            model.temp = pyo.Var(
                [(d, t) for d in node_components for t in range(n_slots + 1)],
                domain=pyo.Reals,
            )
            model.thermal_constraints = pyo.ConstraintList()

        for component in components:
            if component.primitive == Primitive.SOURCE:
                self._add_source(model, component, n_slots)
            elif component.primitive == Primitive.SINK:
                self._add_sink(model, component)
            elif component.primitive == Primitive.STORAGE:
                self._add_storage(model, component, n_slots, resolution_minutes)
            elif component.primitive == Primitive.CONVERTER:
                self._add_converter(model, component)
            elif component.primitive == Primitive.NODE:
                self._add_node(model, component, components, outdoor_temps, n_slots, resolution_minutes)

        # Apply constraint windows (including thermal constraints)
        model.constraint_windows = pyo.ConstraintList()
        model.thermal_slack_lo = pyo.VarList(domain=pyo.NonNegativeReals)
        model.thermal_slack_hi = pyo.VarList(domain=pyo.NonNegativeReals)
        model.thermal_reached = pyo.VarList(domain=pyo.Binary)
        thermal_penalty_terms: list[Any] = []
        self._apply_constraint_windows(
            model,
            constraint_windows,
            components_by_device,
            storage_components,
            node_components,
            t0,
            n_slots,
            resolution_minutes,
            thermal_penalty_terms=thermal_penalty_terms,
        )

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
            # Thermal comfort violation penalty
            comfort_penalty: Any = 0.0
            if thermal_penalty_terms:
                comfort_penalty = sum(thermal_penalty_terms)
            return energy_cost + change_penalty + comfort_penalty

        model.objective = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

        # Solve with HiGHS
        solver = pyo.SolverFactory("appsi_highs")
        solver.options["time_limit"] = self._time_limit_seconds

        try:
            result = solver.solve(model, tee=False)
        except Exception as e:
            return SolverResult(
                status=SolverStatus.ERROR,
                solve_time_seconds=self._clock.monotonic() - start_time,
                diagnostics={"error": str(e)},
            )

        # Check solver status
        status = self._map_solver_status(result)
        if status in (SolverStatus.INFEASIBLE, SolverStatus.ERROR):
            return SolverResult(
                status=status,
                solve_time_seconds=self._clock.monotonic() - start_time,
                diagnostics={"termination": str(result.solver.termination_condition)},
            )

        # Extract plans
        plans = self._extract_plans(
            model,
            device_ids,
            n_slots,
            t0,
            resolution_minutes,
            horizon_minutes,
            constraint_windows=constraint_windows,
            prices=prices,
        )

        solve_time = self._clock.monotonic() - start_time
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

    def _align_weather(self, weather_forecast: list[tuple[datetime, float]] | None, n_slots: int) -> list[float]:
        """Align weather forecast to solver slots, falling back to constructor default."""
        if not weather_forecast:
            return [self._outdoor_temp_c] * n_slots
        temps: list[float] = []
        for i in range(n_slots):
            if i < len(weather_forecast):
                temps.append(weather_forecast[i][1])
            else:
                temps.append(weather_forecast[-1][1])
        return temps

    def _add_power_bounds(self, model: pyo.ConcreteModel, device_id: str, lower: float, upper: float) -> None:
        """Add power bounds and the legacy one-sided on/off link."""
        for t in model.T:
            model.power_bounds.add(model.power[device_id, t] >= lower)
            model.power_bounds.add(model.power[device_id, t] <= upper)
            model.power_bounds.add(model.power[device_id, t] <= upper * model.on[device_id, t])

    def _add_source(self, model: pyo.ConcreteModel, component: ComponentSpec, n_slots: int) -> None:
        """Add a source primitive. PV remains pinned to zero when no forecast is supplied."""
        assert isinstance(component, SourceSpec)
        forecast = component.forecast or [0.0] * n_slots
        for t in model.T:
            upper = forecast[int(t)] if int(t) < len(forecast) else forecast[-1]
            model.power_bounds.add(model.power[component.device_id, t] >= 0.0)
            model.power_bounds.add(model.power[component.device_id, t] <= upper)
            model.power_bounds.add(model.power[component.device_id, t] <= upper * model.on[component.device_id, t])

    def _add_sink(self, model: pyo.ConcreteModel, component: ComponentSpec) -> None:
        """Add a controllable or fixed sink primitive."""
        assert isinstance(component, SinkSpec)
        self._add_power_bounds(model, component.device_id, component.min_power_kw, component.max_power_kw)

    def _add_storage(
        self,
        model: pyo.ConcreteModel,
        component: ComponentSpec,
        n_slots: int,
        resolution_minutes: int,
    ) -> None:
        """Add storage level recursion and direct electrical bounds where applicable."""
        assert isinstance(component, StorageSpec)
        if component.node is None:
            upper = component.max_charge_kw if component.max_charge_kw is not None else 0.0
            lower = 0.0 if component.charge_only else -component.max_discharge_kw
            self._add_power_bounds(model, component.device_id, lower, upper)

        if component.capacity is None:
            return

        dt_hours = resolution_minutes / 60.0
        max_level = component.max_level if component.max_level is not None else component.capacity
        model.component_constraints.add(model.soc[component.device_id, 0] == component.capacity * 0.5)
        for t in range(n_slots):
            leakage = component.leakage or 0.0
            model.component_constraints.add(
                model.soc[component.device_id, t + 1]
                == model.soc[component.device_id, t]
                + model.power[component.device_id, t] * dt_hours * component.charge_efficiency
                - leakage * dt_hours
            )
            model.component_constraints.add(model.soc[component.device_id, t + 1] >= component.min_level)
            if component.max_level is not None:
                model.component_constraints.add(model.soc[component.device_id, t + 1] <= max_level)

    def _add_converter(self, model: pyo.ConcreteModel, component: ComponentSpec) -> None:
        """Add converter input-power bounds; thermal injection is consumed by node builders."""
        assert isinstance(component, ConverterSpec)
        self._add_power_bounds(model, component.device_id, 0.0, component.max_input_kw)

    def _add_node(
        self,
        model: pyo.ConcreteModel,
        component: ComponentSpec,
        components: list[ComponentSpec],
        outdoor_temps: list[float],
        n_slots: int,
        resolution_minutes: int,
    ) -> None:
        """Add the RC balance for a thermal node."""
        assert isinstance(component, NodeSpec)
        if component.quantity != "thermal":
            return

        dt_hours = resolution_minutes / 60.0
        thermal_mass = component.thermal_mass or 1.0
        ua_kw = component.ua or 0.0
        initial = component.initial if component.initial is not None else _DEFAULT_INDOOR_TEMP_C
        converters = [
            candidate
            for candidate in components
            if isinstance(candidate, ConverterSpec) and candidate.output_bus == component.bus
        ]
        has_power_component = any(
            candidate.device_id == component.device_id
            and (
                isinstance(candidate, (ConverterSpec, SinkSpec, SourceSpec))
                or (isinstance(candidate, StorageSpec) and candidate.node is None)
            )
            for candidate in components
        )
        leakage_kw = sum(
            candidate.leakage or 0.0
            for candidate in components
            if isinstance(candidate, StorageSpec) and candidate.node == component.bus
        )

        if not has_power_component:
            self._add_power_bounds(model, component.device_id, 0.0, 0.0)

        model.thermal_constraints.add(model.temp[component.device_id, 0] == initial)
        for t in range(n_slots):
            q_in: Any = 0.0
            for converter in converters:
                ctx = outdoor_temps[t] if converter.factor_ctx == "outdoor_temp" else 0.0
                q_in += model.power[converter.device_id, t] * converter.factor_at(ctx)
            t_out = outdoor_temps[t]
            model.thermal_constraints.add(
                model.temp[component.device_id, t + 1]
                == model.temp[component.device_id, t]
                + dt_hours * (q_in - leakage_kw - ua_kw * (model.temp[component.device_id, t] - t_out)) / thermal_mass
            )

    def _apply_constraint_windows(
        self,
        model: pyo.ConcreteModel,
        constraint_windows: list[ConstraintWindow],
        components_by_device: dict[str, list[ComponentSpec]],
        storage_components: dict[str, StorageSpec],
        node_components: dict[str, NodeSpec],
        t0: datetime,
        n_slots: int,
        resolution_minutes: int,
        *,
        thermal_penalty_terms: list[Any] | None = None,
    ) -> None:
        """Apply constraint windows to the Pyomo model."""
        if thermal_penalty_terms is None:
            thermal_penalty_terms = []

        for cw in constraint_windows:
            if cw.device_id not in components_by_device:
                continue

            deadline_slot = self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots)
            req = cw.requirement

            if isinstance(req, ForbiddenWindow):
                # Device must not operate during this window (up to deadline)
                for t in range(min(deadline_slot + 1, n_slots)):
                    model.constraint_windows.add(model.on[cw.device_id, t] == 0)

            elif isinstance(req, MinSocUntil):
                # Storage level must be >= target by deadline.
                storage = storage_components.get(cw.device_id)
                if storage is not None and storage.capacity is not None and hasattr(model, "soc"):
                    target_kwh = storage.capacity * req.min_soc_pct / 100.0
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
                # Room must reach target_temp_c at least once before deadline.
                # Binary reached[t]: 1 iff T[room, t] >= target.
                # Linearised via big-M: T[t] - target >= -M*(1 - reached[t])
                # At least one reached[t] == 1 up to deadline.
                node_id = cw.device_id
                if node_id in node_components and hasattr(model, "temp"):
                    target = req.target_temp_c
                    reached_vars: list[Any] = []
                    for t in range(min(deadline_slot + 1, n_slots) + 1):
                        r_var = model.thermal_reached.add()
                        reached_vars.append(r_var)
                        # Big-M linearisation: T >= target - M*(1 - reached)
                        model.constraint_windows.add(model.temp[node_id, t] - target >= -_BIG_M_TEMP * (1 - r_var))
                    # At least one must be reached
                    model.constraint_windows.add(sum(reached_vars) >= 1)

            elif isinstance(req, HoldTempBand):
                # Soft comfort band: T[room, t] in [min_temp, max_temp]
                # with slack variables penalised in the objective.
                node_id = cw.device_id
                if node_id in node_components and hasattr(model, "temp"):
                    for t in range(min(deadline_slot + 1, n_slots) + 1):
                        s_lo = model.thermal_slack_lo.add()
                        s_hi = model.thermal_slack_hi.add()
                        # T[t] + s_lo >= min_temp
                        model.constraint_windows.add(model.temp[node_id, t] + s_lo >= req.min_temp_c)
                        # T[t] - s_hi <= max_temp
                        model.constraint_windows.add(model.temp[node_id, t] - s_hi <= req.max_temp_c)
                        thermal_penalty_terms.append(cw.priority_penalty * (s_lo + s_hi))

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
        now = self._clock.now()

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
                    did,
                    t,
                    power,
                    on,
                    constrained_slots,
                    prices,
                    cheap_threshold,
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
        if prices and cheap_threshold is not None and slot_idx < len(prices) and prices[slot_idx] <= cheap_threshold:
            return PlanReason.CHEAP_GRID

        # Active but no specific reason identified → cheap_grid (solver chose for cost)
        return PlanReason.CHEAP_GRID

    def cop_at_temp(self, manifest: Any, outdoor_temp: float | None = None) -> float:
        """Backward-compatible COP helper; solver converters use factor_at()."""
        temp = outdoor_temp if outdoor_temp is not None else self._outdoor_temp_c
        cop_map = getattr(manifest, "cop_map", None) or DEFAULT_COP_MAP
        return _piecewise_cop(cop_map, temp)
