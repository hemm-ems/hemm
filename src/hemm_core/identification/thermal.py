"""Grey-box thermal identification for room RC models."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np

_MAX_CONDITION_NUMBER = 500.0


@dataclass(frozen=True)
class ThermalObservation:
    indoor_temp_c: float
    outdoor_temp_c: float
    heat_input_kw: float = 0.0
    solar_irradiance_w_m2: float = 0.0
    presence: float = 0.0


@dataclass(frozen=True)
class RoomThermalModel:
    thermal_mass_kwh_per_k: float
    ua_kw_per_k: float
    solar_aperture_m2: float
    occupant_gain_kw: float
    r_squared: float
    condition_number: float


@dataclass
class IdentificationResult:
    device_id: str
    parameter_updates: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    message: str = ""


def identify_room_thermal(
    observations: Sequence[ThermalObservation],
    dt_hours: float,
    *,
    device_id: str,
    envelope_area_m2: float | None = None,
    min_observations: int = 24,
) -> IdentificationResult | None:
    """Estimate a room thermal RC model from consecutive observations."""

    transition_count = len(observations) - 1
    if transition_count < min_observations:
        return None

    if dt_hours <= 0.0:
        return None

    x_rows: list[list[float]] = []
    y_rows: list[float] = []
    for current, next_observation in pairwise(observations):
        x_rows.append(
            [
                current.heat_input_kw,
                current.solar_irradiance_w_m2 / 1000.0,
                current.presence,
                current.indoor_temp_c - current.outdoor_temp_c,
            ]
        )
        y_rows.append(next_observation.indoor_temp_c - current.indoor_temp_c)

    x = np.asarray(x_rows, dtype=float)
    y = np.asarray(y_rows, dtype=float)

    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    if ss_tot == 0.0:
        return None

    try:
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        condition_number = float(np.linalg.cond(x))
    except np.linalg.LinAlgError:
        return None

    predictions = x @ beta
    ss_res = float(np.sum((y - predictions) ** 2))
    r_squared = 1.0 - (ss_res / ss_tot)

    heat_beta = float(beta[0])
    if heat_beta <= 1e-9:
        return None

    thermal_mass_kwh_per_k = dt_hours / heat_beta
    if thermal_mass_kwh_per_k <= 0.0:
        return None

    solar_aperture_m2 = float(beta[1] / heat_beta)
    occupant_gain_kw = float(beta[2] / heat_beta)
    ua_kw_per_k = float(-beta[3] / heat_beta)
    if ua_kw_per_k < -1e-6:
        return None
    if ua_kw_per_k < 0.0:
        ua_kw_per_k = 0.0

    thermal_model = RoomThermalModel(
        thermal_mass_kwh_per_k=thermal_mass_kwh_per_k,
        ua_kw_per_k=ua_kw_per_k,
        solar_aperture_m2=solar_aperture_m2,
        occupant_gain_kw=occupant_gain_kw,
        r_squared=r_squared,
        condition_number=condition_number,
    )

    parameter_updates: dict[str, Any] = {
        "thermal_mass_kwh_per_k": thermal_mass_kwh_per_k,
        "solar_aperture_m2": solar_aperture_m2,
        "occupant_gain_kw": occupant_gain_kw,
        "ua_kw_per_k": ua_kw_per_k,
        "thermal_model": thermal_model,
    }
    if envelope_area_m2 is not None and envelope_area_m2 > 0.0:
        parameter_updates["u_value_w_per_m2k"] = ua_kw_per_k * 1000.0 / envelope_area_m2

    condition_gate_tripped = condition_number > _MAX_CONDITION_NUMBER
    confidence = 0.0 if condition_gate_tripped else max(0.0, min(1.0, r_squared))
    gate_message = ", condition gate tripped" if condition_gate_tripped else ""
    message = (
        f"R2={r_squared:.3f}, cond={condition_number:.1f}, "
        f"C={thermal_mass_kwh_per_k:.2f} kWh/K, UA={ua_kw_per_k:.3f} kW/K{gate_message}"
    )
    return IdentificationResult(
        device_id=device_id,
        parameter_updates=parameter_updates,
        confidence=confidence,
        message=message,
    )
