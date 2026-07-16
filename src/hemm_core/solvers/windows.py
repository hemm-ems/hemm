"""Shared constraint-window applicability partition (FR-206).

Both backends must agree on which windows apply to a solve, or A/B
comparisons diverge. Impossible deadlines are rejected and surfaced —
never silently clamped into the horizon.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from hemm_core.manifest.constraints import (
    MinEnergyUntil,
    MinRuntimePerDay,
    MinSocUntil,
    ReachMinTempOnce,
)
from hemm_core.manifest.messages import ConstraintWindow

_LOGGER = logging.getLogger(__name__)

# Demand-type requirements pull work forward when their deadline is clamped into
# the horizon, so an out-of-view deadline must be surfaced, never applied early.
# Restrictive requirements (forbidden window, max runtime, comfort band) truncate
# safely at the horizon edge and stay applied.
_DEMAND_REQUIREMENTS = (MinSocUntil, MinEnergyUntil, MinRuntimePerDay, ReachMinTempOnce)


def partition_constraint_windows(
    constraint_windows: list[ConstraintWindow],
    known_device_ids: set[str],
    t0: datetime,
    horizon_minutes: int,
) -> tuple[list[ConstraintWindow], list[dict[str, str]]]:
    """Split windows into applicable ones and surfaced rejects (FR-206)."""
    applied: list[ConstraintWindow] = []
    ignored: list[dict[str, str]] = []
    horizon_end = t0 + timedelta(minutes=horizon_minutes)
    for cw in constraint_windows:
        reason: str | None = None
        if cw.device_id not in known_device_ids:
            reason = "unknown_device"
        elif cw.deadline < t0:
            reason = "deadline_in_past"
        elif cw.deadline > horizon_end and isinstance(cw.requirement, _DEMAND_REQUIREMENTS):
            reason = "deadline_beyond_horizon"
        if reason is None:
            applied.append(cw)
            continue
        _LOGGER.warning(
            "Ignoring constraint window '%s' (device '%s', requirement '%s'): %s",
            cw.window_id,
            cw.device_id,
            cw.requirement.type,
            reason,
        )
        ignored.append(
            {
                "window_id": cw.window_id,
                "device_id": cw.device_id,
                "requirement": str(cw.requirement.type),
                "reason": reason,
            }
        )
    return applied, ignored
