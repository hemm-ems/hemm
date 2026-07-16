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
    apply_generation_forecast,
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
from hemm_core.manifest.validator import validate_constraint_targets
from hemm_core.solvers.protocol import SolverResult, SolverStatus
from hemm_core.solvers.windows import partition_constraint_windows
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
        feed_in_tariff: float | None = None,
        grid_import_limit_kw: float | None = None,
        grid_export_limit_kw: float | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._plan_change_penalty = plan_change_penalty
        self._outdoor_temp_c = outdoor_temp_c
        self._time_limit_seconds = time_limit_seconds
        # Export price (€/kWh). None → exports credited at the import price
        # (backward-compatible); set below the import price for realistic economics.
        self._feed_in_tariff = feed_in_tariff
        # Connection/main-fuse limits (kW). None → unbounded (legacy). A §14a
        # dimming order is expressible as a lowered import limit (FR-201).
        if grid_import_limit_kw is not None and grid_import_limit_kw <= 0:
            msg = f"grid_import_limit_kw must be positive, got {grid_import_limit_kw}"
            raise ValueError(msg)
        if grid_export_limit_kw is not None and grid_export_limit_kw <= 0:
            msg = f"grid_export_limit_kw must be positive, got {grid_export_limit_kw}"
            raise ValueError(msg)
        self._grid_import_limit_kw = grid_import_limit_kw
        self._grid_export_limit_kw = grid_export_limit_kw
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
        generation_forecast: dict[str, list[float]] | None = None,
        initial_state: dict[str, dict[str, float]] | None = None,
    ) -> SolverResult:
        """Solve the central MILP problem."""
        start_time = self._clock.monotonic()

        n_slots = horizon_minutes // resolution_minutes
        if n_slots <= 0:
            return SolverResult(status=SolverStatus.ERROR, diagnostics={"error": "Invalid horizon/resolution"})

        validate_constraint_targets(manifests, constraint_windows)

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
            manifest.device_id: apply_generation_forecast(list(manifest.to_components()), generation_forecast)
            for manifest in manifests
        }
        components = [
            component for device_components in components_by_device.values() for component in device_components
        ]
        storage_components = {
            component.device_id: component for component in components if isinstance(component, StorageSpec)
        }
        direct_storage_ids = [
            component.device_id for component in storage_components.values() if component.node is None
        ]
        node_components = {
            component.device_id: component for component in components if isinstance(component, NodeSpec)
        }

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
        if direct_storage_ids:
            direct_storage_index = [(d, t) for d in direct_storage_ids for t in range(n_slots)]
            model.power_charge = pyo.Var(direct_storage_index, domain=pyo.NonNegativeReals)
            model.power_discharge = pyo.Var(direct_storage_index, domain=pyo.NonNegativeReals)
            model.b_charge = pyo.Var(direct_storage_index, domain=pyo.Binary)

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
                self._add_storage(model, component, n_slots, resolution_minutes, initial_state=initial_state)
            elif component.primitive == Primitive.CONVERTER:
                self._add_converter(model, component)
            elif component.primitive == Primitive.NODE:
                self._add_node(
                    model,
                    component,
                    components,
                    outdoor_temps,
                    n_slots,
                    resolution_minutes,
                    initial_state=initial_state,
                )

        # Partition windows: applied vs surfaced-as-ignored (FR-206) — impossible
        # deadlines are rejected here, never clamped into the horizon.
        applied_windows, ignored_windows = partition_constraint_windows(
            constraint_windows, set(components_by_device), t0, horizon_minutes
        )

        # Apply constraint windows (including thermal constraints)
        model.constraint_windows = pyo.ConstraintList()
        model.thermal_slack_lo = pyo.VarList(domain=pyo.NonNegativeReals)
        model.thermal_slack_hi = pyo.VarList(domain=pyo.NonNegativeReals)
        model.thermal_reached = pyo.VarList(domain=pyo.Binary)
        thermal_penalty_terms: list[Any] = []
        self._apply_constraint_windows(
            model,
            applied_windows,
            components_by_device,
            storage_components,
            t0,
            n_slots,
            resolution_minutes,
            thermal_penalty_terms=thermal_penalty_terms,
        )

        # Grid settlement (FR-002): net house power per slot is split into
        # import and export legs so exports can be credited at a feed-in tariff
        # below the import price. feed_in_tariff=None keeps export == import.
        dt_hours = resolution_minutes / 60.0
        feed_in = [self._feed_in_tariff if self._feed_in_tariff is not None else prices[t] for t in range(n_slots)]
        model.grid_import = pyo.Var(model.T, domain=pyo.NonNegativeReals)
        model.grid_export = pyo.Var(model.T, domain=pyo.NonNegativeReals)
        model.grid_balance = pyo.ConstraintList()
        for t in model.T:
            model.grid_balance.add(
                model.grid_import[t] - model.grid_export[t] == sum(model.power[d, t] for d in model.D)
            )
            # FR-201: the connection limit bounds each leg; an impossible cap
            # (e.g. fixed load above it) makes the solve INFEASIBLE — fail loud,
            # never silently exceed the main fuse.
            if self._grid_import_limit_kw is not None:
                model.grid_balance.add(model.grid_import[t] <= self._grid_import_limit_kw)
            if self._grid_export_limit_kw is not None:
                model.grid_balance.add(model.grid_export[t] <= self._grid_export_limit_kw)

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
            # Grid settlement: buy imports at the price, sell exports at the feed-in.
            energy_cost = sum((prices[t] * m.grid_import[t] - feed_in[t] * m.grid_export[t]) * dt_hours for t in m.T)
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

        # load_solutions=False so an infeasible model maps to INFEASIBLE instead
        # of the appsi wrapper raising while trying to load a missing solution.
        try:
            result = solver.solve(model, tee=False, load_solutions=False)
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

        try:
            model.solutions.load_from(result)
        except Exception as e:
            # e.g. a TIMEOUT with no incumbent — report honestly, never a stale plan.
            return SolverResult(
                status=SolverStatus.ERROR,
                solve_time_seconds=self._clock.monotonic() - start_time,
                diagnostics={"error": str(e), "termination": str(result.solver.termination_condition)},
            )

        # Extract plans — reason annotation only from windows that were applied
        plans = self._extract_plans(
            model,
            device_ids,
            n_slots,
            t0,
            resolution_minutes,
            horizon_minutes,
            constraint_windows=applied_windows,
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
            diagnostics={
                "n_devices": len(device_ids),
                "n_slots": n_slots,
                "ignored_windows": ignored_windows,
            },
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
        """Add a source primitive. Production is negative power (Backend B convention);
        curtailment down to zero is allowed. Pinned to zero when no forecast is supplied."""
        if not isinstance(component, SourceSpec):
            raise TypeError(f"Expected SourceSpec, got {type(component).__name__}")
        forecast = component.forecast or [0.0] * n_slots
        for t in model.T:
            upper = forecast[int(t)] if int(t) < len(forecast) else forecast[-1]
            model.power_bounds.add(model.power[component.device_id, t] <= 0.0)
            model.power_bounds.add(model.power[component.device_id, t] >= -upper)
            model.power_bounds.add(model.power[component.device_id, t] >= -upper * model.on[component.device_id, t])

    def _add_sink(self, model: pyo.ConcreteModel, component: ComponentSpec) -> None:
        """Add a controllable or fixed sink primitive.

        For controllable sinks the minimum is semi-continuous (FR-205 min
        modulation): the device is either off or runs at ≥ min_power_kw. Fixed
        sinks keep the hard band (e.g. passive loads with min == max).
        """
        if not isinstance(component, SinkSpec):
            raise TypeError(f"Expected SinkSpec, got {type(component).__name__}")
        lower = 0.0 if component.controllable else component.min_power_kw
        self._add_power_bounds(model, component.device_id, lower, component.max_power_kw)
        if component.controllable and component.min_power_kw > 0:
            for t in model.T:
                model.power_bounds.add(
                    model.power[component.device_id, t]
                    >= component.min_power_kw * model.on[component.device_id, t]
                )
                # Close the one-sided on/off link: power > 0 forces on = 1, so
                # the min floor cannot be dodged with on = 0.
                model.power_bounds.add(
                    model.power[component.device_id, t]
                    <= component.max_power_kw * model.on[component.device_id, t]
                )

    def _add_storage(
        self,
        model: pyo.ConcreteModel,
        component: ComponentSpec,
        n_slots: int,
        resolution_minutes: int,
        *,
        initial_state: dict[str, dict[str, float]] | None = None,
    ) -> None:
        """Add storage level recursion and direct electrical bounds where applicable."""
        if not isinstance(component, StorageSpec):
            raise TypeError(f"Expected StorageSpec, got {type(component).__name__}")
        if component.node is None:
            upper = component.max_charge_kw if component.max_charge_kw is not None else 0.0
            lower = 0.0 if component.charge_only else -component.max_discharge_kw
            self._add_power_bounds(model, component.device_id, lower, upper)
            max_charge = component.max_charge_kw if component.max_charge_kw is not None else 0.0
            max_discharge = 0.0 if component.charge_only else component.max_discharge_kw
            for t in model.T:
                model.component_constraints.add(
                    model.power[component.device_id, t]
                    == model.power_charge[component.device_id, t] - model.power_discharge[component.device_id, t]
                )
                model.component_constraints.add(model.power_charge[component.device_id, t] <= max_charge)
                model.component_constraints.add(model.power_discharge[component.device_id, t] <= max_discharge)
                model.component_constraints.add(
                    model.power_charge[component.device_id, t] <= max_charge * model.b_charge[component.device_id, t]
                )
                if component.min_charge_kw > 0:
                    # FR-205: charging is semi-continuous — off, or ≥ the
                    # charger's minimum (e.g. the 6 A IEC floor of a wallbox).
                    model.component_constraints.add(
                        model.power_charge[component.device_id, t]
                        >= component.min_charge_kw * model.b_charge[component.device_id, t]
                    )
                model.component_constraints.add(
                    model.power_discharge[component.device_id, t]
                    <= max_discharge * (1 - model.b_charge[component.device_id, t])
                )

        if component.capacity is None:
            return

        dt_hours = resolution_minutes / 60.0
        max_level = component.max_level if component.max_level is not None else component.capacity
        # Start from the measured SoC when supplied (RW1 FR-105), else the neutral
        # 50 % default — omitting initial_state is behaviour-preserving.
        start_soc = self._initial_soc_kwh(component, initial_state)
        model.component_constraints.add(model.soc[component.device_id, 0] == start_soc)
        for t in range(n_slots):
            leakage = component.leakage or 0.0
            model.component_constraints.add(
                model.soc[component.device_id, t + 1]
                == model.soc[component.device_id, t]
                + (
                    model.power_charge[component.device_id, t] * dt_hours * component.charge_efficiency
                    - model.power_discharge[component.device_id, t] * dt_hours / component.discharge_efficiency
                    if component.node is None
                    else model.power[component.device_id, t] * dt_hours * component.charge_efficiency
                )
                - leakage * dt_hours
            )
            model.component_constraints.add(model.soc[component.device_id, t + 1] >= component.min_level)
            if component.max_level is not None:
                model.component_constraints.add(model.soc[component.device_id, t + 1] <= max_level)

        # Terminal neutrality for direct electrical storage: the horizon may not
        # end below the starting level, so the optimizer cannot book the initial
        # charge as profit by dumping it to the grid (review 001:FR-001/FR-002).
        # Anchored to the *measured* start (RW1 FR-105/FR-204) so a low real SoC is
        # not force-charged up to a fictitious 50 %.
        if component.node is None:
            model.component_constraints.add(model.soc[component.device_id, n_slots] >= start_soc)

    @staticmethod
    def _initial_soc_kwh(component: StorageSpec, initial_state: dict[str, dict[str, float]] | None) -> float:
        """Starting stored energy (kWh): measured value clamped to bounds, else 50 %."""
        capacity = component.capacity if component.capacity is not None else 0.0
        default = capacity * 0.5
        if not initial_state:
            return default
        device = initial_state.get(component.device_id)
        if not device or "soc_kwh" not in device:
            return default
        upper = component.max_level if component.max_level is not None else capacity
        return max(component.min_level, min(upper, float(device["soc_kwh"])))

    def _add_converter(self, model: pyo.ConcreteModel, component: ComponentSpec) -> None:
        """Add converter input-power bounds; thermal injection is consumed by node builders."""
        if not isinstance(component, ConverterSpec):
            raise TypeError(f"Expected ConverterSpec, got {type(component).__name__}")
        self._add_power_bounds(model, component.device_id, 0.0, component.max_input_kw)
        if component.min_input_kw > 0:
            # FR-205 min modulation: off, or at least the modulation floor.
            for t in model.T:
                model.power_bounds.add(
                    model.power[component.device_id, t]
                    >= component.min_input_kw * model.on[component.device_id, t]
                )
                model.power_bounds.add(
                    model.power[component.device_id, t]
                    <= component.max_input_kw * model.on[component.device_id, t]
                )

    def _add_node(
        self,
        model: pyo.ConcreteModel,
        component: ComponentSpec,
        components: list[ComponentSpec],
        outdoor_temps: list[float],
        n_slots: int,
        resolution_minutes: int,
        *,
        initial_state: dict[str, dict[str, float]] | None = None,
    ) -> None:
        """Add the RC balance for a thermal node."""
        if not isinstance(component, NodeSpec):
            raise TypeError(f"Expected NodeSpec, got {type(component).__name__}")
        if component.quantity != "thermal":
            return

        dt_hours = resolution_minutes / 60.0
        thermal_mass = component.thermal_mass or 1.0
        ua_kw = component.ua or 0.0
        initial = component.initial if component.initial is not None else _DEFAULT_INDOOR_TEMP_C
        # Start from the measured node temperature when supplied (RW1 FR-105).
        if initial_state:
            device = initial_state.get(component.device_id)
            if device and "temp_c" in device:
                initial = float(device["temp_c"])
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
        t0: datetime,
        n_slots: int,
        resolution_minutes: int,
        *,
        thermal_penalty_terms: list[Any] | None = None,
    ) -> None:
        """Apply constraint windows to the Pyomo model."""
        if thermal_penalty_terms is None:
            thermal_penalty_terms = []
        state_vars_by_device = self._state_vars_by_device(components_by_device)

        for cw in constraint_windows:
            if cw.device_id not in components_by_device:
                continue

            deadline_slot = self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots)
            req = cw.requirement

            if isinstance(req, ForbiddenWindow):
                # Device must not operate during this window (up to deadline)
                for t in range(min(deadline_slot + 1, n_slots)):
                    model.constraint_windows.add(model.on[cw.device_id, t] == 0)
                    model.constraint_windows.add(model.power[cw.device_id, t] == 0)

            elif isinstance(req, MinSocUntil):
                # Storage level must be >= target by deadline.
                if "level" in state_vars_by_device[cw.device_id]:
                    storage = storage_components[cw.device_id]
                    if storage.capacity is None:
                        raise ValueError(f"Storage capacity is required for {cw.device_id}")
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
                if "temp" in state_vars_by_device[node_id]:
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
                if "temp" in state_vars_by_device[node_id]:
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
                window_slots = range(min(deadline_slot + 1, n_slots))
                model.constraint_windows.add(sum(model.on[cw.device_id, t] for t in window_slots) >= min_slots)
                # `on` must mean actually running: with only the one-sided
                # power<=upper*on link the solver satisfies runtime with on=1 at
                # 0 kW — vacuous compliance. Backend B runs min-runtime slots at
                # rated power; mirror that with a rated-power floor while on.
                rated = self._rated_power_kw(components_by_device.get(cw.device_id, []))
                if rated > 0:
                    for t in window_slots:
                        model.constraint_windows.add(model.power[cw.device_id, t] >= rated * model.on[cw.device_id, t])

            elif isinstance(req, MaxRuntimePerDay):
                max_slots = int(req.max_hours * 60 / resolution_minutes)
                window_slots = range(min(deadline_slot + 1, n_slots))
                model.constraint_windows.add(sum(model.on[cw.device_id, t] for t in window_slots) <= max_slots)

    @staticmethod
    def _rated_power_kw(components: list[ComponentSpec]) -> float:
        """Electrical rating a runtime-constrained device runs at while on."""
        for component in components:
            if isinstance(component, ConverterSpec):
                return float(component.max_input_kw)
            if isinstance(component, SinkSpec):
                return float(component.max_power_kw)
        return 0.0

    @staticmethod
    def _state_vars_by_device(components_by_device: dict[str, list[ComponentSpec]]) -> dict[str, set[str]]:
        """Map each device to primitive-backed state/flow vars available to constraints."""
        state_vars: dict[str, set[str]] = {}
        for device_id, components in components_by_device.items():
            device_vars = {"power", "on"}
            if any(isinstance(component, StorageSpec) and component.capacity is not None for component in components):
                device_vars.add("level")
            if any(isinstance(component, NodeSpec) and component.quantity == "thermal" for component in components):
                device_vars.add("temp")
            state_vars[device_id] = device_vars
        return state_vars

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

        # Pre-compute cheap/expensive price thresholds (bottom/top 25%)
        cheap_threshold: float | None = None
        expensive_threshold: float | None = None
        if prices:
            sorted_prices = sorted(prices)
            q25_idx = max(0, len(sorted_prices) // 4 - 1)
            cheap_threshold = sorted_prices[q25_idx]
            expensive_threshold = sorted_prices[-max(1, len(sorted_prices) // 4)]

        for did in device_ids:
            slots: list[PlanSlot] = []
            for t in range(n_slots):
                start = t0 + timedelta(minutes=t * resolution_minutes)
                end = start + timedelta(minutes=resolution_minutes)
                power = pyo.value(model.power[did, t])
                on = pyo.value(model.on[did, t])
                # Mode from actual power, not the `on` binary: `on` is only
                # one-sidedly linked to power, so it is degenerate for slots with
                # zero or negative power and would flag idle devices as active —
                # the integration actuates scripts based on this field.
                mode = "active" if abs(power) > 0.01 else "idle"

                reason = self._determine_reason(
                    did,
                    t,
                    power,
                    on,
                    constrained_slots,
                    prices,
                    cheap_threshold,
                    expensive_threshold,
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
        expensive_threshold: float | None,
    ) -> PlanReason:
        """Determine why the solver chose this setpoint for a slot."""
        # Device is effectively off → idle
        if abs(power) < 0.01:
            return PlanReason.IDLE

        # Constraint forced this slot
        if (device_id, slot_idx) in constrained_slots:
            return PlanReason.CONSTRAINT

        # Producing power (negative): discharge into a peak-price slot is grid
        # arbitrage, not PV surplus — the battery convention is negative=discharge,
        # so only low/mid-price production keeps the PV-surplus fallback.
        if power < -0.01:
            if (
                prices
                and expensive_threshold is not None
                and slot_idx < len(prices)
                and prices[slot_idx] >= expensive_threshold
            ):
                return PlanReason.EXPENSIVE_GRID
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
