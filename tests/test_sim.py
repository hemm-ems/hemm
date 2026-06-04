"""Tests for the simulation harness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hemm_core.sim.runner import SimRunner
from hemm_core.sim.scenario import Scenario, load_scenario
from hemm_core.sim.synthetic import generate_price_series, generate_weather_series

TESTDATA_DIR = Path(__file__).parent.parent / "testdata"
SCENARIOS_DIR = TESTDATA_DIR / "scenarios"


@pytest.mark.req("005:FR-006")
class TestSyntheticSeries:
    """Tests for synthetic time series generators."""

    @pytest.mark.unit
    def test_price_series_length(self) -> None:
        series = generate_price_series(hours=24, resolution_minutes=15)
        assert len(series) == 96  # 24h * 4 slots/h

    @pytest.mark.unit
    def test_price_series_has_timestamps(self) -> None:
        t0 = datetime(2026, 5, 6, 0, 0, tzinfo=UTC)
        series = generate_price_series(start=t0, hours=24, resolution_minutes=15)
        assert series[0][0] == t0
        assert series[1][0] == t0 + timedelta(minutes=15)

    @pytest.mark.unit
    def test_price_series_values_in_range(self) -> None:
        series = generate_price_series(hours=24, base_price=0.30, peak_price=0.45, off_peak_price=0.20)
        for _, price in series:
            assert 0.10 <= price <= 0.60

    @pytest.mark.unit
    def test_weather_series_length(self) -> None:
        series = generate_weather_series(hours=24, resolution_minutes=60)
        assert len(series) == 24

    @pytest.mark.unit
    def test_weather_series_temp_range(self) -> None:
        series = generate_weather_series(min_temp_c=0.0, max_temp_c=15.0, hours=24)
        for _, temp in series:
            assert -1 <= temp <= 16  # slight tolerance

    @pytest.mark.unit
    def test_weather_series_has_variation(self) -> None:
        series = generate_weather_series(min_temp_c=0.0, max_temp_c=15.0, hours=24)
        temps = [t for _, t in series]
        assert max(temps) - min(temps) > 5.0  # meaningful variation


@pytest.mark.req("005:FR-001", "005:FR-003")
class TestScenarioLoading:
    """Tests for scenario file loading."""

    @pytest.mark.unit
    def test_load_onboarding_scenario(self) -> None:
        path = SCENARIOS_DIR / "onboarding.yaml"
        if not path.exists():
            pytest.skip("Scenario file not found")
        scenario = load_scenario(path)
        assert scenario.name == "onboarding"
        assert scenario.horizon_hours == 24
        assert scenario.resolution_minutes == 15
        assert len(scenario.manifests) > 0

    @pytest.mark.unit
    def test_load_battery_arbitrage(self) -> None:
        path = SCENARIOS_DIR / "battery_arbitrage.yaml"
        if not path.exists():
            pytest.skip("Scenario file not found")
        scenario = load_scenario(path)
        assert scenario.name == "battery_arbitrage"
        assert len(scenario.manifests) == 1

    @pytest.mark.unit
    def test_load_nonexistent_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_scenario("/nonexistent/path.yaml")

    @pytest.mark.unit
    def test_scenario_has_tags(self) -> None:
        path = SCENARIOS_DIR / "onboarding.yaml"
        if not path.exists():
            pytest.skip("Scenario file not found")
        scenario = load_scenario(path)
        assert "onboarding" in scenario.tags

    @pytest.mark.unit
    @pytest.mark.req("003:FR-012")
    def test_pool_pump_scenario_loads(self) -> None:
        path = SCENARIOS_DIR / "pool_pump.yaml"
        scenario = load_scenario(path)
        assert scenario.name == "pool_pump"
        assert scenario.manifests[0]["type"] == "pool_pump"

    @pytest.mark.unit
    def test_all_six_scenarios_loadable(self) -> None:
        """All 6 standard scenarios load without error."""
        scenario_files = [
            "onboarding.yaml",
            "battery_arbitrage.yaml",
            "heat_pump_shift.yaml",
            "ev_departure.yaml",
            "water_heater_legionella.yaml",
            "full_house.yaml",
        ]
        for name in scenario_files:
            path = SCENARIOS_DIR / name
            if not path.exists():
                pytest.skip(f"Scenario file not found: {name}")
            scenario = load_scenario(path)
            assert scenario.name


@pytest.mark.req("005:FR-002")
class TestSimRunner:
    """Tests for the simulation runner."""

    @pytest.mark.unit
    def test_run_minimal_scenario(self) -> None:
        """Runner handles a minimal inline scenario."""
        scenario = Scenario(
            name="minimal",
            horizon_hours=4,
            resolution_minutes=15,
            days=1,
            manifests=[
                {
                    "type": "battery",
                    "device_id": "bat1",
                    "name": "Test Bat",
                    "capacity_kwh": 10.0,
                    "max_charge_kw": 5.0,
                    "max_discharge_kw": 5.0,
                    "safe_default": {
                        "script": "script.bat_safe",
                        "verify": {"entity": "sensor.bat", "expected": "== 0", "within_seconds": 30},
                    },
                }
            ],
        )
        runner = SimRunner()
        result = runner.run(scenario)
        assert result.success
        assert result.scenario_name == "minimal"
        assert result.total_solve_time_seconds > 0
        assert len(result.plans) > 0

    @pytest.mark.unit
    def test_run_invalid_manifest_fails(self) -> None:
        """Runner reports failure on invalid manifest."""
        scenario = Scenario(
            name="invalid",
            manifests=[{"type": "unknown_type"}],
        )
        runner = SimRunner()
        result = runner.run(scenario)
        assert not result.success
        assert result.error is not None

    @pytest.mark.unit
    def test_metrics_accumulated(self) -> None:
        """Metrics are accumulated correctly."""
        scenario = Scenario(
            name="metrics_test",
            horizon_hours=4,
            resolution_minutes=60,
            days=1,
            manifests=[
                {
                    "type": "ev_charger",
                    "device_id": "ev1",
                    "name": "Test EV",
                    "max_charge_kw": 11.0,
                    "safe_default": {
                        "script": "script.ev_safe",
                        "verify": {"entity": "sensor.ev", "expected": "== 0", "within_seconds": 30},
                    },
                }
            ],
        )
        runner = SimRunner()
        result = runner.run(scenario)
        assert result.success
        assert len(result.metrics.solve_times) == 1
        assert result.metrics.solve_times[0] >= 0


class TestSimRunnerScenarios:
    """Integration tests running the standard scenarios (marked slow)."""

    @pytest.mark.slow
    def test_onboarding_scenario_solves_fast(self) -> None:
        """Onboarding scenario solves in < 1 second."""
        path = SCENARIOS_DIR / "onboarding.yaml"
        if not path.exists():
            pytest.skip("Scenario file not found")
        scenario = load_scenario(path)
        runner = SimRunner()
        result = runner.run(scenario)
        assert result.success
        assert result.total_solve_time_seconds < 1.0

    @pytest.mark.slow
    def test_battery_arbitrage_solves(self) -> None:
        path = SCENARIOS_DIR / "battery_arbitrage.yaml"
        if not path.exists():
            pytest.skip("Scenario file not found")
        scenario = load_scenario(path)
        runner = SimRunner()
        result = runner.run(scenario)
        assert result.success

    @pytest.mark.slow
    def test_all_standard_scenarios_solve(self) -> None:
        """All 6 standard scenarios solve successfully."""
        scenario_files = [
            "onboarding.yaml",
            "battery_arbitrage.yaml",
            "heat_pump_shift.yaml",
            "ev_departure.yaml",
            "water_heater_legionella.yaml",
            "full_house.yaml",
        ]
        for name in scenario_files:
            path = SCENARIOS_DIR / name
            if not path.exists():
                pytest.skip(f"Scenario file not found: {name}")
            scenario = load_scenario(path)
            runner = SimRunner()
            result = runner.run(scenario)
            assert result.success, f"Scenario {name} failed: {result.error}"

    @pytest.mark.slow
    @pytest.mark.req("003:FR-012")
    def test_pool_pump_scenario_plans_with_power(self) -> None:
        path = SCENARIOS_DIR / "pool_pump.yaml"
        scenario = load_scenario(path)
        runner = SimRunner()
        result = runner.run(scenario)
        assert result.success, result.error
        plan = next(plan for plan in result.plans if plan.device_id == "pool_pump")
        assert sum(slot.power_kw for slot in plan.slots) > 0.0
