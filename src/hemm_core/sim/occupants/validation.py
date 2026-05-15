"""Profile plausibility validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from hemm_core.sim.occupants.profile import ApplianceEvent, HouseholdProfile


@dataclass(frozen=True)
class ResourceConflict:
    """A structured resource conflict in an occupant profile."""

    resource: str
    capacity: float
    slot: datetime
    events: list[str]
    cause: str = ""

    def message(self) -> str:
        return (
            f"{self.resource} capacity {self.capacity:g} exceeded at {self.slot.isoformat()}: {', '.join(self.events)}"
        )


def validate_profile(
    profile: HouseholdProfile,
    resources: dict[str, float] | None = None,
    *,
    cause: str = "",
) -> list[ResourceConflict]:
    """Validate resource usage with a linear scan over generated events."""
    caps = resources or default_resources(profile.archetype)
    conflicts: list[ResourceConflict] = []
    for slot in profile.slots:
        usage: dict[str, float] = {}
        users: dict[str, list[str]] = {}
        for event in _active_events(profile, slot.timestamp):
            for resource, amount in _event_resource_use(event):
                usage[resource] = usage.get(resource, 0.0) + amount
                users.setdefault(resource, []).append(event.appliance)
        for resource, amount in usage.items():
            cap = caps.get(resource)
            if cap is not None and amount > cap:
                conflicts.append(
                    ResourceConflict(
                        resource=resource,
                        capacity=cap,
                        slot=slot.timestamp,
                        events=users.get(resource, []),
                        cause=cause,
                    )
                )
    return conflicts


def default_resources(archetype: str) -> dict[str, float]:
    caps = {
        "bathroom": 1.0,
        "shower_flow_lpm": 9.0,
        "dishwasher": 1.0,
        "washing_machine": 1.0,
        "kitchen_oven": 1.0,
        "ev_plug": 1.0,
    }
    if archetype == "family4":
        caps["bathroom"] = 1.0
    return caps


def _active_events(profile: HouseholdProfile, slot_start: datetime) -> list[ApplianceEvent]:
    slot_end = slot_start + timedelta(minutes=profile.resolution_minutes)
    active: list[ApplianceEvent] = []
    for slot in profile.slots:
        for event in slot.appliance_events:
            duration = max(event.duration_minutes, profile.resolution_minutes)
            event_end = event.start + timedelta(minutes=duration)
            if event.start < slot_end and event_end > slot_start:
                active.append(event)
    return active


def _event_resource_use(event: ApplianceEvent) -> list[tuple[str, float]]:
    uses: list[tuple[str, float]] = []
    for raw in event.resource_use:
        if ":" in raw:
            resource, amount = raw.split(":", 1)
            uses.append((resource, float(amount)))
        else:
            uses.append((raw, 1.0))
    return uses
