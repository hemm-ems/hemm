"""Tests for the forecast adapter framework."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hemm_core.adapters import AdapterRegistry, ForecastPoint, get_registry
from hemm_core.adapters.forecast_solar import ForecastSolarAdapter
from hemm_core.adapters.solcast import SolcastAdapter
from hemm_core.adapters.template import TemplateAdapter


class TestForecastPoint:
    """Tests for the canonical forecast point schema."""

    @pytest.mark.unit
    def test_forecast_point_creation(self) -> None:
        fp = ForecastPoint(
            timestamp=datetime(2026, 5, 6, 12, 0, tzinfo=UTC),
            value=5.5,
            unit="kW",
        )
        assert fp.value == 5.5
        assert fp.unit == "kW"

    @pytest.mark.unit
    def test_forecast_point_json_roundtrip(self) -> None:
        fp = ForecastPoint(
            timestamp=datetime(2026, 5, 6, 12, 0, tzinfo=UTC),
            value=3.14,
            unit="EUR_per_kWh",
        )
        data = fp.model_dump(mode="json")
        fp2 = ForecastPoint.model_validate(data)
        assert fp2.value == fp.value
        assert fp2.unit == fp.unit


class TestAdapterRegistry:
    """Tests for the adapter registry."""

    @pytest.mark.unit
    def test_register_and_get(self) -> None:
        registry = AdapterRegistry()
        adapter = SolcastAdapter()
        registry.register(adapter)
        assert registry.get("solcast") is adapter

    @pytest.mark.unit
    def test_get_missing_raises(self) -> None:
        registry = AdapterRegistry()
        with pytest.raises(KeyError, match="not registered"):
            registry.get("nonexistent")

    @pytest.mark.unit
    def test_list_adapters(self) -> None:
        registry = AdapterRegistry()
        registry.register(SolcastAdapter())
        registry.register(TemplateAdapter())
        names = registry.list_adapters()
        assert "solcast" in names
        assert "template" in names

    @pytest.mark.unit
    def test_has(self) -> None:
        registry = AdapterRegistry()
        registry.register(SolcastAdapter())
        assert registry.has("solcast")
        assert not registry.has("nonexistent")

    @pytest.mark.unit
    def test_global_registry_has_builtins(self) -> None:
        registry = get_registry()
        assert registry.has("solcast")
        assert registry.has("forecast_solar")
        assert registry.has("template")


class TestSolcastAdapter:
    """Tests for the Solcast adapter."""

    @pytest.mark.unit
    def test_properties(self) -> None:
        adapter = SolcastAdapter()
        assert adapter.name == "solcast"
        assert adapter.source_type == "solar"

    @pytest.mark.unit
    def test_synthetic_fetch(self) -> None:
        adapter = SolcastAdapter()
        points = adapter.fetch(peak_kwp=10.0, hours=24)
        assert len(points) == 24
        assert all(isinstance(p, ForecastPoint) for p in points)
        assert all(p.unit == "kW" for p in points)
        # Should have some non-zero values during daytime
        max_val = max(p.value for p in points)
        assert max_val > 0

    @pytest.mark.unit
    def test_from_data(self) -> None:
        adapter = SolcastAdapter()
        data = [
            {"timestamp": "2026-05-06T12:00:00+00:00", "value": 7.5},
            {"timestamp": "2026-05-06T13:00:00+00:00", "value": 7.2},
        ]
        points = adapter.fetch(data=data)
        assert len(points) == 2
        assert points[0].value == 7.5


class TestForecastSolarAdapter:
    """Tests for the Forecast.Solar adapter."""

    @pytest.mark.unit
    def test_properties(self) -> None:
        adapter = ForecastSolarAdapter()
        assert adapter.name == "forecast_solar"
        assert adapter.source_type == "solar"

    @pytest.mark.unit
    def test_synthetic_with_azimuth_correction(self) -> None:
        adapter = ForecastSolarAdapter()
        # South-facing (optimal)
        south = adapter.fetch(peak_kwp=10.0, azimuth=180.0, hours=24)
        # East-facing (suboptimal)
        east = adapter.fetch(peak_kwp=10.0, azimuth=90.0, hours=24)
        # South should produce more at noon
        assert south[12].value > east[12].value

    @pytest.mark.unit
    def test_from_data(self) -> None:
        adapter = ForecastSolarAdapter()
        data = [{"timestamp": "2026-05-06T12:00:00+00:00", "value": 8.0}]
        points = adapter.fetch(data=data)
        assert len(points) == 1
        assert points[0].value == 8.0


class TestTemplateAdapter:
    """Tests for the Jinja2 template adapter."""

    @pytest.mark.unit
    def test_properties(self) -> None:
        adapter = TemplateAdapter()
        assert adapter.name == "template"
        assert adapter.source_type == "template"

    @pytest.mark.unit
    def test_constant_template(self) -> None:
        adapter = TemplateAdapter()
        points = adapter.fetch(template="0.30", unit="EUR_per_kWh", hours=24)
        assert len(points) == 24
        assert all(p.value == 0.30 for p in points)
        assert all(p.unit == "EUR_per_kWh" for p in points)

    @pytest.mark.unit
    def test_hour_dependent_template(self) -> None:
        adapter = TemplateAdapter()
        # Price that depends on hour: cheap at night, expensive during day
        points = adapter.fetch(
            template="0.20 if hour < 6 or hour > 22 else 0.40",
            unit="EUR_per_kWh",
            hours=24,
        )
        assert len(points) == 24
        # Check some values
        night_points = [p for p in points if p.timestamp.hour < 6 or p.timestamp.hour > 22]
        day_points = [p for p in points if 6 <= p.timestamp.hour <= 22]
        if night_points:
            assert all(p.value == 0.20 for p in night_points)
        if day_points:
            assert all(p.value == 0.40 for p in day_points)

    @pytest.mark.unit
    def test_template_missing_raises(self) -> None:
        adapter = TemplateAdapter()
        with pytest.raises(ValueError, match="requires 'template'"):
            adapter.fetch(hours=24)

    @pytest.mark.unit
    def test_from_data(self) -> None:
        adapter = TemplateAdapter()
        data = [
            {"timestamp": "2026-05-06T00:00:00+00:00", "value": 0.25, "unit": "EUR_per_kWh"},
        ]
        points = adapter.fetch(data=data)
        assert len(points) == 1
        assert points[0].value == 0.25
        assert points[0].unit == "EUR_per_kWh"

    @pytest.mark.unit
    def test_invalid_template_returns_zero(self) -> None:
        adapter = TemplateAdapter()
        points = adapter.fetch(template="invalid_python(", hours=3)
        assert len(points) == 3
        assert all(p.value == 0.0 for p in points)
