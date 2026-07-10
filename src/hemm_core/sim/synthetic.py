"""Synthetic time series generators for simulation."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from hemm_core.time import Clock, WallClock


def generate_price_series(
    start: datetime | None = None,
    hours: int = 24,
    resolution_minutes: int = 15,
    base_price: float = 0.30,
    peak_price: float = 0.45,
    off_peak_price: float = 0.20,
    *,
    clock: Clock | None = None,
) -> list[tuple[datetime, float]]:
    """Generate a synthetic electricity price time series.

    Produces a realistic day-ahead price pattern with:
    - Morning peak (7-9)
    - Evening peak (17-20)
    - Low prices overnight and midday (solar surplus)

    Args:
        start: Start time. If None, defaults to `clock.now()` rounded to the
            hour (and `clock` defaults to `WallClock` for back-compat).
        hours: Number of hours to generate.
        resolution_minutes: Resolution in minutes.
        base_price: Base price in €/kWh.
        peak_price: Peak price in €/kWh.
        off_peak_price: Off-peak price in €/kWh.
        clock: Time source used only when `start` is None.

    Returns:
        List of (timestamp, price_eur_per_kwh) tuples.
    """
    if start is None:
        c: Clock = clock if clock is not None else WallClock()
        start = c.now().replace(minute=0, second=0, microsecond=0)

    n_slots = hours * 60 // resolution_minutes
    series: list[tuple[datetime, float]] = []

    for i in range(n_slots):
        t = start + timedelta(minutes=i * resolution_minutes)
        hour = t.hour + t.minute / 60.0

        # Price profile: two peaks + solar dip
        morning_peak = 0.6 * math.exp(-0.5 * ((hour - 8) / 1.5) ** 2)
        evening_peak = 0.8 * math.exp(-0.5 * ((hour - 18) / 2) ** 2)
        solar_dip = -0.4 * math.exp(-0.5 * ((hour - 13) / 2) ** 2)

        factor = 1.0 + morning_peak + evening_peak + solar_dip
        price = off_peak_price + (peak_price - off_peak_price) * max(0.0, min(1.0, (factor - 0.5) / 1.5))

        series.append((t, round(price, 4)))

    return series


def generate_weather_series(
    start: datetime | None = None,
    hours: int = 24,
    resolution_minutes: int = 60,
    min_temp_c: float = 2.0,
    max_temp_c: float = 12.0,
    *,
    clock: Clock | None = None,
) -> list[tuple[datetime, float]]:
    """Generate a synthetic outdoor temperature time series.

    Produces a sinusoidal daily temperature pattern:
    - Minimum at 5:00
    - Maximum at 15:00

    Args:
        start: Start time. If None, defaults to `clock.now()` rounded to the
            hour (and `clock` defaults to `WallClock` for back-compat).
        hours: Duration.
        resolution_minutes: Resolution.
        min_temp_c: Minimum daily temperature.
        max_temp_c: Maximum daily temperature.
        clock: Time source used only when `start` is None.

    Returns:
        List of (timestamp, temperature_celsius) tuples.
    """
    if start is None:
        c: Clock = clock if clock is not None else WallClock()
        start = c.now().replace(minute=0, second=0, microsecond=0)

    n_slots = hours * 60 // resolution_minutes
    series: list[tuple[datetime, float]] = []
    amplitude = (max_temp_c - min_temp_c) / 2.0
    mean_temp = (max_temp_c + min_temp_c) / 2.0

    for i in range(n_slots):
        t = start + timedelta(minutes=i * resolution_minutes)
        hour = t.hour + t.minute / 60.0
        # Cosine curve: minimum at 5:00, maximum at 17:00
        temp = mean_temp + amplitude * math.cos(2 * math.pi * (hour - 15) / 24)
        series.append((t, round(temp, 1)))

    return series


def generate_pv_series(
    start: datetime,
    hours: int = 24,
    resolution_minutes: int = 15,
    peak_kwp: float = 5.0,
) -> list[float]:
    """Generate a deterministic synthetic PV production series in kW.

    Half-sine bell between 06:00 and 20:00 local-slot time scaled to
    ``peak_kwp`` — no randomness, so sims and goldens stay reproducible.
    Values are positive kW of *available* production; the solver dispatches
    sources as negative power and may curtail below this bound (FR-006).
    """
    n_slots = hours * 60 // resolution_minutes
    series: list[float] = []
    sunrise, sunset = 6.0, 20.0
    for i in range(n_slots):
        t = start + timedelta(minutes=i * resolution_minutes)
        hour = t.hour + t.minute / 60.0
        if sunrise <= hour <= sunset:
            series.append(round(peak_kwp * math.sin(math.pi * (hour - sunrise) / (sunset - sunrise)), 6))
        else:
            series.append(0.0)
    return series
