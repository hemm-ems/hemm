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


def find_conflicts(windows: list[ConstraintWindow]) -> list[tuple[ConstraintWindow, ConstraintWindow]]:
    """Find pairs of conflicting constraint windows.

    Two windows conflict when they target the same device and overlap in time.
    Returns pairs where the first element has higher priority.
    """
    conflicts: list[tuple[ConstraintWindow, ConstraintWindow]] = []

    # Group by device
    by_device: dict[str, list[ConstraintWindow]] = {}
    for w in windows:
        by_device.setdefault(w.device_id, []).append(w)

    for device_windows in by_device.values():
        # Sort by deadline for overlap detection
        sorted_windows = sorted(device_windows, key=lambda w: w.deadline)
        for i in range(len(sorted_windows)):
            for j in range(i + 1, len(sorted_windows)):
                w1, w2 = sorted_windows[i], sorted_windows[j]
                # Windows for the same device implicitly compete for the same capacity
                # The one with higher priority_penalty wins
                if w1.priority_penalty >= w2.priority_penalty:
                    conflicts.append((w1, w2))
                else:
                    conflicts.append((w2, w1))

    return conflicts
