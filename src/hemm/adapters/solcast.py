"""Solcast forecast adapter.

Produces PV power forecast from the Solcast API.
In production, this would call the Solcast API. For now it serves
as a structural adapter that can work with pre-fetched data or HA entities.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hemm.adapters.protocol import ForecastPoint


class SolcastAdapter:
    """Solcast PV forecast adapter."""

    @property
    def name(self) -> str:
        return "solcast"

    @property
    def source_type(self) -> str:
        return "solar"

    def fetch(self, **kwargs: object) -> list[ForecastPoint]:
        """Fetch PV forecast from Solcast.

        In a real implementation, this calls the Solcast API.
        For core library usage, it accepts pre-fetched data via kwargs.

        Kwargs:
            data: List of dicts with 'timestamp' and 'value' keys (pre-fetched).
            peak_kwp: Peak power for synthetic generation (test mode).
            hours: Number of hours to forecast (test mode, default 24).
        """
        # If pre-fetched data is provided, convert to ForecastPoints
        data = kwargs.get("data")
        if data is not None and isinstance(data, list):
            return self._from_data(data)

        # Synthetic mode for testing
        peak_kwp = float(str(kwargs.get("peak_kwp", 10.0) or 10.0))
        hours = int(float(str(kwargs.get("hours", 24) or 24)))
        return self._synthetic(peak_kwp, hours)

    def _from_data(self, data: list[object]) -> list[ForecastPoint]:
        """Convert pre-fetched data to ForecastPoints."""
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

    def _synthetic(self, peak_kwp: float, hours: int) -> list[ForecastPoint]:
        """Generate a synthetic solar forecast (bell curve, peaks at noon)."""
        import math

        now = datetime.now(tz=UTC).replace(minute=0, second=0, microsecond=0)
        points: list[ForecastPoint] = []
        for h in range(hours):
            t = now + timedelta(hours=h)
            hour_of_day = t.hour
            # Bell curve peaking at 12:00
            solar_factor = max(0.0, math.exp(-0.5 * ((hour_of_day - 12) / 3) ** 2))
            power_kw = peak_kwp * solar_factor * 0.8  # 80% of peak as typical
            points.append(ForecastPoint(timestamp=t, value=round(power_kw, 3), unit="kW"))
        return points
