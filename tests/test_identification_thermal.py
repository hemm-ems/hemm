from __future__ import annotations

import numpy as np
import pytest

from hemm_core.identification import ThermalObservation, identify_room_thermal


def _exogenous_series(steps: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    index = np.arange(steps, dtype=float)
    outdoor_temp = 5.0 + 6.0 * np.sin(index / 13.0) + 0.04 * index
    solar = np.maximum(0.0, 650.0 * np.sin((index % 24.0 - 6.0) / 12.0 * np.pi))
    presence = ((index % 11.0) < 4.0).astype(float)
    presence += ((index % 17.0) >= 12.0).astype(float)
    presence += ((index % 29.0) == 0.0).astype(float)
    heat_input = 0.5 + 1.2 * ((index % 16.0) < 5.0).astype(float) + 0.4 * np.sin(index / 5.0)
    return outdoor_temp, solar, presence, heat_input


def _simulate_observations(
    *,
    steps: int,
    dt_hours: float,
    thermal_mass_kwh_per_k: float,
    ua_kw_per_k: float,
    solar_aperture_m2: float,
    occupant_gain_kw: float,
    noise_sigma: float = 0.0,
) -> list[ThermalObservation]:
    rng = np.random.default_rng(42)
    outdoor_temp, solar, presence, heat_input = _exogenous_series(steps)
    indoor = np.empty(steps + 1)
    indoor[0] = 19.5
    for step in range(steps):
        d_temp = (
            dt_hours
            * (
                heat_input[step]
                + solar_aperture_m2 * (solar[step] / 1000.0)
                + occupant_gain_kw * presence[step]
                - ua_kw_per_k * (indoor[step] - outdoor_temp[step])
            )
            / thermal_mass_kwh_per_k
        )
        indoor[step + 1] = indoor[step] + d_temp

    observed_indoor = indoor + rng.normal(0.0, noise_sigma, size=indoor.shape)
    return [
        ThermalObservation(
            indoor_temp_c=float(observed_indoor[step]),
            outdoor_temp_c=float(outdoor_temp[min(step, steps - 1)]),
            heat_input_kw=float(heat_input[min(step, steps - 1)]),
            solar_irradiance_w_m2=float(solar[min(step, steps - 1)]),
            presence=float(presence[min(step, steps - 1)]),
        )
        for step in range(steps + 1)
    ]


@pytest.mark.unit
@pytest.mark.req("006:FR-007")
def test_recovers_known_parameters_noiseless() -> None:
    observations = _simulate_observations(
        steps=96,
        dt_hours=0.25,
        thermal_mass_kwh_per_k=9.5,
        ua_kw_per_k=0.42,
        solar_aperture_m2=3.2,
        occupant_gain_kw=0.11,
    )

    result = identify_room_thermal(observations, 0.25, device_id="room.living", envelope_area_m2=120.0)

    assert result is not None
    updates = result.parameter_updates
    assert float(updates["thermal_mass_kwh_per_k"]) == pytest.approx(9.5, rel=1e-6)
    assert float(updates["ua_kw_per_k"]) == pytest.approx(0.42, rel=1e-6)
    assert float(updates["solar_aperture_m2"]) == pytest.approx(3.2, rel=1e-6)
    assert float(updates["occupant_gain_kw"]) == pytest.approx(0.11, rel=1e-6)
    assert float(updates["u_value_w_per_m2k"]) == pytest.approx(3.5, rel=1e-6)
    assert updates["thermal_model"].r_squared == pytest.approx(1.0)
    assert result.confidence == pytest.approx(1.0)


@pytest.mark.unit
@pytest.mark.req("006:FR-007")
def test_recovers_with_small_noise() -> None:
    observations = _simulate_observations(
        steps=384,
        dt_hours=0.25,
        thermal_mass_kwh_per_k=4.0,
        ua_kw_per_k=0.25,
        solar_aperture_m2=6.0,
        occupant_gain_kw=0.5,
        noise_sigma=0.02,
    )

    result = identify_room_thermal(observations, 0.25, device_id="room.office")

    assert result is not None
    updates = result.parameter_updates
    assert float(updates["thermal_mass_kwh_per_k"]) == pytest.approx(4.0, rel=0.05)
    assert float(updates["ua_kw_per_k"]) == pytest.approx(0.25, rel=0.05)
    assert float(updates["solar_aperture_m2"]) == pytest.approx(6.0, rel=0.05)
    assert float(updates["occupant_gain_kw"]) == pytest.approx(0.5, rel=0.05)
    assert updates["thermal_model"].r_squared > 0.95


@pytest.mark.unit
@pytest.mark.req("006:FR-007")
def test_insufficient_observations_returns_none() -> None:
    observations = [
        ThermalObservation(indoor_temp_c=20.0, outdoor_temp_c=5.0),
        ThermalObservation(indoor_temp_c=20.1, outdoor_temp_c=5.0),
    ]

    assert identify_room_thermal(observations, 0.25, device_id="room.short", min_observations=2) is None


@pytest.mark.unit
@pytest.mark.req("006:FR-007")
def test_degenerate_no_excitation_returns_none() -> None:
    observations = [ThermalObservation(indoor_temp_c=20.0, outdoor_temp_c=20.0) for _ in range(25)]

    result = identify_room_thermal(observations, 0.25, device_id="room.flat")

    assert result is None
