"""Time abstraction — single source for `now()` reads across HEMM.

Domain code must NOT call `datetime.now`, `datetime.utcnow`, `time.time`, or
`time.monotonic` directly. Inject a `Clock` instead. The `check_clock` audit
(`hemm/tools/check_clock.py`) enforces this.

Three implementations:

- `WallClock` — default; wraps real wall-clock time. Behavior identical to
  pre-Clock code.
- `FixedClock` — returns the same instant every call. Use in unit tests.
- `VirtualClock` — manually advanced; for the time-warp simulator. `now()` and
  `monotonic()` both progress only via `.advance(delta)`.
"""

from __future__ import annotations

from hemm_core.time.clock import Clock, FixedClock, VirtualClock, WallClock

__all__ = ["Clock", "FixedClock", "VirtualClock", "WallClock"]
