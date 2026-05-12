"""Forecast.Solar adapter.

Produces PV power forecast from the Forecast.Solar API.
Structural adapter — in production integrates with forecast.solar API.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from hemm.adapters.protocol import ForecastPoint
from hemm.time import Clock, WallClock


class ForecastSolarAdapter:
    """Forecast.Solar PV forecast adapter."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock: Clock = clock if clock is not None else WallClock()

    @property
    def name(self) -> str:
        return "forecast_solar"

    @property
    def source_type(self) -> str:
        return "solar"

    def fetch(self, **kwargs: object) -> list[ForecastPoint]:
        """Fetch PV forecast from Forecast.Solar.

        Kwargs:
            data: Pre-fetched data list.
            peak_kwp: Peak power in kWp.
            azimuth: Panel azimuth in degrees (180=south).
            tilt: Panel tilt in degrees.
            hours: Forecast horizon in hours (default 24).
        """
        data = kwargs.get("data")
        if data is not None and isinstance(data, list):
            return self._from_data(data)

        peak_kwp = float(str(kwargs.get("peak_kwp", 10.0) or 10.0))
        hours = int(float(str(kwargs.get("hours", 24) or 24)))
        azimuth = float(str(kwargs.get("azimuth", 180.0) or 180.0))
        tilt = float(str(kwargs.get("tilt", 30.0) or 30.0))
        return self._synthetic(peak_kwp, hours, azimuth, tilt)

    def _from_data(self, data: list[object]) -> list[ForecastPoint]:
        """Convert pre-fetched data."""
        points: list[ForecastPoint] = []
        for item in data:
            if isinstance(item, dict):
                ts = item.get("timestamp")
                val = item.get("value", 0.0)
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                if isinstance(ts, datetime):
                    points.append(ForecastPoint(timestamp=ts, value=float(val), unit="kW"))
        return points

    def _synthetic(self, peak_kwp: float, hours: int, azimuth: float, tilt: float) -> list[ForecastPoint]:
        """Generate synthetic PV forecast considering azimuth/tilt."""
        import math

        now = self._clock.now().replace(minute=0, second=0, microsecond=0)
        points: list[ForecastPoint] = []

        # Azimuth correction: south (180) is optimal, penalize deviation
        azimuth_factor = max(0.5, 1.0 - abs(azimuth - 180) / 360)
        # Tilt correction: 30° is near-optimal for middle latitudes
        tilt_factor = max(0.7, 1.0 - abs(tilt - 30) / 90 * 0.3)

        for h in range(hours):
            t = now + timedelta(hours=h)
            hour_of_day = t.hour
            solar_factor = max(0.0, math.exp(-0.5 * ((hour_of_day - 12) / 3) ** 2))
            power_kw = peak_kwp * solar_factor * azimuth_factor * tilt_factor * 0.75
            points.append(ForecastPoint(timestamp=t, value=round(power_kw, 3), unit="kW"))
        return points
