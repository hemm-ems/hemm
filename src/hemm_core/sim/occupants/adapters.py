"""Household profile adapter registry."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hemm_core.sim.occupants.overlay import apply_calendar_overlay
from hemm_core.sim.occupants.profile import HouseholdProfile, read_profile
from hemm_core.sim.occupants.synthetic import generate_synthetic_profile

ProfileAdapter = Callable[[dict[str, Any], Path, datetime, int, int], HouseholdProfile]


def load_household_profile(
    household: dict[str, Any],
    *,
    base_dir: Path,
    default_start: datetime,
    horizon_hours: int,
    resolution_minutes: int,
) -> HouseholdProfile:
    """Load and overlay a household profile from a scenario block."""
    adapter_name = str(household.get("adapter", "synthetic"))
    start = _scenario_start(household, default_start)
    adapter = _ADAPTERS.get(adapter_name)
    if adapter is None:
        msg = f"Unknown household adapter: {adapter_name}"
        raise ValueError(msg)
    profile = adapter(household, base_dir, start, horizon_hours, resolution_minutes)
    profile = apply_calendar_overlay(profile, household.get("calendar"))
    return profile.slice(start, horizon_hours)


def register_adapter(name: str, adapter: ProfileAdapter) -> None:
    _ADAPTERS[name] = adapter


def synthetic_adapter(
    household: dict[str, Any], _base_dir: Path, start: datetime, horizon_hours: int, resolution_minutes: int
) -> HouseholdProfile:
    return generate_synthetic_profile(
        archetype=str(household.get("archetype", "family4")),
        seed=int(household.get("seed", 17)),
        start=start,
        hours=horizon_hours,
        resolution_minutes=resolution_minutes,
    )


def file_adapter(
    household: dict[str, Any], base_dir: Path, _start: datetime, _horizon_hours: int, resolution_minutes: int
) -> HouseholdProfile:
    raw = household.get("path") or household.get("profile")
    if not raw:
        msg = "csv/parquet household adapters require 'path' or 'profile'"
        raise ValueError(msg)
    path = Path(str(raw))
    if not path.is_absolute():
        path = base_dir / path
    return read_profile(path, resolution_minutes=resolution_minutes)


def lpg_adapter(
    household: dict[str, Any], base_dir: Path, start: datetime, horizon_hours: int, resolution_minutes: int
) -> HouseholdProfile:
    """Load a baked LPG profile, falling back to synthetic only when explicitly allowed."""
    raw = household.get("path") or household.get("profile")
    if raw:
        path = Path(str(raw))
        if not path.is_absolute():
            path = base_dir / path
        return read_profile(path, resolution_minutes=resolution_minutes)
    if household.get("allow_synthetic_fallback", False):
        return synthetic_adapter(household, base_dir, start, horizon_hours, resolution_minutes)
    msg = "lpg household scenarios require a baked profile path; use bake-profile first"
    raise ValueError(msg)


def _scenario_start(household: dict[str, Any], default_start: datetime) -> datetime:
    raw = household.get("start")
    if raw is None:
        return default_start.astimezone(UTC)
    text = str(raw)
    if len(text) == 10:
        return datetime.fromisoformat(text).replace(tzinfo=UTC)
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


_ADAPTERS: dict[str, ProfileAdapter] = {
    "synthetic": synthetic_adapter,
    "csv": file_adapter,
    "parquet": file_adapter,
    "replay_history": file_adapter,
    "lpg": lpg_adapter,
}
