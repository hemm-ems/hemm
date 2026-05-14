"""Tests for the `hemm.time` Clock abstraction and its retrofit into core."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hemm.constraints import ConstraintWindowManager
from hemm.manifest.constraints import MinSocUntil
from hemm.manifest.messages import ConstraintWindow
from hemm.sim.synthetic import generate_price_series
from hemm.time import Clock, FixedClock, VirtualClock, WallClock


class TestClockImpls:
    @pytest.mark.unit
    def test_wallclock_now_is_tz_aware(self) -> None:
        c = WallClock()
        assert c.now().tzinfo is not None
        assert c.monotonic() > 0.0

    @pytest.mark.unit
    def test_wallclock_satisfies_protocol(self) -> None:
        assert isinstance(WallClock(), Clock)
        assert isinstance(FixedClock(datetime(2026, 1, 1, tzinfo=UTC)), Clock)
        assert isinstance(VirtualClock(datetime(2026, 1, 1, tzinfo=UTC)), Clock)

    @pytest.mark.unit
    def test_fixed_clock_returns_same_instant(self) -> None:
        instant = datetime(2026, 5, 12, 10, 0, tzinfo=UTC)
        c = FixedClock(instant)
        assert c.now() == instant
        assert c.now() == instant
        assert c.monotonic() == 0.0

    @pytest.mark.unit
    def test_fixed_clock_requires_tz_aware(self) -> None:
        with pytest.raises(ValueError, match="tz-aware"):
            FixedClock(datetime(2026, 5, 12, 10, 0))

    @pytest.mark.unit
    def test_virtual_clock_advance(self) -> None:
        start = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)
        c = VirtualClock(start)
        assert c.now() == start
        assert c.monotonic() == 0.0
        c.advance(timedelta(hours=1))
        assert c.now() == start + timedelta(hours=1)
        assert c.monotonic() == 3600.0
        c.advance(timedelta(minutes=30))
        assert c.now() == start + timedelta(hours=1, minutes=30)
        assert c.monotonic() == 3600.0 + 1800.0

    @pytest.mark.unit
    def test_virtual_clock_rejects_negative_advance(self) -> None:
        c = VirtualClock(datetime(2026, 5, 12, tzinfo=UTC))
        with pytest.raises(ValueError, match="backwards"):
            c.advance(timedelta(seconds=-1))

    @pytest.mark.unit
    def test_virtual_clock_requires_tz_aware(self) -> None:
        with pytest.raises(ValueError, match="tz-aware"):
            VirtualClock(datetime(2026, 5, 12, 0, 0))


class TestConstraintManagerClockInjection:
    """The Clock retrofit's load-bearing contract."""

    @pytest.mark.unit
    def test_created_at_uses_injected_clock(self) -> None:
        instant = datetime(2026, 5, 12, 10, 0, tzinfo=UTC)
        mgr = ConstraintWindowManager(clock=FixedClock(instant))
        w = ConstraintWindow(
            window_id="w1",
            device_id="dev1",
            deadline=instant + timedelta(hours=12),
            requirement=MinSocUntil(min_soc_pct=80),
            priority_penalty=1.0,
        )
        mgr.add(w)
        stored = mgr.get("w1")
        assert stored is not None
        assert stored.created_at == instant

    @pytest.mark.unit
    def test_get_active_default_uses_injected_clock(self) -> None:
        # Set clock between deadline of "expired" and "active".
        clock_time = datetime(2026, 5, 12, 12, 0, tzinfo=UTC)
        mgr = ConstraintWindowManager(clock=FixedClock(clock_time))
        # Window deadline 1h in the past
        mgr.add(
            ConstraintWindow(
                window_id="expired",
                device_id="dev1",
                deadline=clock_time - timedelta(hours=1),
                requirement=MinSocUntil(min_soc_pct=80),
                priority_penalty=1.0,
            )
        )
        # Window deadline 1h in the future
        mgr.add(
            ConstraintWindow(
                window_id="active",
                device_id="dev1",
                deadline=clock_time + timedelta(hours=1),
                requirement=MinSocUntil(min_soc_pct=80),
                priority_penalty=1.0,
            )
        )
        active = mgr.get_active()  # no `now=` -> uses injected clock
        assert [w.window_id for w in active] == ["active"]

    @pytest.mark.unit
    def test_virtual_clock_drives_expiration(self) -> None:
        start = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)
        clock = VirtualClock(start)
        mgr = ConstraintWindowManager(clock=clock)
        mgr.add(
            ConstraintWindow(
                window_id="short",
                device_id="dev1",
                deadline=start + timedelta(hours=2),
                requirement=MinSocUntil(min_soc_pct=80),
                priority_penalty=1.0,
            )
        )
        assert len(mgr.get_active()) == 1
        clock.advance(timedelta(hours=3))
        assert len(mgr.get_active()) == 0
        expired = mgr.expire_old()
        assert expired == ["short"]


class TestSyntheticUsesInjectedClock:
    @pytest.mark.unit
    def test_price_series_falls_back_to_clock_when_start_none(self) -> None:
        clock = FixedClock(datetime(2026, 5, 12, 10, 30, tzinfo=UTC))
        series = generate_price_series(start=None, hours=24, clock=clock)
        # Start is rounded to the hour.
        assert series[0][0] == datetime(2026, 5, 12, 10, 0, tzinfo=UTC)

    @pytest.mark.unit
    def test_price_series_explicit_start_ignores_clock(self) -> None:
        clock = FixedClock(datetime(2030, 1, 1, tzinfo=UTC))
        explicit_start = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)
        series = generate_price_series(start=explicit_start, hours=24, clock=clock)
        assert series[0][0] == explicit_start
