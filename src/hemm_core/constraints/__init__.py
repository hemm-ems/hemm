"""Constraint-window management — tracks active constraint windows in core."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

from hemm_core.manifest.messages import ConstraintWindow
from hemm_core.time import Clock, WallClock


class ConstraintWindowManager:
    """Manages active constraint windows.

    Provides add, remove, expire, and query operations for the solver.
    """

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._windows: dict[str, ConstraintWindow] = {}
        self._clock: Clock = clock if clock is not None else WallClock()

    def add(self, window: ConstraintWindow) -> None:
        """Add a constraint window.

        If a window with the same ID exists, it is replaced.
        """
        if window.created_at is None:
            window = window.model_copy(update={"created_at": self._clock.now()})
        self._windows[window.window_id] = window

    def remove(self, window_id: str) -> ConstraintWindow | None:
        """Remove a constraint window by ID.

        Returns:
            The removed window, or None if not found.
        """
        return self._windows.pop(window_id, None)

    def get(self, window_id: str) -> ConstraintWindow | None:
        """Get a constraint window by ID."""
        return self._windows.get(window_id)

    def get_active(self, now: datetime | None = None) -> list[ConstraintWindow]:
        """Get all currently active (non-expired) constraint windows.

        Windows are expired if:
        - Their deadline has passed, OR
        - Their TTL has expired (created_at + ttl_seconds < now)

        Args:
            now: Current time (defaults to the injected clock).

        Returns:
            List of active windows, sorted by priority_penalty descending.
        """
        if now is None:
            now = self._clock.now()

        active: list[ConstraintWindow] = []
        for window in self._windows.values():
            if self._is_expired(window, now):
                continue
            active.append(window)

        # Sort by priority: higher penalty = higher priority
        active.sort(key=lambda w: w.priority_penalty, reverse=True)
        return active

    def expire_old(self, now: datetime | None = None) -> list[str]:
        """Remove expired windows and return their IDs.

        Args:
            now: Current time (defaults to the injected clock).

        Returns:
            List of expired window IDs that were removed.
        """
        if now is None:
            now = self._clock.now()

        expired_ids: list[str] = []
        for wid, window in list(self._windows.items()):
            if self._is_expired(window, now):
                expired_ids.append(wid)
                del self._windows[wid]
        return expired_ids

    def get_for_device(self, device_id: str, now: datetime | None = None) -> list[ConstraintWindow]:
        """Get active constraint windows for a specific device."""
        return [w for w in self.get_active(now) if w.device_id == device_id]

    def bump_priority(self, window_id: str, new_penalty: float) -> bool:
        """Update the priority penalty for a constraint window.

        Returns:
            True if the window was found and updated, False otherwise.
        """
        window = self._windows.get(window_id)
        if window is None:
            return False
        self._windows[window_id] = window.model_copy(update={"priority_penalty": new_penalty})
        return True

    @property
    def count(self) -> int:
        """Number of managed windows (including expired)."""
        return len(self._windows)

    def __iter__(self) -> Iterator[ConstraintWindow]:
        return iter(self._windows.values())

    def __len__(self) -> int:
        return len(self._windows)

    def clear(self) -> None:
        """Remove all constraint windows."""
        self._windows.clear()

    def _is_expired(self, window: ConstraintWindow, now: datetime) -> bool:
        """Check if a window is expired."""
        # Deadline passed
        if window.deadline <= now:
            return True
        # TTL expired
        if window.ttl_seconds is not None and window.created_at is not None:
            expiry = window.created_at + timedelta(seconds=window.ttl_seconds)
            if expiry <= now:
                return True
        return False
