"""Calendar overlays for occupant profiles."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Any

from hemm_core.sim.occupants.profile import HouseholdProfile


def apply_calendar_overlay(profile: HouseholdProfile, calendar: dict[str, Any] | None) -> HouseholdProfile:
    """Apply deterministic calendar overlays in fixed order."""
    if not calendar:
        return profile
    slots = list(profile.slots)
    vacation_ranges = [_parse_range(v) for v in calendar.get("vacation", [])]
    sick_days = {_parse_date(v) for v in calendar.get("sick_days", [])}
    wfh_days = {str(v).lower()[:3] for v in calendar.get("wfh_days", [])}

    transformed = []
    for slot in slots:
        local_date = slot.timestamp.date()
        weekday = slot.timestamp.strftime("%a").lower()[:3]
        if any(start <= local_date <= end for start, end in vacation_ranges):
            transformed.append(
                replace(
                    slot,
                    presence=0,
                    electric_baseload_w=min(slot.electric_baseload_w, 170.0),
                    electric_appliances_w=0.0,
                    appliance_events=[],
                    dhw_draw_l_per_min=0.0,
                    internal_gains_w=0.0,
                )
            )
        elif local_date in sick_days:
            transformed.append(
                replace(slot, presence=max(slot.presence, 1), internal_gains_w=slot.internal_gains_w + 90.0)
            )
        elif weekday in wfh_days and 8 <= slot.timestamp.hour < 17:
            transformed.append(
                replace(
                    slot,
                    presence=max(slot.presence, 1),
                    electric_baseload_w=slot.electric_baseload_w + 120.0,
                    internal_gains_w=slot.internal_gains_w + 160.0,
                )
            )
        else:
            transformed.append(slot)
    return profile.with_slots(transformed, source_suffix="calendar")


def _parse_range(raw: str) -> tuple[date, date]:
    start, end = str(raw).split("..", 1)
    return _parse_date(start), _parse_date(end)


def _parse_date(raw: object) -> date:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    return datetime.fromisoformat(str(raw)).date()
