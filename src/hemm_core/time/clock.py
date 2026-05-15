"""Clock protocol and implementations."""

from __future__ import annotations

import time as _time
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """A source of `now()` and `monotonic()` readings.

    Every component in core that needs the current time receives a `Clock`
    via constructor injection. The default is `WallClock`, which preserves
    pre-existing behavior. Tests inject `FixedClock`; the time-warp simulator
    injects `VirtualClock`.
    """

    def now(self) -> datetime:
        """Return the current instant as a tz-aware UTC datetime."""
        ...

    def monotonic(self) -> float:
        """Return a monotonic timestamp in seconds (for elapsed-time metrics)."""
        ...


class WallClock:
    """Real wall-clock implementation. Default for production code."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)

    def monotonic(self) -> float:
        return _time.monotonic()


class FixedClock:
    """Returns the same instant every call.

    `monotonic()` reads also return a fixed value, so elapsed-time deltas
    computed inside one solver call evaluate to zero. Suitable for unit tests
    that need deterministic timestamps without manual advancement.
    """

    def __init__(self, now: datetime, monotonic: float = 0.0) -> None:
        if now.tzinfo is None:
            msg = "FixedClock requires a tz-aware datetime (use tz=UTC)."
            raise ValueError(msg)
        self._now = now.astimezone(UTC)
        self._monotonic = monotonic

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic


class VirtualClock:
    """Manually advanced clock for the time-warp simulator.

    Both `now()` and `monotonic()` progress only via `advance()`. This makes
    every time read deterministic and decouples simulated time from
    wall-clock — required for 1000x real-time-factor playback.
    """

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            msg = "VirtualClock requires a tz-aware start (use tz=UTC)."
            raise ValueError(msg)
        self._now = start.astimezone(UTC)
        # `monotonic` is synthesized from cumulative advances. We start at 0
        # so two runs of a sim with the same scenario produce identical
        # `solve_time_seconds` field traces (zero, because the virtual clock
        # does not advance inside a single solver invocation).
        self._elapsed = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._elapsed

    def advance(self, delta: timedelta) -> None:
        """Advance simulated time by `delta`."""
        if delta.total_seconds() < 0:
            msg = "VirtualClock cannot move backwards."
            raise ValueError(msg)
        self._now = self._now + delta
        self._elapsed += delta.total_seconds()
