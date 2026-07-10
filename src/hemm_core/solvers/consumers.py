"""Primitive-driven local price response for Backend B."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from hemm_core.manifest.components import ComponentSpec, ConverterSpec, Primitive, SinkSpec, SourceSpec, StorageSpec
from hemm_core.manifest.constraints import (
    ForbiddenWindow,
    HoldTempBand,
    MaxRuntimePerDay,
    MinEnergyUntil,
    MinRuntimePerDay,
    MinSocUntil,
    ReachMinTempOnce,
)
from hemm_core.manifest.messages import ConstraintWindow

_DEFAULT_STATE_FRACTION = 0.5
_DEFAULT_THERMAL_INITIAL_C = 20.0


class ConsumerModel(ABC):
    """Abstract base class for local primitive response models."""

    @property
    @abstractmethod
    def device_id(self) -> str:
        """Device identifier."""
        ...

    @property
    @abstractmethod
    def device_type(self) -> Any:
        """Manifest type value."""
        ...

    @abstractmethod
    def respond_to_prices(
        self,
        prices: list[float],
        n_slots: int,
        resolution_minutes: int,
        constraints: list[ConstraintWindow],
        t0: datetime,
        previous_power: list[float] | None = None,
        plan_change_penalty: float = 0.0,
    ) -> list[float]:
        """Compute a power schedule from slot prices."""
        ...


class _PrimitiveConsumer(ConsumerModel):
    def __init__(self, manifest: Any, component: ComponentSpec) -> None:
        self._manifest = manifest
        self._component = component
        self._reference_prices: list[float] | None = None

    @property
    def device_id(self) -> str:
        return self._component.device_id

    @property
    def device_type(self) -> Any:
        return getattr(self._manifest, "type", None)

    @staticmethod
    def _time_to_slot(dt: datetime, t0: datetime, resolution_minutes: int, n_slots: int) -> int:
        delta = dt - t0
        slot = int(delta.total_seconds() / (resolution_minutes * 60))
        return max(0, min(slot, n_slots - 1))

    def _forbidden_slots(
        self, constraints: list[ConstraintWindow], t0: datetime, resolution_minutes: int, n_slots: int
    ) -> set[int]:
        slots: set[int] = set()
        for cw in constraints:
            if isinstance(cw.requirement, ForbiddenWindow):
                deadline_slot = self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots)
                slots.update(range(min(deadline_slot + 1, n_slots)))
        return slots

    def _runtime_limits(
        self, constraints: list[ConstraintWindow], resolution_minutes: int, n_slots: int
    ) -> tuple[int, int]:
        minimum = 0
        maximum = n_slots
        for cw in constraints:
            req = cw.requirement
            if isinstance(req, MinRuntimePerDay):
                minimum = max(minimum, int(req.min_hours * 60 / resolution_minutes))
            elif isinstance(req, MaxRuntimePerDay):
                maximum = min(maximum, int(req.max_hours * 60 / resolution_minutes))
        return minimum, maximum

    def _prices_for_decision(self, prices: list[float], n_slots: int) -> list[float]:
        if self._reference_prices is None or len(self._reference_prices) != n_slots:
            self._reference_prices = list(prices[:n_slots])
        return self._reference_prices

    @staticmethod
    def _dampen(
        powers: list[float],
        previous_power: list[float] | None,
        plan_change_penalty: float,
        *,
        clamp_nonnegative: bool = False,
    ) -> list[float]:
        if not previous_power or plan_change_penalty <= 0:
            return powers

        damping = 1.0 / (1.0 + plan_change_penalty * 10)
        damped: list[float] = []
        for t, power in enumerate(powers):
            prev = previous_power[t] if t < len(previous_power) else 0.0
            value = prev + (power - prev) * damping
            damped.append(max(0.0, value) if clamp_nonnegative else value)
        return damped


class StorageConsumer(_PrimitiveConsumer):
    """Storage response with arbitrage and deadline target handling."""

    def __init__(self, manifest: Any, component: StorageSpec) -> None:
        super().__init__(manifest, component)
        self._storage = component

    def respond_to_prices(
        self,
        prices: list[float],
        n_slots: int,
        resolution_minutes: int,
        constraints: list[ConstraintWindow],
        t0: datetime,
        previous_power: list[float] | None = None,
        plan_change_penalty: float = 0.0,
    ) -> list[float]:
        storage = self._storage
        dt_hours = resolution_minutes / 60.0
        powers = [0.0] * n_slots
        forbidden = self._forbidden_slots(constraints, t0, resolution_minutes, n_slots)

        decision_input = self._prices_for_decision(prices, n_slots)
        max_charge = storage.max_charge_kw or 0.0
        max_discharge = 0.0 if storage.charge_only else storage.max_discharge_kw
        capacity = storage.capacity
        min_level = storage.min_level
        max_level = storage.max_level if storage.max_level is not None else capacity
        level = capacity * _DEFAULT_STATE_FRACTION if capacity is not None else 0.0

        target_energy, target_level, deadline_slot = self._target(constraints, t0, resolution_minutes, n_slots)
        if storage.charge_only:
            required_input = target_energy
            if capacity is not None and target_level is not None:
                deficit = max(0.0, target_level - level)
                required_input = max(required_input, deficit / max(storage.charge_efficiency, 1e-9))
            return self._charge_to_target(
                powers,
                decision_input,
                required_input,
                deadline_slot,
                forbidden,
                max_charge,
                dt_hours,
                previous_power,
                plan_change_penalty,
            )

        if not decision_input or (max_charge <= 0 and max_discharge <= 0):
            return powers

        if capacity is not None and max_level is not None:
            powers = self._arbitrage_dp(
                decision_input,
                n_slots,
                dt_hours,
                forbidden,
                level,
                min_level,
                max_level,
                max_charge,
                max_discharge,
            )

        trajectory = [level]
        for power in powers:
            if power >= 0:
                level += power * dt_hours * storage.charge_efficiency
            else:
                level += power * dt_hours / storage.discharge_efficiency
            if capacity is not None:
                upper = max_level if max_level is not None else capacity
                level = max(min_level, min(upper, level))
            trajectory.append(level)

        if capacity is not None and target_level is not None and deadline_slot < n_slots:
            deficit = target_level - trajectory[deadline_slot + 1]
            if deficit > 0:
                available = [(decision_input[t], t) for t in range(deadline_slot + 1) if t not in forbidden]
                available.sort()
                for _, t in available:
                    if deficit <= 0:
                        break
                    spare_kw = max(0.0, max_charge - max(0.0, powers[t]))
                    add = min(spare_kw, deficit / (dt_hours * storage.charge_efficiency))
                    powers[t] += add
                    deficit -= add * dt_hours * storage.charge_efficiency

        return self._dampen(powers, previous_power, plan_change_penalty)

    def _arbitrage_dp(
        self,
        prices: list[float],
        n_slots: int,
        dt_hours: float,
        forbidden: set[int],
        initial_level: float,
        min_level: float,
        max_level: float,
        max_charge: float,
        max_discharge: float,
    ) -> list[float]:
        storage = self._storage
        step = max((max_level - min_level) / 80.0, 0.05)
        levels = [min_level + i * step for i in range(round((max_level - min_level) / step) + 1)]
        if levels[-1] < max_level:
            levels.append(max_level)
        start_idx = min(range(len(levels)), key=lambda i: abs(levels[i] - initial_level))

        inf = float("inf")
        costs = [inf] * len(levels)
        costs[start_idx] = 0.0
        parents: list[list[tuple[int, float] | None]] = [[None] * len(levels) for _ in range(n_slots)]

        for t in range(n_slots):
            next_costs = [inf] * len(levels)
            for idx, current_cost in enumerate(costs):
                if current_cost == inf:
                    continue
                for power, next_idx in self._storage_actions(
                    levels[idx],
                    levels,
                    dt_hours,
                    forbidden,
                    t,
                    min_level,
                    max_level,
                    max_charge,
                    max_discharge,
                    storage.charge_efficiency,
                    storage.discharge_efficiency,
                ):
                    slot_cost = prices[t] * power * dt_hours
                    candidate = current_cost + slot_cost
                    if candidate < next_costs[next_idx]:
                        next_costs[next_idx] = candidate
                        parents[t][next_idx] = (idx, power)
            costs = next_costs

        idx = min(range(len(costs)), key=lambda i: costs[i])
        powers = [0.0] * n_slots
        for t in range(n_slots - 1, -1, -1):
            parent = parents[t][idx]
            if parent is None:
                break
            idx, power = parent
            powers[t] = power
        return powers

    @staticmethod
    def _storage_actions(
        level: float,
        levels: list[float],
        dt_hours: float,
        forbidden: set[int],
        slot: int,
        min_level: float,
        max_level: float,
        max_charge: float,
        max_discharge: float,
        charge_efficiency: float,
        discharge_efficiency: float,
    ) -> list[tuple[float, int]]:
        if slot in forbidden:
            return [(0.0, min(range(len(levels)), key=lambda i: abs(levels[i] - level)))]

        candidates = [0.0]
        spare = max(0.0, max_level - level)
        if spare > 0 and max_charge > 0:
            candidates.append(min(max_charge, spare / (dt_hours * charge_efficiency)))
        available = max(0.0, level - min_level)
        if available > 0 and max_discharge > 0:
            candidates.append(-min(max_discharge, available * discharge_efficiency / dt_hours))

        actions: list[tuple[float, int]] = []
        for power in candidates:
            if power >= 0:
                next_level = level + power * dt_hours * charge_efficiency
            else:
                next_level = level + power * dt_hours / discharge_efficiency
            next_level = max(min_level, min(max_level, next_level))
            next_idx = min(range(len(levels)), key=lambda i: abs(levels[i] - next_level))
            actions.append((power, next_idx))
        return actions

    def _target(
        self, constraints: list[ConstraintWindow], t0: datetime, resolution_minutes: int, n_slots: int
    ) -> tuple[float, float | None, int]:
        energy = 0.0
        level: float | None = None
        deadline = n_slots - 1
        capacity = self._storage.capacity
        for cw in constraints:
            slot = self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots)
            req = cw.requirement
            if isinstance(req, MinEnergyUntil):
                energy = max(energy, req.min_energy_kwh)
                deadline = min(deadline, slot)
            elif isinstance(req, MinSocUntil) and capacity is not None:
                level = max(level or 0.0, capacity * req.min_soc_pct / 100.0)
                deadline = min(deadline, slot)
        return energy, level, deadline

    def _charge_to_target(
        self,
        powers: list[float],
        prices: list[float],
        required_input: float,
        deadline_slot: int,
        forbidden: set[int],
        max_charge: float,
        dt_hours: float,
        previous_power: list[float] | None,
        plan_change_penalty: float,
    ) -> list[float]:
        if required_input <= 0 or max_charge <= 0:
            return self._dampen(powers, previous_power, plan_change_penalty, clamp_nonnegative=True)

        available = [(prices[t], t) for t in range(min(deadline_slot + 1, len(powers))) if t not in forbidden]
        available.sort()
        delivered = 0.0
        for _, t in available:
            if delivered >= required_input:
                break
            power = min(max_charge, (required_input - delivered) / dt_hours)
            powers[t] = power
            delivered += power * dt_hours

        return self._dampen(powers, previous_power, plan_change_penalty, clamp_nonnegative=True)


class ConverterConsumer(_PrimitiveConsumer):
    """Converter response using output-factor weighted prices."""

    def __init__(
        self,
        manifest: Any,
        component: ConverterSpec,
        *,
        storage: StorageSpec | None = None,
        outdoor_temp_c: float = 5.0,
    ) -> None:
        super().__init__(manifest, component)
        self._converter = component
        self._storage = storage
        self._outdoor_temp_c = outdoor_temp_c

    def respond_to_prices(
        self,
        prices: list[float],
        n_slots: int,
        resolution_minutes: int,
        constraints: list[ConstraintWindow],
        t0: datetime,
        previous_power: list[float] | None = None,
        plan_change_penalty: float = 0.0,
    ) -> list[float]:
        converter = self._converter
        dt_hours = resolution_minutes / 60.0
        forbidden = self._forbidden_slots(constraints, t0, resolution_minutes, n_slots)
        min_runtime, max_runtime = self._runtime_limits(constraints, resolution_minutes, n_slots)
        required_input, required_output, deadline_slot = self._energy_targets(
            constraints, t0, resolution_minutes, n_slots
        )

        if self._storage and self._storage.leakage:
            required_input = max(required_input, self._storage.leakage * n_slots * dt_hours)

        if required_input <= 0 and required_output <= 0 and min_runtime <= 0:
            return [0.0] * n_slots

        decision_input = self._prices_for_decision(prices, n_slots)
        scored: list[tuple[float, int, float]] = []
        for t in range(n_slots):
            if t in forbidden:
                continue
            factor = self._factor_at_slot(t)
            price = decision_input[t] if t < len(decision_input) else decision_input[-1]
            scored.append((price / max(factor, 1e-9), t, factor))
        scored.sort()

        powers = [0.0] * n_slots
        slots_used = 0
        input_delivered = 0.0
        output_delivered = 0.0
        limit = min(max_runtime, len(scored))

        for _, t, factor in scored:
            if slots_used >= limit:
                break
            before_deadline = t <= deadline_slot
            needs_input = required_input > 0 and input_delivered < required_input and before_deadline
            needs_output = required_output > 0 and output_delivered < required_output and before_deadline
            needs_runtime = slots_used < min_runtime
            if not needs_input and not needs_output and not needs_runtime:
                break

            power = converter.max_input_kw
            if needs_input and not needs_output and not needs_runtime:
                power = min(power, (required_input - input_delivered) / dt_hours)
            if needs_output and not needs_runtime:
                power = min(power, (required_output - output_delivered) / (dt_hours * max(factor, 1e-9)))
            powers[t] = max(0.0, power)
            slots_used += 1  # noqa: SIM113
            input_delivered += powers[t] * dt_hours
            output_delivered += powers[t] * dt_hours * factor

        return self._dampen(powers, previous_power, plan_change_penalty, clamp_nonnegative=True)

    def _factor_at_slot(self, slot: int) -> float:
        if self._converter.factor_ctx == "outdoor_temp":
            return self._converter.factor_at(self._outdoor_temp_c)
        return self._converter.factor_at(0.0)

    def _energy_targets(
        self, constraints: list[ConstraintWindow], t0: datetime, resolution_minutes: int, n_slots: int
    ) -> tuple[float, float, int]:
        required_input = 0.0
        required_output = 0.0
        deadline = n_slots - 1
        for cw in constraints:
            req = cw.requirement
            if isinstance(req, MinEnergyUntil):
                required_input = max(required_input, req.min_energy_kwh)
                deadline = min(deadline, self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots))
            elif isinstance(req, ReachMinTempOnce):
                required_output = max(required_output, self._thermal_delta(req.target_temp_c))
                deadline = min(deadline, self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots))
            elif isinstance(req, HoldTempBand):
                required_output = max(required_output, self._thermal_delta(req.min_temp_c))
                deadline = min(deadline, self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots))
        return required_input, required_output, deadline

    def _thermal_delta(self, target_temp_c: float) -> float:
        if not self._storage or self._storage.capacity is None:
            return 0.0
        return max(0.0, self._storage.capacity * (target_temp_c - _DEFAULT_THERMAL_INITIAL_C))


class SinkConsumer(_PrimitiveConsumer):
    """Sink response for fixed and controllable loads."""

    def __init__(self, manifest: Any, component: SinkSpec) -> None:
        super().__init__(manifest, component)
        self._sink = component

    def respond_to_prices(
        self,
        prices: list[float],
        n_slots: int,
        resolution_minutes: int,
        constraints: list[ConstraintWindow],
        t0: datetime,
        previous_power: list[float] | None = None,
        plan_change_penalty: float = 0.0,
    ) -> list[float]:
        sink = self._sink
        if not sink.controllable:
            return [sink.max_power_kw] * n_slots

        dt_hours = resolution_minutes / 60.0
        forbidden = self._forbidden_slots(constraints, t0, resolution_minutes, n_slots)
        min_runtime, max_runtime = self._runtime_limits(constraints, resolution_minutes, n_slots)
        min_energy, deadline_slot = self._energy_target(constraints, t0, resolution_minutes, n_slots)

        if min_energy <= 0 and min_runtime <= 0:
            return [0.0] * n_slots

        powers = [0.0] * n_slots
        decision_input = self._prices_for_decision(prices, n_slots)
        available = [(decision_input[t], t) for t in range(n_slots) if t not in forbidden]
        available.sort()
        energy = 0.0

        slots_used = 0
        for _, t in available:
            if slots_used >= max_runtime:
                break
            needs_energy = min_energy > 0 and energy < min_energy and t <= deadline_slot
            needs_runtime = slots_used < min_runtime
            if not needs_energy and not needs_runtime:
                break

            power = sink.max_power_kw
            if needs_energy and not needs_runtime:
                power = min(power, (min_energy - energy) / dt_hours)
            powers[t] = max(sink.min_power_kw, power)
            energy += powers[t] * dt_hours
            slots_used += 1  # noqa: SIM113

        return self._dampen(powers, previous_power, plan_change_penalty, clamp_nonnegative=True)

    def _energy_target(
        self, constraints: list[ConstraintWindow], t0: datetime, resolution_minutes: int, n_slots: int
    ) -> tuple[float, int]:
        energy = 0.0
        deadline = n_slots - 1
        for cw in constraints:
            if isinstance(cw.requirement, MinEnergyUntil):
                energy = max(energy, cw.requirement.min_energy_kwh)
                deadline = min(deadline, self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots))
        return energy, deadline


class SourceConsumer(_PrimitiveConsumer):
    """Source response from an explicit generation forecast."""

    def __init__(self, manifest: Any, component: SourceSpec) -> None:
        super().__init__(manifest, component)
        self._source = component

    def respond_to_prices(
        self,
        prices: list[float],
        n_slots: int,
        resolution_minutes: int,
        constraints: list[ConstraintWindow],
        t0: datetime,
        previous_power: list[float] | None = None,
        plan_change_penalty: float = 0.0,
    ) -> list[float]:
        forecast = self._source.forecast or []
        if not forecast:
            return [0.0] * n_slots
        powers: list[float] = []
        for t in range(n_slots):
            value = forecast[t] if t < len(forecast) else forecast[-1]
            powers.append(-abs(value))
        return powers


class NodeConsumer(_PrimitiveConsumer):
    """State node with no direct electrical response."""

    def respond_to_prices(
        self,
        prices: list[float],
        n_slots: int,
        resolution_minutes: int,
        constraints: list[ConstraintWindow],
        t0: datetime,
        previous_power: list[float] | None = None,
        plan_change_penalty: float = 0.0,
    ) -> list[float]:
        return [0.0] * n_slots


class CompositeConsumer(ConsumerModel):
    """Single-device response assembled from one or more primitive consumers."""

    def __init__(self, manifest: Any, consumers: list[ConsumerModel]) -> None:
        self._manifest = manifest
        self._consumers = consumers

    @property
    def device_id(self) -> str:
        return str(self._manifest.device_id)

    @property
    def device_type(self) -> Any:
        return getattr(self._manifest, "type", None)

    def respond_to_prices(
        self,
        prices: list[float],
        n_slots: int,
        resolution_minutes: int,
        constraints: list[ConstraintWindow],
        t0: datetime,
        previous_power: list[float] | None = None,
        plan_change_penalty: float = 0.0,
    ) -> list[float]:
        total = [0.0] * n_slots
        for consumer in self._consumers:
            powers = consumer.respond_to_prices(
                prices,
                n_slots,
                resolution_minutes,
                constraints,
                t0,
                previous_power=previous_power,
                plan_change_penalty=plan_change_penalty,
            )
            total = [total[t] + powers[t] for t in range(n_slots)]
        return total


def get_consumer_model(manifest: Any, outdoor_temp_c: float = 5.0) -> ConsumerModel | None:
    """Compile a manifest to a primitive-based local response model."""
    to_components = getattr(manifest, "to_components", None)
    if to_components is None:
        return None

    components = list(to_components())
    storage = next(
        (
            component
            for component in components
            if component.primitive == Primitive.STORAGE and isinstance(component, StorageSpec)
        ),
        None,
    )
    consumers: list[ConsumerModel] = []

    for component in components:
        if component.primitive == Primitive.SOURCE and isinstance(component, SourceSpec):
            consumers.append(SourceConsumer(manifest, component))
        elif component.primitive == Primitive.SINK and isinstance(component, SinkSpec):
            consumers.append(SinkConsumer(manifest, component))
        elif component.primitive == Primitive.STORAGE and isinstance(component, StorageSpec) and component.node is None:
            consumers.append(StorageConsumer(manifest, component))
        elif component.primitive == Primitive.CONVERTER and isinstance(component, ConverterSpec):
            consumers.append(ConverterConsumer(manifest, component, storage=storage, outdoor_temp_c=outdoor_temp_c))
        elif component.primitive == Primitive.NODE:
            has_electrical_component = any(
                candidate.primitive in {Primitive.SOURCE, Primitive.SINK, Primitive.STORAGE, Primitive.CONVERTER}
                and not (isinstance(candidate, StorageSpec) and candidate.node is not None)
                for candidate in components
            )
            if not has_electrical_component:
                consumers.append(NodeConsumer(manifest, component))

    if not consumers:
        return None
    if len(consumers) == 1:
        return consumers[0]
    return CompositeConsumer(manifest, consumers)
