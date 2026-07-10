"""US1 — scenarios that cannot rot: relative deadlines, fail-loud, fulfillment.

Covers FR-011 (relative deadlines active at any wall-clock date, plus the
`start:` anchor), FR-012 (a scenario whose declared windows have all expired
fails instead of solving green) and FR-013 (per-window fulfillment: delivered
energy ≥ target, not just result.success).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hemm_core.sim.runner import SimRunner
from hemm_core.sim.scenario import Scenario, load_scenario

SCENARIOS_DIR = Path(__file__).parent.parent / "testdata" / "scenarios"
MANIFESTS_DIR = Path(__file__).parent.parent / "testdata" / "manifests" / "simple_house"


def _battery_manifest() -> dict:
    """A schema-valid battery manifest (the shipped example, unique device id)."""
    data = json.loads((MANIFESTS_DIR / "battery.json").read_text(encoding="utf-8"))
    data["device_id"] = "bat1"
    return data


def _scenario(windows: list[dict], **kwargs) -> Scenario:
    defaults: dict = {
        "name": "trust",
        "horizon_hours": 8,
        "resolution_minutes": 15,
        "manifests": [_battery_manifest()],
        "constraint_windows": windows,
    }
    defaults.update(kwargs)
    return Scenario(**defaults)


@pytest.mark.unit
def test_expired_absolute_deadline_fails_loud() -> None:
    """FR-012: all declared windows expired at t0 → error, not a green solve."""
    scenario = _scenario(
        [
            {
                "window_id": "stale",
                "device_id": "bat1",
                "deadline": "2020-01-01T07:00:00+00:00",
                "requirement": {"type": "min_soc_until", "min_soc_pct": 60},
                "priority_penalty": 2.0,
            }
        ]
    )
    result = SimRunner().run(scenario)
    assert not result.success
    assert result.error is not None
    assert "active" in result.error.lower()


@pytest.mark.unit
def test_relative_deadline_is_active_at_any_date() -> None:
    """FR-011: a relative-deadline window is active regardless of wall-clock date."""
    scenario = _scenario(
        [
            {
                "window_id": "morning_soc",
                "device_id": "bat1",
                "deadline_offset_hours": 6,
                "requirement": {"type": "min_soc_until", "min_soc_pct": 60},
                "priority_penalty": 2.0,
            }
        ]
    )
    result = SimRunner().run(scenario)
    assert result.success, result.error


@pytest.mark.unit
def test_start_anchor_resolves_offsets_against_it() -> None:
    """FR-011: a scenario `start:` anchors t0, so offsets resolve against it."""
    start = datetime(2026, 5, 7, 0, 0, tzinfo=UTC)
    scenario = _scenario(
        [
            {
                "window_id": "morning_soc",
                "device_id": "bat1",
                "deadline_offset_hours": 6,
                "requirement": {"type": "min_soc_until", "min_soc_pct": 60},
                "priority_penalty": 2.0,
            }
        ],
        start=start,
    )
    result = SimRunner().run(scenario)
    assert result.success, result.error
    plan = result.plans[0]
    assert plan.slots[0].start == start


@pytest.mark.unit
def test_offset_and_absolute_deadline_together_rejected() -> None:
    """A window may not set both `deadline` and `deadline_offset_hours`."""
    scenario = _scenario(
        [
            {
                "window_id": "ambiguous",
                "device_id": "bat1",
                "deadline": "2026-05-07T07:00:00+00:00",
                "deadline_offset_hours": 7,
                "requirement": {"type": "min_soc_until", "min_soc_pct": 60},
                "priority_penalty": 2.0,
            }
        ]
    )
    with pytest.raises(ValueError, match="both"):
        SimRunner().run(scenario)


@pytest.mark.slow
def test_ev_departure_fulfills_energy_target() -> None:
    """FR-013: the EV departure scenario delivers its required energy by the deadline
    and stays idle during the forbidden quiet-hours window — not just 'success'."""
    scenario = load_scenario(SCENARIOS_DIR / "ev_departure.yaml")
    result = SimRunner().run(scenario)
    assert result.success, result.error

    ev_plan = next(p for p in result.plans if p.device_id == "ev_charger_garage")
    dt_h = scenario.resolution_minutes / 60.0
    t0 = ev_plan.slots[0].start
    deadline = t0 + timedelta(hours=7)
    forbidden_end = t0 + timedelta(hours=4)

    delivered = sum(s.power_kw * dt_h for s in ev_plan.slots if s.start < deadline and s.power_kw > 0)
    assert delivered >= 30.0 * 0.95, f"EV delivered only {delivered:.1f} kWh of the 30 kWh target"

    quiet_energy = sum(s.power_kw for s in ev_plan.slots if s.start < forbidden_end)
    assert quiet_energy == pytest.approx(0.0, abs=1e-6), "EV charged during forbidden quiet hours"


@pytest.mark.slow
def test_standard_scenarios_have_active_windows() -> None:
    """Every standard scenario that declares windows keeps at least one active at t0
    (i.e. none silently rotted to an unconstrained solve). Since FR-012 fails loud on
    zero active windows, a successful run with declared windows proves ≥ 1 was active."""
    for name in ["battery_arbitrage", "ev_departure", "heat_pump_shift", "water_heater_legionella"]:
        scenario = load_scenario(SCENARIOS_DIR / f"{name}.yaml")
        assert scenario.constraint_windows, f"{name} should declare windows"
        result = SimRunner().run(scenario)
        assert result.success, f"{name}: {result.error}"
