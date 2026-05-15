"""Tests for occupant demand simulation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hemm_core.sim.occupants import (
    apply_interventions,
    generate_synthetic_profile,
    load_household_profile,
    read_profile,
    validate_profile,
    write_profile,
)
from hemm_core.sim.occupants.lpg import cache_key, normalize_lpg_output
from hemm_core.sim.occupants.overlay import apply_calendar_overlay
from hemm_core.sim.runner import SimRunner
from hemm_core.sim.scenario import load_scenario

TESTDATA = Path(__file__).parent.parent / "testdata"


@pytest.mark.unit
def test_synthetic_profile_is_deterministic() -> None:
    start = datetime(2026, 1, 15, tzinfo=UTC)
    a = generate_synthetic_profile(archetype="family4", seed=17, start=start, hours=24)
    b = generate_synthetic_profile(archetype="family4", seed=17, start=start, hours=24)
    assert a.slots == b.slots
    assert a.slots[0].presence == 0
    assert sum(slot.total_electric_kw() for slot in a.slots) > 0


@pytest.mark.unit
def test_profile_parquet_roundtrip(tmp_path: Path) -> None:
    start = datetime(2026, 1, 15, tzinfo=UTC)
    profile = generate_synthetic_profile(archetype="family4", seed=17, start=start, hours=4)
    path = tmp_path / "profile.parquet"
    write_profile(profile, path)
    loaded = read_profile(path)
    assert loaded.resolution_minutes == 15
    assert loaded.archetype == "family4"
    assert loaded.slots[0].timestamp == start


@pytest.mark.unit
def test_calendar_overlay_vacation_removes_presence() -> None:
    start = datetime(2026, 7, 15, tzinfo=UTC)
    profile = generate_synthetic_profile(archetype="family4", seed=17, start=start, hours=24)
    overlaid = apply_calendar_overlay(profile, {"vacation": ["2026-07-15..2026-07-16"]})
    assert max(slot.presence for slot in overlaid.slots) == 0
    assert max(slot.electric_appliances_w for slot in overlaid.slots) == 0


@pytest.mark.unit
def test_shift_load_intervention_moves_dishwasher() -> None:
    start = datetime(2026, 1, 15, tzinfo=UTC)
    profile = generate_synthetic_profile(archetype="family4", seed=17, start=start, hours=24)
    result = apply_interventions(
        profile,
        [
            {
                "id": "shift",
                "type": "shift_load",
                "appliance": "dishwasher",
                "to_window": {"earliest": "11:00", "latest": "16:00"},
            }
        ],
    )
    dishwasher_slots = [
        slot.timestamp.hour
        for slot in result.profile.slots
        for event in slot.appliance_events
        if event.appliance == "dishwasher"
    ]
    assert dishwasher_slots == [11]
    assert validate_profile(result.profile) == []


@pytest.mark.unit
def test_lpg_normalizer_accepts_canonical_fixture(tmp_path: Path) -> None:
    start = datetime(2026, 1, 15, tzinfo=UTC)
    profile = generate_synthetic_profile(archetype="family4", seed=17, start=start, hours=4)
    write_profile(profile, tmp_path / "household_canonical.csv")
    normalized = normalize_lpg_output(tmp_path)
    assert normalized.slots[0].timestamp == start
    assert cache_key(archetype="family4", lpg_version="test", seed=17, year=2026, resolution_minutes=15)


@pytest.mark.unit
def test_load_household_profile_from_lpg_fixture() -> None:
    scenario_dir = TESTDATA / "scenarios"
    profile = load_household_profile(
        {
            "adapter": "lpg",
            "profile": "../profiles/family4-2026-s17.parquet",
            "start": "2026-01-15",
        },
        base_dir=scenario_dir,
        default_start=datetime(2026, 1, 15, tzinfo=UTC),
        horizon_hours=24,
        resolution_minutes=15,
    )
    assert len(profile.slots) == 96
    assert profile.start == datetime(2026, 1, 15, tzinfo=UTC)


@pytest.mark.unit
def test_scenario_parses_household_and_interventions() -> None:
    scenario = load_scenario(TESTDATA / "scenarios" / "family4_winter_setback.yaml")
    assert scenario.household is not None
    assert scenario.household["adapter"] == "lpg"
    assert [i["id"] for i in scenario.interventions] == [
        "shift_dishwasher_to_pv",
        "setback_workday",
        "ev_pv_match",
    ]


@pytest.mark.unit
def test_runner_uses_household_profile() -> None:
    scenario = load_scenario(TESTDATA / "scenarios" / "family4_winter_setback.yaml")
    result = SimRunner().run(scenario)
    assert result.success, result.error
    assert result.metrics.household_energy_kwh > 0
    assert result.metrics.dhw_draw_energy_kwh > 0
    assert result.metrics.peak_total_power_kw > 0
    assert result.metrics.applied_interventions == ["shift_dishwasher_to_pv", "setback_workday", "ev_pv_match"]
