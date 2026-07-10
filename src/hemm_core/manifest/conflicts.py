"""Conflict resolution for overlapping constraint windows."""

from __future__ import annotations

from hemm_core.manifest.messages import ConstraintWindow


def resolve_conflicts(windows: list[ConstraintWindow]) -> list[ConstraintWindow]:
    """Resolve conflicts between overlapping constraint windows.

    When multiple windows demand capacity simultaneously, the higher
    priority_penalty wins. Returns windows sorted by priority (highest first).

    Windows that do not overlap are all kept. For overlapping windows targeting
    the same device, the one with the higher priority_penalty takes precedence.
    """
    if not windows:
        return []

    # Sort by priority_penalty descending (higher penalty = higher priority)
    return sorted(windows, key=lambda w: w.priority_penalty, reverse=True)


def _overlaps(w1: ConstraintWindow, w2: ConstraintWindow) -> bool:
    """Whether two windows' active intervals overlap.

    A window is active over ``[created_at, deadline]`` (a missing ``created_at`` is
    treated as unbounded-early). Two intervals overlap iff each starts before the
    other ends.
    """
    s1, s2 = w1.created_at, w2.created_at
    return (s1 is None or s1 < w2.deadline) and (s2 is None or s2 < w1.deadline)


def find_conflicts(windows: list[ConstraintWindow]) -> list[tuple[ConstraintWindow, ConstraintWindow]]:
    """Find pairs of conflicting constraint windows.

    Two windows conflict when they target the same device *and* their active intervals
    (``[created_at, deadline]``) overlap — same-device windows separated in time do not
    compete for the same capacity. Returns pairs where the first element has the higher
    priority (``priority_penalty``).
    """
    conflicts: list[tuple[ConstraintWindow, ConstraintWindow]] = []

    # Group by device
    by_device: dict[str, list[ConstraintWindow]] = {}
    for w in windows:
        by_device.setdefault(w.device_id, []).append(w)

    for device_windows in by_device.values():
        sorted_windows = sorted(device_windows, key=lambda w: w.deadline)
        for i in range(len(sorted_windows)):
            for j in range(i + 1, len(sorted_windows)):
                w1, w2 = sorted_windows[i], sorted_windows[j]
                if not _overlaps(w1, w2):
                    continue
                # The window with the higher priority_penalty wins the conflict.
                if w1.priority_penalty >= w2.priority_penalty:
                    conflicts.append((w1, w2))
                else:
                    conflicts.append((w2, w1))

    return conflicts
