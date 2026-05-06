"""Tests for constraint-window management."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hemm.constraints import ConstraintWindowManager
from hemm.manifest.constraints import MinSocUntil
from hemm.manifest.messages import ConstraintWindow


def _make_window(
    window_id: str = "w1",
    device_id: str = "dev1",
    hours_until_deadline: float = 12,
    priority: float = 1.0,
    ttl: float | None = None,
    now: datetime | None = None,
) -> ConstraintWindow:
    """Helper to create a constraint window."""
    if now is None:
        now = datetime.now(tz=UTC)
    return ConstraintWindow(
        window_id=window_id,
        device_id=device_id,
        deadline=now + timedelta(hours=hours_until_deadline),
        requirement=MinSocUntil(min_soc_pct=80),
        priority_penalty=priority,
        ttl_seconds=ttl,
        created_at=now,
    )


class TestConstraintWindowManager:
    """Tests for the ConstraintWindowManager."""

    @pytest.mark.unit
    def test_add_and_get(self) -> None:
        mgr = ConstraintWindowManager()
        w = _make_window("w1")
        mgr.add(w)
        assert mgr.get("w1") is not None
        assert mgr.count == 1

    @pytest.mark.unit
    def test_remove(self) -> None:
        mgr = ConstraintWindowManager()
        w = _make_window("w1")
        mgr.add(w)
        removed = mgr.remove("w1")
        assert removed is not None
        assert mgr.count == 0
        assert mgr.remove("nonexistent") is None

    @pytest.mark.unit
    def test_get_active_filters_expired(self) -> None:
        now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
        mgr = ConstraintWindowManager()
        # Active window (deadline in 12h)
        mgr.add(_make_window("active", hours_until_deadline=12, now=now))
        # Expired window (deadline was 1h ago)
        mgr.add(_make_window("expired", hours_until_deadline=-1, now=now))

        active = mgr.get_active(now=now)
        assert len(active) == 1
        assert active[0].window_id == "active"

    @pytest.mark.unit
    def test_get_active_filters_ttl_expired(self) -> None:
        now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
        mgr = ConstraintWindowManager()
        # Window with TTL that has expired (TTL = 1 second, created in the past)
        past = now - timedelta(hours=1)
        mgr.add(_make_window("ttl_expired", hours_until_deadline=24, ttl=1.0, now=past))
        # Window with TTL still valid
        mgr.add(_make_window("ttl_valid", hours_until_deadline=24, ttl=7200.0, now=now))

        active = mgr.get_active(now=now)
        assert len(active) == 1
        assert active[0].window_id == "ttl_valid"

    @pytest.mark.unit
    def test_get_active_sorted_by_priority(self) -> None:
        now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
        mgr = ConstraintWindowManager()
        mgr.add(_make_window("low", priority=1.0, now=now))
        mgr.add(_make_window("high", priority=10.0, now=now))
        mgr.add(_make_window("mid", priority=5.0, now=now))

        active = mgr.get_active(now=now)
        assert [w.window_id for w in active] == ["high", "mid", "low"]

    @pytest.mark.unit
    def test_expire_old_removes_expired(self) -> None:
        now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
        mgr = ConstraintWindowManager()
        mgr.add(_make_window("active", hours_until_deadline=12, now=now))
        mgr.add(_make_window("expired1", hours_until_deadline=-1, now=now))
        mgr.add(_make_window("expired2", hours_until_deadline=-2, now=now))

        expired = mgr.expire_old(now=now)
        assert set(expired) == {"expired1", "expired2"}
        assert mgr.count == 1

    @pytest.mark.unit
    def test_get_for_device(self) -> None:
        now = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
        mgr = ConstraintWindowManager()
        mgr.add(_make_window("w1", device_id="battery", now=now))
        mgr.add(_make_window("w2", device_id="ev", now=now))
        mgr.add(_make_window("w3", device_id="battery", now=now))

        battery_windows = mgr.get_for_device("battery", now=now)
        assert len(battery_windows) == 2

    @pytest.mark.unit
    def test_bump_priority(self) -> None:
        mgr = ConstraintWindowManager()
        mgr.add(_make_window("w1", priority=1.0))
        assert mgr.bump_priority("w1", 10.0)
        w = mgr.get("w1")
        assert w is not None
        assert w.priority_penalty == 10.0
        assert not mgr.bump_priority("nonexistent", 5.0)

    @pytest.mark.unit
    def test_clear(self) -> None:
        mgr = ConstraintWindowManager()
        mgr.add(_make_window("w1"))
        mgr.add(_make_window("w2"))
        mgr.clear()
        assert mgr.count == 0

    @pytest.mark.unit
    def test_replace_on_same_id(self) -> None:
        mgr = ConstraintWindowManager()
        mgr.add(_make_window("w1", priority=1.0))
        mgr.add(_make_window("w1", priority=5.0))
        assert mgr.count == 1
        w = mgr.get("w1")
        assert w is not None
        assert w.priority_penalty == 5.0

    @pytest.mark.unit
    def test_iter(self) -> None:
        mgr = ConstraintWindowManager()
        mgr.add(_make_window("w1"))
        mgr.add(_make_window("w2"))
        windows = list(mgr)
        assert len(windows) == 2
