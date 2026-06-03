"""Backend-A golden plan-parity tests (feature 003).

Scaffold created in T003. The parity test (T015, 003:FR-005/FR-006) compares a
component-driven Backend-A solve against the golden fixtures captured in T001
(``testdata/golden/003_backend_a/``) using the helper in ``tests/_parity.py``.
"""

from __future__ import annotations

import pytest

from tests._parity import (
    DIVERGENCE_ALLOWLIST,
    GOLDEN_DIR,
    OBJECTIVE_REL_TOL,
    POWER_ABS_TOL,
    SCENARIOS,
    SCENARIOS_DIR,
    extract_plan,
    load_golden,
    solve_scenario,
)


ACTS_FROM_ZERO_ALLOWLIST = frozenset(
    {
        ("water_heater_legionella", "dhw"),
        ("full_house", "dhw"),
        ("onboarding", "ev_charger_garage"),
    }
)


def _objective_diff(golden: dict[str, object], current: dict[str, object]) -> str | None:
    g_obj = golden["objective_value"]
    c_obj = current["objective_value"]
    if (g_obj is None) != (c_obj is None):
        return f"objective presence: golden={g_obj} current={c_obj}"
    if g_obj is None or c_obj is None:
        return None
    if abs(c_obj - g_obj) > OBJECTIVE_REL_TOL * max(1.0, abs(g_obj)):
        return f"objective: golden={g_obj!r} current={c_obj!r} (delta={c_obj - g_obj:.3e})"
    return None


@pytest.mark.req("003:FR-005", "003:FR-006")
@pytest.mark.unit
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_backend_a_component_build_matches_per_device_golden(scenario: str) -> None:
    golden = load_golden(scenario)
    current = extract_plan(solve_scenario(SCENARIOS_DIR / f"{scenario}.yaml"))

    diffs: list[str] = []
    if current["status"] != golden["status"]:
        diffs.append(f"status: golden={golden['status']} current={current['status']}")

    golden_devices = golden["devices"]
    current_devices = current["devices"]
    if set(golden_devices) != set(current_devices):
        diffs.append(f"device set: golden={sorted(golden_devices)} current={sorted(current_devices)}")

    scenario_allowlist = {device for allowed_scenario, device in DIVERGENCE_ALLOWLIST if allowed_scenario == scenario}
    if not scenario_allowlist:
        objective_diff = _objective_diff(golden, current)
        if objective_diff is not None:
            diffs.append(objective_diff)

    for device in sorted(set(golden_devices) & set(current_devices)):
        pair = (scenario, device)
        golden_power = golden_devices[device]
        current_power = current_devices[device]
        if len(golden_power) != len(current_power):
            diffs.append(f"{device}: slot count golden={len(golden_power)} current={len(current_power)}")
            continue

        if pair in DIVERGENCE_ALLOWLIST:
            if pair in ACTS_FROM_ZERO_ALLOWLIST:
                acts_where_golden_was_zero = any(
                    abs(gv) <= POWER_ABS_TOL and abs(cv) > POWER_ABS_TOL
                    for gv, cv in zip(golden_power, current_power, strict=True)
                )
                if not acts_where_golden_was_zero:
                    diffs.append(f"{device}: allowlisted divergence did not act where golden was zero")
            else:
                golden_kwh = sum(golden_power) * 0.25
                current_kwh = sum(current_power) * 0.25
                if abs(current_kwh - golden_kwh) > POWER_ABS_TOL:
                    diffs.append(f"{device}: golden_kwh={golden_kwh!r} current_kwh={current_kwh!r}")
            continue

        for t, (gv, cv) in enumerate(zip(golden_power, current_power, strict=True)):
            if abs(cv - gv) > POWER_ABS_TOL:
                diffs.append(f"{device}[{t}]: golden={gv!r} current={cv!r} (delta={cv - gv:.3e})")

    unexpected_allowlist = scenario_allowlist - set(current_devices)
    if unexpected_allowlist:
        diffs.append(f"allowlisted devices absent from scenario: {sorted(unexpected_allowlist)}")

    assert not diffs, f"{scenario} diverged from {GOLDEN_DIR / f'{scenario}.json'}:\n" + "\n".join(diffs)
