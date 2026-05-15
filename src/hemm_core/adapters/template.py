"""Template adapter — Jinja2-based fallback for arbitrary forecast expressions.

Allows users to define forecast values via Jinja2 templates,
evaluating expressions against time and other variables.
Useful as a price source or custom forecast generator.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from hemm_core.adapters.protocol import ForecastPoint
from hemm_core.time import Clock, WallClock


class TemplateAdapter:
    """Template-based forecast adapter using Jinja2 expressions."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock: Clock = clock if clock is not None else WallClock()

    @property
    def name(self) -> str:
        return "template"

    @property
    def source_type(self) -> str:
        return "template"

    def fetch(self, **kwargs: object) -> list[ForecastPoint]:
        """Evaluate a Jinja2 template to produce forecast points.

        Kwargs:
            template: Jinja2 expression string that produces a float value.
                      Available variables: hour, day_of_week, month, timestamp.
            unit: Unit string (default 'EUR_per_kWh').
            hours: Number of hours to produce (default 24).
            data: Pre-built data list (bypass template eval).
        """
        data = kwargs.get("data")
        if data is not None and isinstance(data, list):
            return self._from_data(data)

        template = kwargs.get("template")
        if not isinstance(template, str):
            msg = "TemplateAdapter requires 'template' kwarg (Jinja2 expression string)"
            raise ValueError(msg)

        unit = str(kwargs.get("unit", "EUR_per_kWh"))
        hours = int(float(str(kwargs.get("hours", 24) or 24)))
        return self._evaluate_template(template, unit, hours)

    def _from_data(self, data: list[object]) -> list[ForecastPoint]:
        """Convert pre-fetched data."""
        points: list[ForecastPoint] = []
        for item in data:
            if isinstance(item, dict):
                ts = item.get("timestamp")
                val = item.get("value", 0.0)
                unit = item.get("unit", "EUR_per_kWh")
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                if isinstance(ts, datetime):
                    points.append(ForecastPoint(timestamp=ts, value=float(val), unit=str(unit)))
        return points

    def _evaluate_template(self, template: str, unit: str, hours: int) -> list[ForecastPoint]:
        """Evaluate a Jinja2 template expression for each hour."""
        import jinja2

        env = jinja2.Environment(autoescape=False)
        try:
            tmpl = env.from_string("{{ " + template + " }}")
        except jinja2.TemplateSyntaxError:
            # Invalid template — return zeros
            now = self._clock.now().replace(minute=0, second=0, microsecond=0)
            return [ForecastPoint(timestamp=now + timedelta(hours=h), value=0.0, unit=unit) for h in range(hours)]

        now = self._clock.now().replace(minute=0, second=0, microsecond=0)
        points: list[ForecastPoint] = []

        for h in range(hours):
            t = now + timedelta(hours=h)
            context = {
                "hour": t.hour,
                "day_of_week": t.weekday(),
                "month": t.month,
                "timestamp": t.isoformat(),
                "h": h,
            }
            try:
                rendered = tmpl.render(**context)
                value = float(rendered)
            except (ValueError, TypeError, jinja2.TemplateError):
                value = 0.0

            points.append(ForecastPoint(timestamp=t, value=round(value, 4), unit=unit))

        return points
