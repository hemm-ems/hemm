"""Tests for message types and conflict resolution."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hemm.manifest.conflicts import find_conflicts, resolve_conflicts
from hemm.manifest.constraints import MinSocUntil, ReachMinTempOnce
from hemm.manifest.messages import (
    ConstraintWindow,
    PlanMessage,
    PlanSlot,
    PriceMessage,
    PriceSlot,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TestPlanMessage:
    """Tests for plan messages."""

    @pytest.mark.unit
    def test_valid_plan(self) -> None:
        now = _utc_now()
        plan = PlanMessage(
            device_id="bat1",
            created_at=now,
            horizon_minutes=60,
            slots=[
                PlanSlot(start=now, end=now, power_kw=2.5, mode="charge"),
            ],
        )
        assert plan.device_id == "bat1"
        assert len(plan.slots) == 1

    @pytest.mark.unit
    def test_plan_roundtrip(self) -> None:
        now = _utc_now()
        plan = PlanMessage(
            device_id="hp1",
            created_at=now,
            horizon_minutes=120,
            slots=[PlanSlot(start=now, end=now, power_kw=-3.0)],
        )
        restored = PlanMessage.model_validate_json(plan.model_dump_json())
        assert restored == plan

    @pytest.mark.unit
    def test_empty_slots_rejected(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            PlanMessage(device_id="x", created_at=_utc_now(), horizon_minutes=60, slots=[])


class TestPriceMessage:
    """Tests for price messages (Backend B internal)."""

    @pytest.mark.unit
    def test_valid_price_message(self) -> None:
        now = _utc_now()
        msg = PriceMessage(
            device_id="hp1",
            iteration=3,
            created_at=now,
            slots=[
                PriceSlot(
                    start=now,
                    end=now,
                    base_price=0.30,
                    target_load_band=(1.0, 4.0),
                    penalty_weight=1.5,
                ),
            ],
        )
        assert msg.iteration == 3
        assert msg.slots[0].penalty_weight == 1.5

    @pytest.mark.unit
    def test_price_message_roundtrip(self) -> None:
        now = _utc_now()
        msg = PriceMessage(
            device_id="bat1",
            iteration=0,
            created_at=now,
            slots=[
                PriceSlot(start=now, end=now, base_price=0.10, target_load_band=(0, 5.0)),
            ],
        )
        restored = PriceMessage.model_validate_json(msg.model_dump_json())
        assert restored == msg


class TestConstraintWindow:
    """Tests for constraint window messages."""

    @pytest.mark.unit
    def test_valid_window(self) -> None:
        now = _utc_now()
        w = ConstraintWindow(
            window_id="w1",
            device_id="dhw",
            deadline=now,
            requirement=ReachMinTempOnce(target_temp_c=60.0),
            flex_cost_per_hour_early=0.5,
            priority_penalty=2.0,
        )
        assert w.window_id == "w1"
        assert w.priority_penalty == 2.0

    @pytest.mark.unit
    def test_window_with_soc(self) -> None:
        now = _utc_now()
        w = ConstraintWindow(
            window_id="w2",
            device_id="ev1",
            deadline=now,
            requirement=MinSocUntil(min_soc_pct=80.0),
        )
        assert w.requirement.type == "min_soc_until"

    @pytest.mark.unit
    def test_window_roundtrip(self) -> None:
        now = _utc_now()
        w = ConstraintWindow(
            window_id="w1",
            device_id="dhw",
            deadline=now,
            requirement=ReachMinTempOnce(target_temp_c=60.0),
            flex_cost_per_hour_early=0.5,
        )
        restored = ConstraintWindow.model_validate_json(w.model_dump_json())
        assert restored == w


class TestConflictResolution:
    """Tests for conflict resolution — higher penalty wins."""

    @pytest.mark.unit
    def test_resolve_empty(self) -> None:
        assert resolve_conflicts([]) == []

    @pytest.mark.unit
    def test_resolve_single(self) -> None:
        now = _utc_now()
        w = ConstraintWindow(
            window_id="w1",
            device_id="d1",
            deadline=now,
            requirement=ReachMinTempOnce(target_temp_c=60.0),
            priority_penalty=1.0,
        )
        result = resolve_conflicts([w])
        assert result == [w]

    @pytest.mark.unit
    def test_higher_penalty_wins(self) -> None:
        """Windows sorted by priority_penalty descending."""
        now = _utc_now()
        low = ConstraintWindow(
            window_id="low",
            device_id="d1",
            deadline=now,
            requirement=ReachMinTempOnce(target_temp_c=50.0),
            priority_penalty=1.0,
        )
        high = ConstraintWindow(
            window_id="high",
            device_id="d1",
            deadline=now,
            requirement=ReachMinTempOnce(target_temp_c=60.0),
            priority_penalty=5.0,
        )
        result = resolve_conflicts([low, high])
        assert result[0].window_id == "high"
        assert result[1].window_id == "low"

    @pytest.mark.unit
    @settings(max_examples=100)
    @given(
        penalties=st.lists(
            st.floats(min_value=0.01, max_value=1000, allow_nan=False),
            min_size=2,
            max_size=10,
        )
    )
    def test_resolve_always_sorted_descending(self, penalties: list[float]) -> None:
        """Property: resolve_conflicts always returns descending priority order."""
        now = _utc_now()
        windows = [
            ConstraintWindow(
                window_id=f"w{i}",
                device_id="d1",
                deadline=now,
                requirement=ReachMinTempOnce(target_temp_c=60.0),
                priority_penalty=p,
            )
            for i, p in enumerate(penalties)
        ]
        result = resolve_conflicts(windows)
        for i in range(len(result) - 1):
            assert result[i].priority_penalty >= result[i + 1].priority_penalty

    @pytest.mark.unit
    def test_find_conflicts_same_device(self) -> None:
        now = _utc_now()
        w1 = ConstraintWindow(
            window_id="w1",
            device_id="d1",
            deadline=now,
            requirement=ReachMinTempOnce(target_temp_c=60.0),
            priority_penalty=5.0,
        )
        w2 = ConstraintWindow(
            window_id="w2",
            device_id="d1",
            deadline=now,
            requirement=ReachMinTempOnce(target_temp_c=50.0),
            priority_penalty=1.0,
        )
        conflicts = find_conflicts([w1, w2])
        assert len(conflicts) == 1
        # Higher penalty is first in the pair
        assert conflicts[0][0].window_id == "w1"

    @pytest.mark.unit
    def test_find_conflicts_different_devices_no_conflict(self) -> None:
        now = _utc_now()
        w1 = ConstraintWindow(
            window_id="w1",
            device_id="d1",
            deadline=now,
            requirement=ReachMinTempOnce(target_temp_c=60.0),
            priority_penalty=5.0,
        )
        w2 = ConstraintWindow(
            window_id="w2",
            device_id="d2",
            deadline=now,
            requirement=ReachMinTempOnce(target_temp_c=50.0),
            priority_penalty=1.0,
        )
        conflicts = find_conflicts([w1, w2])
        assert len(conflicts) == 0
