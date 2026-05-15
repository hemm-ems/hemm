"""Tests for the A/B comparison runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from hemm_core.sim.comparison import ABComparisonRunner, ComparisonMetrics, ComparisonReport
from hemm_core.sim.scenario import Scenario, load_scenario
from hemm_core.solvers.distributed import DistributedSolver
from hemm_core.solvers.milp_central import MILPCentralSolver

TESTDATA = Path(__file__).parent.parent / "testdata"
SCENARIOS_DIR = TESTDATA / "scenarios"


def _make_simple_scenario() -> Scenario:
    """Create a minimal scenario for testing."""
    return Scenario(
        name="test_simple",
        horizon_hours=4,
        resolution_minutes=15,
        days=1,
        manifests=[
            {
                "type": "battery",
                "device_id": "bat_test",
                "name": "Test Battery",
                "capacity_kwh": 10.0,
                "max_charge_kw": 5.0,
                "max_discharge_kw": 5.0,
                "safe_default": {
                    "script": "script.bat_safe",
                    "verify": {"entity": "sensor.bat", "expected": "== 0", "within_seconds": 30},
                },
            }
        ],
        price_params={"base_price": 0.30, "peak_price": 0.45, "off_peak_price": 0.20},
    )


class TestComparisonMetrics:
    """Tests for ComparisonMetrics dataclass."""

    @pytest.mark.unit
    def test_default_values(self) -> None:
        m = ComparisonMetrics(scenario_name="test")
        assert m.cost_gap_pct == 0.0
        assert m.plan_stability_ratio == 0.0


class TestComparisonReport:
    """Tests for ComparisonReport."""

    @pytest.mark.unit
    def test_to_csv_empty(self) -> None:
        report = ComparisonReport()
        csv_str = report.to_csv()
        assert "scenario" in csv_str  # header row

    @pytest.mark.unit
    def test_to_csv_with_data(self) -> None:
        report = ComparisonReport(
            scenarios=[ComparisonMetrics(scenario_name="test", a_cost_eur=10.0, b_cost_eur=10.5, cost_gap_pct=5.0)]
        )
        csv_str = report.to_csv()
        assert "test" in csv_str
        assert "10.0000" in csv_str

    @pytest.mark.unit
    def test_to_markdown(self) -> None:
        report = ComparisonReport(
            scenarios=[ComparisonMetrics(scenario_name="test", a_cost_eur=10.0, b_cost_eur=10.5, cost_gap_pct=5.0)]
        )
        md = report.to_markdown()
        assert "# HEMM A/B Solver Comparison Report" in md
        assert "test" in md
        assert "Decision Metrics" in md


class TestABComparisonRunner:
    """Tests for the A/B comparison runner."""

    @pytest.mark.unit
    def test_compare_simple_scenario(self) -> None:
        runner = ABComparisonRunner()
        scenario = _make_simple_scenario()
        metrics = runner.compare_scenario(scenario)
        assert metrics.scenario_name == "test_simple"
        assert metrics.a_status == "success"
        assert metrics.b_status == "success"

    @pytest.mark.unit
    def test_compare_multiple_scenarios(self) -> None:
        runner = ABComparisonRunner()
        scenarios = [_make_simple_scenario(), _make_simple_scenario()]
        scenarios[1].name = "test_simple_2"
        report = runner.compare_scenarios(scenarios)
        assert len(report.scenarios) == 2
        assert report.total_time_seconds > 0
        assert report.summary != ""

    @pytest.mark.unit
    def test_cost_gap_calculated(self) -> None:
        runner = ABComparisonRunner()
        scenario = _make_simple_scenario()
        metrics = runner.compare_scenario(scenario)
        # Both solvers should produce results with some cost
        # Gap should be finite
        assert abs(metrics.cost_gap_pct) < 200  # Sanity check

    @pytest.mark.unit
    def test_report_csv_export(self) -> None:
        runner = ABComparisonRunner()
        report = runner.compare_scenarios([_make_simple_scenario()])
        csv_str = report.to_csv()
        lines = csv_str.strip().split("\n")
        assert len(lines) == 2  # header + 1 data row

    @pytest.mark.unit
    def test_report_markdown_export(self) -> None:
        runner = ABComparisonRunner()
        report = runner.compare_scenarios([_make_simple_scenario()])
        md = report.to_markdown()
        assert "PASS" in md or "FAIL" in md

    @pytest.mark.unit
    def test_custom_solvers(self) -> None:
        solver_a = MILPCentralSolver(time_limit_seconds=10)
        solver_b = DistributedSolver(max_iterations=5, mode="admm")
        runner = ABComparisonRunner(solver_a=solver_a, solver_b=solver_b)
        metrics = runner.compare_scenario(_make_simple_scenario())
        assert metrics.a_status == "success"
        assert metrics.b_status == "success"


class TestABOnStandardScenarios:
    """Tests that A/B comparison works on the standard scenario files."""

    @pytest.mark.unit
    def test_onboarding_scenario(self) -> None:
        scenario = load_scenario(SCENARIOS_DIR / "onboarding.yaml")
        runner = ABComparisonRunner(
            solver_a=MILPCentralSolver(time_limit_seconds=30),
            solver_b=DistributedSolver(max_iterations=20),
        )
        metrics = runner.compare_scenario(scenario)
        assert metrics.a_status == "success"
        assert metrics.b_status == "success"

    @pytest.mark.unit
    def test_battery_arbitrage_scenario(self) -> None:
        scenario = load_scenario(SCENARIOS_DIR / "battery_arbitrage.yaml")
        runner = ABComparisonRunner(
            solver_a=MILPCentralSolver(time_limit_seconds=30),
            solver_b=DistributedSolver(max_iterations=20),
        )
        metrics = runner.compare_scenario(scenario)
        assert metrics.a_status == "success"
        assert metrics.b_status == "success"

    @pytest.mark.slow
    def test_all_standard_scenarios(self) -> None:
        """Run A/B comparison on all 6 standard scenarios."""
        scenario_files = sorted(SCENARIOS_DIR.glob("*.yaml"))
        assert len(scenario_files) >= 6

        scenarios = [load_scenario(f) for f in scenario_files]
        runner = ABComparisonRunner(
            solver_a=MILPCentralSolver(time_limit_seconds=30),
            solver_b=DistributedSolver(max_iterations=30),
        )
        report = runner.compare_scenarios(scenarios)

        assert len(report.scenarios) == len(scenarios)
        # All should succeed
        for m in report.scenarios:
            assert m.a_status == "success", f"Backend A failed on {m.scenario_name}"
            assert m.b_status == "success", f"Backend B failed on {m.scenario_name}"
