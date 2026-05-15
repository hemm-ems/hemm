"""Consumer models — realistic device response models for both solver backends.

Each consumer model encapsulates the local optimization logic for a device type.
Given price signals, a consumer decides its optimal power schedule subject to
its physical constraints.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any

from hemm_core.manifest.constraints import (
    ForbiddenWindow,
    MaxRuntimePerDay,
    MinEnergyUntil,
    MinRuntimePerDay,
    MinSocUntil,
)
from hemm_core.manifest.messages import ConstraintWindow
from hemm_core.manifest.types import (
    BatteryManifest,
    EVChargerManifest,
    HeatPumpManifest,
    ManifestType,
    PassiveLoadManifest,
    PVForecastManifest,
    RoomManifest,
    ThermostatLoadManifest,
    WaterHeaterManifest,
)


class ConsumerModel(ABC):
    """Abstract base class for consumer models.

    A consumer model responds to price signals by computing an optimal
    power schedule subject to its physical and operational constraints.
    """

    @property
    @abstractmethod
    def device_id(self) -> str:
        """Device identifier."""
        ...

    @property
    @abstractmethod
    def device_type(self) -> ManifestType:
        """Device type."""
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
        """Compute optimal power schedule given prices.

        Args:
            prices: Effective price per slot (€/kWh).
            n_slots: Number of time slots.
            resolution_minutes: Duration per slot.
            constraints: Active constraint windows for this device.
            t0: Start time of horizon.
            previous_power: Previous plan power per slot (for plan-change penalty).
            plan_change_penalty: Penalty weight for deviating from previous plan.

        Returns:
            List of power values (kW) per slot.
        """
        ...


class BatteryConsumer(ConsumerModel):
    """Battery consumer — charges when cheap, discharges when expensive."""

    def __init__(self, manifest: BatteryManifest) -> None:
        self._manifest = manifest

    @property
    def device_id(self) -> str:
        return self._manifest.device_id

    @property
    def device_type(self) -> ManifestType:
        return ManifestType.BATTERY

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
        """Battery: charge at low prices, discharge at high prices, respecting SoC limits."""
        bat = self._manifest
        dt_hours = resolution_minutes / 60.0
        cap = bat.capacity_kwh
        min_soc = cap * bat.min_soc_pct / 100.0
        max_soc = cap * bat.max_soc_pct / 100.0

        # Check for MinSocUntil constraints
        soc_targets: list[tuple[int, float]] = []
        forbidden_slots: set[int] = set()
        for cw in constraints:
            deadline_slot = self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots)
            if isinstance(cw.requirement, MinSocUntil):
                target_kwh = cap * cw.requirement.min_soc_pct / 100.0
                soc_targets.append((deadline_slot, target_kwh))
            elif isinstance(cw.requirement, ForbiddenWindow):
                for t in range(min(deadline_slot + 1, n_slots)):
                    forbidden_slots.add(t)

        # Greedy approach: sort slots by price, charge cheapest, discharge most expensive
        # While respecting SoC trajectory constraints
        powers = [0.0] * n_slots
        soc = cap * 0.5  # Start at 50%

        # Compute price median to decide charge/discharge threshold
        sorted_prices = sorted(prices[:n_slots])
        median_price = sorted_prices[len(sorted_prices) // 2]

        # Forward pass: respect SoC limits and meet targets
        soc_trajectory = [soc]
        for t in range(n_slots):
            if t in forbidden_slots:
                powers[t] = 0.0
            elif prices[t] < median_price * 0.85:
                # Cheap: charge
                max_charge = min(bat.max_charge_kw, (max_soc - soc) / (dt_hours * bat.charge_efficiency))
                powers[t] = max(0.0, max_charge)
            elif prices[t] > median_price * 1.15:
                # Expensive: discharge
                max_discharge = min(bat.max_discharge_kw, (soc - min_soc) / dt_hours)
                powers[t] = -max(0.0, max_discharge)
            else:
                powers[t] = 0.0

            # Apply plan-change penalty (reduce changes from previous)
            if previous_power and plan_change_penalty > 0:
                prev = previous_power[t] if t < len(previous_power) else 0.0
                # Dampen change
                change = powers[t] - prev
                damping = 1.0 / (1.0 + plan_change_penalty * 10)
                powers[t] = prev + change * damping

            # Update SoC
            if powers[t] > 0:
                soc += powers[t] * dt_hours * bat.charge_efficiency
            else:
                soc += powers[t] * dt_hours  # discharge (power is negative)

            # Clamp SoC
            soc = max(min_soc, min(max_soc, soc))
            soc_trajectory.append(soc)

        # Ensure SoC targets are met (greedy correction)
        for target_slot, target_kwh in soc_targets:
            if target_slot < n_slots and soc_trajectory[target_slot + 1] < target_kwh:
                deficit = target_kwh - soc_trajectory[target_slot + 1]
                # Charge more in cheapest slots before the deadline
                slots_before = [(prices[t], t) for t in range(target_slot + 1) if t not in forbidden_slots]
                slots_before.sort()
                for _, t in slots_before:
                    if deficit <= 0:
                        break
                    headroom = bat.max_charge_kw - max(0.0, powers[t])
                    add_power = min(headroom, deficit / (dt_hours * bat.charge_efficiency))
                    powers[t] += add_power
                    deficit -= add_power * dt_hours * bat.charge_efficiency

        return powers

    @staticmethod
    def _time_to_slot(dt: datetime, t0: datetime, resolution_minutes: int, n_slots: int) -> int:
        delta = dt - t0
        slot = int(delta.total_seconds() / (resolution_minutes * 60))
        return max(0, min(slot, n_slots - 1))


class EVChargerConsumer(ConsumerModel):
    """EV charger consumer — charges to meet deadline SoC target at cheapest slots."""

    def __init__(self, manifest: EVChargerManifest) -> None:
        self._manifest = manifest

    @property
    def device_id(self) -> str:
        return self._manifest.device_id

    @property
    def device_type(self) -> ManifestType:
        return ManifestType.EV_CHARGER

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
        """EV: charge at cheapest slots, meet energy targets by deadline."""
        ev = self._manifest
        dt_hours = resolution_minutes / 60.0
        powers = [0.0] * n_slots

        # Determine energy target from constraints
        energy_target_kwh = 0.0
        deadline_slot = n_slots - 1
        forbidden_slots: set[int] = set()

        for cw in constraints:
            slot = self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots)
            if isinstance(cw.requirement, MinEnergyUntil):
                energy_target_kwh = max(energy_target_kwh, cw.requirement.min_energy_kwh)
                deadline_slot = min(deadline_slot, slot)
            elif isinstance(cw.requirement, MinSocUntil) and ev.battery_capacity_kwh:
                target_energy = ev.battery_capacity_kwh * cw.requirement.min_soc_pct / 100.0
                energy_target_kwh = max(energy_target_kwh, target_energy * 0.5)  # Assume 50% initial SoC
                deadline_slot = min(deadline_slot, slot)
            elif isinstance(cw.requirement, ForbiddenWindow):
                for t in range(min(slot + 1, n_slots)):
                    forbidden_slots.add(t)

        # If no target, charge minimally at cheapest times
        if energy_target_kwh == 0:
            energy_target_kwh = ev.max_charge_kw * dt_hours * 4  # 4 slots default

        # Select cheapest slots before deadline for charging
        available = [(prices[t], t) for t in range(min(deadline_slot + 1, n_slots)) if t not in forbidden_slots]
        available.sort()

        energy_delivered = 0.0
        for _, t in available:
            if energy_delivered >= energy_target_kwh:
                break
            power = ev.max_charge_kw
            energy = power * dt_hours
            if energy_delivered + energy > energy_target_kwh:
                power = (energy_target_kwh - energy_delivered) / dt_hours
            powers[t] = max(ev.min_charge_kw, power) if power > 0 else 0.0
            energy_delivered += powers[t] * dt_hours

        # Apply plan-change penalty
        if previous_power and plan_change_penalty > 0:
            damping = 1.0 / (1.0 + plan_change_penalty * 10)
            for t in range(n_slots):
                prev = previous_power[t] if t < len(previous_power) else 0.0
                change = powers[t] - prev
                powers[t] = prev + change * damping

        return powers

    @staticmethod
    def _time_to_slot(dt: datetime, t0: datetime, resolution_minutes: int, n_slots: int) -> int:
        delta = dt - t0
        slot = int(delta.total_seconds() / (resolution_minutes * 60))
        return max(0, min(slot, n_slots - 1))


class HeatPumpConsumer(ConsumerModel):
    """Heat pump consumer — runs when prices are favorable, respecting comfort."""

    def __init__(self, manifest: HeatPumpManifest, outdoor_temp_c: float = 5.0) -> None:
        self._manifest = manifest
        self._outdoor_temp_c = outdoor_temp_c

    @property
    def device_id(self) -> str:
        return self._manifest.device_id

    @property
    def device_type(self) -> ManifestType:
        return ManifestType.HEAT_PUMP

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
        """Heat pump: prefer cheap slots, respect min/max runtime constraints."""
        hp = self._manifest
        powers = [0.0] * n_slots

        # Parse constraints
        min_runtime_slots = 0
        max_runtime_slots = n_slots
        forbidden_slots: set[int] = set()

        for cw in constraints:
            slot = self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots)
            if isinstance(cw.requirement, MinRuntimePerDay):
                min_runtime_slots = max(min_runtime_slots, int(cw.requirement.min_hours * 60 / resolution_minutes))
            elif isinstance(cw.requirement, MaxRuntimePerDay):
                max_runtime_slots = min(max_runtime_slots, int(cw.requirement.max_hours * 60 / resolution_minutes))
            elif isinstance(cw.requirement, ForbiddenWindow):
                for t in range(min(slot + 1, n_slots)):
                    forbidden_slots.add(t)

        # COP-weighted effective price: lower COP → more expensive per heat unit
        cop = self._get_cop()
        effective_cost_per_heat = [p / cop for p in prices[:n_slots]]

        # Sort available slots by effective cost
        available = [(effective_cost_per_heat[t], t) for t in range(n_slots) if t not in forbidden_slots]
        available.sort()

        # Run for min_runtime_slots cheapest slots, up to max_runtime_slots
        target_slots = max(min_runtime_slots, min(max_runtime_slots, len(available) // 3))
        run_slots = set()

        for i, (_, t) in enumerate(available):
            if i >= target_slots:
                break
            run_slots.add(t)

        for t in range(n_slots):
            if t in run_slots:
                # Modulate based on price relative to average
                avg_price = sum(prices[:n_slots]) / n_slots if n_slots > 0 else 0.3
                modulation = min(1.0, max(hp.min_modulation_pct / 100.0, 1.0 - (prices[t] - avg_price) / avg_price))
                powers[t] = hp.max_power_kw * modulation
            else:
                powers[t] = 0.0

        # Apply plan-change penalty (anti short-cycling)
        if previous_power and plan_change_penalty > 0:
            damping = 1.0 / (1.0 + plan_change_penalty * 10)
            for t in range(n_slots):
                prev = previous_power[t] if t < len(previous_power) else 0.0
                change = powers[t] - prev
                powers[t] = max(0.0, prev + change * damping)

        return powers

    def _get_cop(self) -> float:
        """Get COP at current outdoor temperature."""
        cop_map = self._manifest.cop_map or [(-10, 2.5), (0, 3.5), (10, 4.5)]
        sorted_map = sorted(cop_map, key=lambda x: x[0])
        temp = self._outdoor_temp_c

        if temp <= sorted_map[0][0]:
            return sorted_map[0][1]
        if temp >= sorted_map[-1][0]:
            return sorted_map[-1][1]

        for i in range(len(sorted_map) - 1):
            t1, c1 = sorted_map[i]
            t2, c2 = sorted_map[i + 1]
            if t1 <= temp <= t2:
                ratio = (temp - t1) / (t2 - t1)
                return c1 + ratio * (c2 - c1)

        return sorted_map[-1][1]

    @staticmethod
    def _time_to_slot(dt: datetime, t0: datetime, resolution_minutes: int, n_slots: int) -> int:
        delta = dt - t0
        slot = int(delta.total_seconds() / (resolution_minutes * 60))
        return max(0, min(slot, n_slots - 1))


class WaterHeaterConsumer(ConsumerModel):
    """Water heater consumer — heats during cheap periods, respects legionella constraints."""

    def __init__(self, manifest: WaterHeaterManifest) -> None:
        self._manifest = manifest

    @property
    def device_id(self) -> str:
        return self._manifest.device_id

    @property
    def device_type(self) -> ManifestType:
        return ManifestType.WATER_HEATER

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
        """Water heater: heat at cheapest slots, ensure min energy for legionella."""
        wh = self._manifest
        dt_hours = resolution_minutes / 60.0
        powers = [0.0] * n_slots

        # Parse constraints
        min_energy_kwh = 0.0
        min_runtime_slots = 0
        forbidden_slots: set[int] = set()

        for cw in constraints:
            slot = self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots)
            if isinstance(cw.requirement, MinEnergyUntil):
                min_energy_kwh = max(min_energy_kwh, cw.requirement.min_energy_kwh)
            elif isinstance(cw.requirement, MinRuntimePerDay):
                min_runtime_slots = max(min_runtime_slots, int(cw.requirement.min_hours * 60 / resolution_minutes))
            elif isinstance(cw.requirement, ForbiddenWindow):
                for t in range(min(slot + 1, n_slots)):
                    forbidden_slots.add(t)

        # Default: run enough to maintain temperature (standby loss compensation)
        if min_energy_kwh == 0:
            # Compensate standby loss over the horizon
            loss_kwh = wh.standby_loss_w / 1000.0 * (n_slots * resolution_minutes / 60.0)
            min_energy_kwh = loss_kwh

        # Select cheapest slots
        available = [(prices[t], t) for t in range(n_slots) if t not in forbidden_slots]
        available.sort()

        energy_delivered = 0.0
        slots_used = 0
        for _, t in available:
            if energy_delivered >= min_energy_kwh and slots_used >= min_runtime_slots:
                break
            powers[t] = wh.max_power_kw
            energy_delivered += wh.max_power_kw * dt_hours
            slots_used += 1  # noqa: SIM113

        # Apply plan-change penalty
        if previous_power and plan_change_penalty > 0:
            damping = 1.0 / (1.0 + plan_change_penalty * 10)
            for t in range(n_slots):
                prev = previous_power[t] if t < len(previous_power) else 0.0
                change = powers[t] - prev
                powers[t] = max(0.0, prev + change * damping)

        return powers

    @staticmethod
    def _time_to_slot(dt: datetime, t0: datetime, resolution_minutes: int, n_slots: int) -> int:
        delta = dt - t0
        slot = int(delta.total_seconds() / (resolution_minutes * 60))
        return max(0, min(slot, n_slots - 1))


class ThermostatConsumer(ConsumerModel):
    """Thermostat load consumer — binary on/off, prefers cheap slots."""

    def __init__(self, manifest: ThermostatLoadManifest) -> None:
        self._manifest = manifest

    @property
    def device_id(self) -> str:
        return self._manifest.device_id

    @property
    def device_type(self) -> ManifestType:
        return ManifestType.THERMOSTAT_LOAD

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
        """Thermostat: allow heating in cheapest slots, respect min/max runtime."""
        thermo = self._manifest
        powers = [0.0] * n_slots

        # Parse constraints
        min_runtime_slots = 0
        max_runtime_slots = n_slots
        forbidden_slots: set[int] = set()

        for cw in constraints:
            slot = self._time_to_slot(cw.deadline, t0, resolution_minutes, n_slots)
            if isinstance(cw.requirement, MinRuntimePerDay):
                min_runtime_slots = max(min_runtime_slots, int(cw.requirement.min_hours * 60 / resolution_minutes))
            elif isinstance(cw.requirement, MaxRuntimePerDay):
                max_runtime_slots = min(max_runtime_slots, int(cw.requirement.max_hours * 60 / resolution_minutes))
            elif isinstance(cw.requirement, ForbiddenWindow):
                for t in range(min(slot + 1, n_slots)):
                    forbidden_slots.add(t)

        # Default: run for ~30% of slots
        target_slots = max(min_runtime_slots, min(max_runtime_slots, n_slots // 3))

        # Sort available by price
        available = [(prices[t], t) for t in range(n_slots) if t not in forbidden_slots]
        available.sort()

        run_slots: set[int] = set()
        for i, (_, t) in enumerate(available):
            if i >= target_slots:
                break
            run_slots.add(t)

        for t in range(n_slots):
            powers[t] = thermo.max_power_kw if t in run_slots else 0.0

        # Apply plan-change penalty
        if previous_power and plan_change_penalty > 0:
            damping = 1.0 / (1.0 + plan_change_penalty * 10)
            for t in range(n_slots):
                prev = previous_power[t] if t < len(previous_power) else 0.0
                change = powers[t] - prev
                powers[t] = max(0.0, prev + change * damping)

        return powers

    @staticmethod
    def _time_to_slot(dt: datetime, t0: datetime, resolution_minutes: int, n_slots: int) -> int:
        delta = dt - t0
        slot = int(delta.total_seconds() / (resolution_minutes * 60))
        return max(0, min(slot, n_slots - 1))


class PVForecastConsumer(ConsumerModel):
    """PV forecast consumer — produces power based on forecast (negative = generation)."""

    def __init__(self, manifest: PVForecastManifest) -> None:
        self._manifest = manifest

    @property
    def device_id(self) -> str:
        return self._manifest.device_id

    @property
    def device_type(self) -> ManifestType:
        return ManifestType.PV_FORECAST

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
        """PV: generate synthetic solar curve (negative power = production)."""
        pv = self._manifest
        powers = [0.0] * n_slots

        for t in range(n_slots):
            slot_start = t0 + timedelta(minutes=t * resolution_minutes)
            hour = slot_start.hour + slot_start.minute / 60.0
            # Solar bell curve centered at noon
            solar_factor = max(0.0, math.cos((hour - 12) * math.pi / 12)) ** 2
            # Only produce during daylight (6-18)
            if 6 <= hour <= 18:
                powers[t] = -pv.peak_power_kwp * solar_factor * 0.8  # 80% typical yield
            else:
                powers[t] = 0.0

        return powers


class RoomConsumer(ConsumerModel):
    """Room consumer — passive thermal model, no direct power decision.

    The room does not consume power directly but influences heat pump/thermostat
    decisions through its thermal characteristics.
    Returns zero power (room is a thermal zone, not an actuator).
    """

    def __init__(self, manifest: RoomManifest) -> None:
        self._manifest = manifest

    @property
    def device_id(self) -> str:
        return self._manifest.device_id

    @property
    def device_type(self) -> ManifestType:
        return ManifestType.ROOM

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
        """Room: no direct power — returns zeros."""
        return [0.0] * n_slots


class PassiveLoadConsumer(ConsumerModel):
    """Passive load consumer — fixed consumption profile, not steerable.

    Distributes the typical daily kWh evenly across all slots as a fixed
    positive power draw.  The solver cannot optimize this — it just appears
    in the power balance as unavoidable consumption.
    """

    def __init__(self, manifest: PassiveLoadManifest) -> None:
        self._manifest = manifest

    @property
    def device_id(self) -> str:
        return self._manifest.device_id

    @property
    def device_type(self) -> ManifestType:
        return ManifestType.PASSIVE_LOAD

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
        """Passive load: return flat power curve based on typical daily consumption."""
        horizon_hours = n_slots * resolution_minutes / 60.0
        daily_fraction = horizon_hours / 24.0
        total_kwh = self._manifest.typical_daily_kwh * daily_fraction
        power_kw = total_kwh / horizon_hours if horizon_hours > 0 else 0.0
        return [power_kw] * n_slots


def get_consumer_model(manifest: Any, outdoor_temp_c: float = 5.0) -> ConsumerModel | None:
    """Factory: create the appropriate consumer model for a manifest.

    Args:
        manifest: Device manifest.
        outdoor_temp_c: Outdoor temperature (for heat pump COP).

    Returns:
        ConsumerModel instance, or None for unsupported types.
    """
    if isinstance(manifest, BatteryManifest):
        return BatteryConsumer(manifest)
    if isinstance(manifest, EVChargerManifest):
        return EVChargerConsumer(manifest)
    if isinstance(manifest, HeatPumpManifest):
        return HeatPumpConsumer(manifest, outdoor_temp_c=outdoor_temp_c)
    if isinstance(manifest, WaterHeaterManifest):
        return WaterHeaterConsumer(manifest)
    if isinstance(manifest, ThermostatLoadManifest):
        return ThermostatConsumer(manifest)
    if isinstance(manifest, PVForecastManifest):
        return PVForecastConsumer(manifest)
    if isinstance(manifest, RoomManifest):
        return RoomConsumer(manifest)
    if isinstance(manifest, PassiveLoadManifest):
        return PassiveLoadConsumer(manifest)
    return None
