"""Deterministic synthetic occupant profile generation."""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime, timedelta

from hemm_core.sim.occupants.profile import ApplianceEvent, HouseholdProfile, HouseholdSlot

_ARCHETYPES: dict[str, dict[str, float | int]] = {
    "single_worker": {"occupants": 1, "base_w": 180, "electronics_w": 120},
    "working_couple": {"occupants": 2, "base_w": 260, "electronics_w": 180},
    "family4": {"occupants": 4, "base_w": 420, "electronics_w": 260},
    "wfh_techie": {"occupants": 1, "base_w": 260, "electronics_w": 420},
    "retired_couple": {"occupants": 2, "base_w": 300, "electronics_w": 180},
}


def generate_synthetic_profile(
    *,
    archetype: str = "family4",
    seed: int = 17,
    start: datetime,
    hours: int,
    resolution_minutes: int = 15,
) -> HouseholdProfile:
    """Generate a deterministic, plausible household demand profile."""
    start = _ensure_utc(start)
    params = _ARCHETYPES.get(archetype, _ARCHETYPES["family4"])
    occupants = int(params["occupants"])
    base_w = float(params["base_w"])
    electronics_w = float(params["electronics_w"])
    rng = random.Random(_stable_seed(archetype, seed, start.year))

    n_slots = hours * 60 // resolution_minutes
    slots: list[HouseholdSlot] = []
    for i in range(n_slots):
        ts = start + timedelta(minutes=i * resolution_minutes)
        hour = ts.hour + ts.minute / 60.0
        presence = _presence(archetype, occupants, ts)
        appliances_w = _appliance_power(archetype, hour, ts.weekday(), rng)
        dhw_lpm = _dhw_draw(archetype, hour, occupants)
        gains_w = presence * 90.0 + appliances_w * 0.35 + (electronics_w if presence else 0.0)
        base_noise = rng.uniform(-20, 20)
        events = _events_for_slot(archetype, ts, occupants)
        slots.append(
            HouseholdSlot(
                timestamp=ts,
                presence=presence,
                electric_baseload_w=max(80.0, base_w + base_noise + (electronics_w * 0.25 if presence else 0.0)),
                electric_appliances_w=appliances_w,
                appliance_events=events,
                dhw_draw_l_per_min=dhw_lpm,
                internal_gains_w=gains_w,
            )
        )

    return HouseholdProfile(
        slots=slots,
        resolution_minutes=resolution_minutes,
        source="synthetic",
        archetype=archetype,
        seed=seed,
        metadata={"generator": "hemm.synthetic.v1"},
    )


def _presence(archetype: str, occupants: int, ts: datetime) -> int:
    hour = ts.hour + ts.minute / 60.0
    weekday = ts.weekday()
    weekend = weekday >= 5
    if archetype == "wfh_techie":
        return occupants if 7 <= hour <= 23 else max(0, occupants - 1)
    if archetype == "retired_couple":
        return occupants if 6 <= hour <= 23 else 1
    if weekend:
        return occupants if 7 <= hour <= 23 else 0
    if archetype == "single_worker":
        return 0 if 8 <= hour < 17 else occupants
    if archetype == "working_couple":
        return 0 if 8 <= hour < 17 else occupants
    if archetype == "family4":
        if 8 <= hour < 14:
            return 0
        if 14 <= hour < 17:
            return 2
        return occupants if 6 <= hour <= 23 else 0
    return occupants


def _appliance_power(archetype: str, hour: float, weekday: int, rng: random.Random) -> float:
    cooking = 900.0 if 18.0 <= hour < 19.5 else 0.0
    breakfast = 350.0 if 7.0 <= hour < 8.0 else 0.0
    laundry = 650.0 if weekday in (1, 5) and 10 <= hour < 12 else 0.0
    dishwasher = 500.0 if 21.0 <= hour < 22.5 else 0.0
    family_extra = 220.0 if archetype == "family4" and 15 <= hour < 20 else 0.0
    return max(0.0, cooking + breakfast + laundry + dishwasher + family_extra + rng.uniform(-35, 35))


def _dhw_draw(archetype: str, hour: float, occupants: int) -> float:
    morning = 2.1 if 6.5 <= hour < 7.5 else 0.0
    evening = 1.4 if 20.0 <= hour < 21.0 else 0.0
    cooking = 0.35 if 18.0 <= hour < 19.5 else 0.0
    family = 0.8 if archetype == "family4" and 7.0 <= hour < 8.0 else 0.0
    return (morning + evening + cooking + family) * max(1, occupants) / 2.0


def _events_for_slot(archetype: str, ts: datetime, occupants: int) -> list[ApplianceEvent]:
    events: list[ApplianceEvent] = []
    if ts.hour == 7 and ts.minute == 0:
        events.append(
            ApplianceEvent(
                appliance="shower",
                start=ts,
                duration_minutes=8,
                resource_use=["bathroom", "shower_flow_lpm:9"],
            )
        )
    if ts.hour == 21 and ts.minute == 0:
        events.append(
            ApplianceEvent(
                appliance="dishwasher",
                start=ts,
                energy_kwh=1.2,
                deadline_default=ts.replace(hour=23, minute=0),
                duration_minutes=90,
                resource_use=["dishwasher"],
                device_id="kitchen_loads",
            )
        )
    if archetype == "family4" and occupants >= 4 and ts.weekday() in (1, 5) and ts.hour == 10 and ts.minute == 0:
        events.append(
            ApplianceEvent(
                appliance="washer",
                start=ts,
                energy_kwh=0.8,
                deadline_default=ts.replace(hour=17, minute=0),
                duration_minutes=120,
                resource_use=["washing_machine"],
                device_id="kitchen_loads",
            )
        )
    return events


def _stable_seed(archetype: str, seed: int, year: int) -> int:
    data = f"{archetype}:{seed}:{year}".encode()
    return int.from_bytes(hashlib.sha256(data).digest()[:8], "big")


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
