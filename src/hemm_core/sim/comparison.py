"""A/B comparison runner — runs both solver backends on identical scenarios and produces reports."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

from hemm_core.sim.runner import SimRunner
from hemm_core.sim.scenario import Scenario
from hemm_core.solvers.distributed import DistributedSolver
from hemm_core.solvers.milp_central import MILPCentralSolver
from hemm_core.time import Clock, WallClock


@dataclass
class ComparisonMetrics:
    """Metrics for comparing two solver backends."""

    scenario_name: str
    # Backend A (MILP central)
    a_cost_eur: float = 0.0
    a_energy_kwh: float = 0.0
    a_solve_time_s: float = 0.0
    a_plan_changes: int = 0
    a_constraint_violations: int = 0
    a_status: str = ""
    # Backend B (distributed)
    b_cost_eur: float = 0.0
    b_energy_kwh: float = 0.0
    b_solve_time_s: float = 0.0
    b_plan_changes: int = 0
    b_constraint_violations: int = 0
    b_iterations: int = 0
    b_converged: bool = False
    b_status: str = ""
    # Comparison
    cost_gap_pct: float = 0.0
    comfort_violations_diff: int = 0
    plan_stability_ratio: float = 0.0
    speed_ratio: float = 0.0


def _now_utc() -> datetime:
    # The audit (`tools/check_clock.py`) flags direct `datetime.now`. Here the
    # call is only used as a dataclass `default_factory` for `ComparisonReport`;
    # callers that want deterministic timestamps build a runner with a `clock`
    # and pass `timestamp=clock.now()` explicitly.
    return WallClock().now()


@dataclass
class ComparisonReport:
    """Full A/B comparison report."""

    scenarios: list[ComparisonMetrics] = field(default_factory=list)
    total_time_seconds: float = 0.0
    timestamp: datetime = field(default_factory=_now_utc)
    summary: str = ""

    def to_csv(self) -> str:
        """Export comparison to CSV format."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "scenario",
                "a_cost_eur",
                "b_cost_eur",
                "cost_gap_pct",
                "a_solve_time_s",
                "b_solve_time_s",
                "speed_ratio",
                "a_energy_kwh",
                "b_energy_kwh",
                "a_plan_changes",
                "b_plan_changes",
                "plan_stability_ratio",
                "a_violations",
                "b_violations",
                "b_iterations",
                "b_converged",
                "a_status",
                "b_status",
            ]
        )
        for m in self.scenarios:
            writer.writerow(
                [
                    m.scenario_name,
                    f"{m.a_cost_eur:.4f}",
                    f"{m.b_cost_eur:.4f}",
                    f"{m.cost_gap_pct:.2f}",
                    f"{m.a_solve_time_s:.3f}",
                    f"{m.b_solve_time_s:.3f}",
                    f"{m.speed_ratio:.2f}",
                    f"{m.a_energy_kwh:.2f}",
                    f"{m.b_energy_kwh:.2f}",
                    m.a_plan_changes,
                    m.b_plan_changes,
                    f"{m.plan_stability_ratio:.2f}",
                    m.a_constraint_violations,
                    m.b_constraint_violations,
                    m.b_iterations,
                    m.b_converged,
                    m.a_status,
                    m.b_status,
                ]
            )
        return output.getvalue()

    def to_markdown(self) -> str:
        """Export comparison as Markdown summary."""
        lines: list[str] = []
        lines.append("# HEMM A/B Solver Comparison Report")
        lines.append("")
        lines.append(f"**Generated:** {self.timestamp.isoformat()}")
        lines.append(f"**Total runtime:** {self.total_time_seconds:.1f}s")
        lines.append("")
        lines.append("## Summary")
        lines.append("")

        if self.scenarios:
            avg_gap = sum(m.cost_gap_pct for m in self.scenarios) / len(self.scenarios)
            avg_speed = sum(m.speed_ratio for m in self.scenarios) / len(self.scenarios)
            total_a_violations = sum(m.a_constraint_violations for m in self.scenarios)
            total_b_violations = sum(m.b_constraint_violations for m in self.scenarios)
            converged_count = sum(1 for m in self.scenarios if m.b_converged)

            lines.append(f"- **Scenarios tested:** {len(self.scenarios)}")
            lines.append(f"- **Avg cost gap (B vs A):** {avg_gap:+.2f}%")
            lines.append(f"- **Avg speed ratio (B/A):** {avg_speed:.2f}x")
            lines.append(f"- **Backend A violations:** {total_a_violations}")
            lines.append(f"- **Backend B violations:** {total_b_violations}")
            lines.append(f"- **Backend B convergence:** {converged_count}/{len(self.scenarios)}")

        lines.append("")
        lines.append("## Per-Scenario Results")
        lines.append("")
        lines.append("| Scenario | Cost A (€) | Cost B (€) | Gap % | Time A | Time B | B Converged |")
        lines.append("|----------|-----------|-----------|-------|--------|--------|-------------|")

        for m in self.scenarios:
            lines.append(
                f"| {m.scenario_name} | {m.a_cost_eur:.2f} | {m.b_cost_eur:.2f} | "
                f"{m.cost_gap_pct:+.1f}% | {m.a_solve_time_s:.3f}s | {m.b_solve_time_s:.3f}s | "
                f"{'Yes' if m.b_converged else 'No'} |"
            )

        lines.append("")
        lines.append("## Decision Metrics (Phase 6 Gate)")
        lines.append("")
        lines.append("| Metric | Threshold | Result | Pass |")
        lines.append("|--------|-----------|--------|------|")

        if self.scenarios:
            avg_gap = sum(m.cost_gap_pct for m in self.scenarios) / len(self.scenarios)
            lines.append(f"| Cost gap (avg) | < 3% | {abs(avg_gap):.2f}% | {'PASS' if abs(avg_gap) < 3 else 'FAIL'} |")

            b_worse = sum(1 for m in self.scenarios if m.b_constraint_violations > m.a_constraint_violations)
            lines.append(
                f"| Comfort violations | B ≤ A | {b_worse} scenarios worse | {'PASS' if b_worse == 0 else 'FAIL'} |"
            )

            stability_ratios = [m.plan_stability_ratio for m in self.scenarios if m.plan_stability_ratio > 0]
            if stability_ratios:
                max_stability = max(stability_ratios)
                lines.append(
                    f"| Plan stability | <= 1.5x A | {max_stability:.2f}x | "
                    f"{'PASS' if max_stability <= 1.5 else 'FAIL'} |"
                )

        lines.append("")
        return "\n".join(lines)


class ABComparisonRunner:
    """Runs identical scenarios through both solver backends and compares results."""

    def __init__(
        self,
        solver_a: MILPCentralSolver | None = None,
        solver_b: DistributedSolver | None = None,
        outdoor_temp_c: float = 5.0,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._clock: Clock = clock if clock is not None else WallClock()
        self._solver_a = solver_a or MILPCentralSolver(outdoor_temp_c=outdoor_temp_c, clock=self._clock)
        self._solver_b = solver_b or DistributedSolver(outdoor_temp_c=outdoor_temp_c, clock=self._clock)
        self._outdoor_temp_c = outdoor_temp_c

    def compare_scenario(self, scenario: Scenario) -> ComparisonMetrics:
        """Run a single scenario through both backends and compare.

        Args:
            scenario: Scenario to run.

        Returns:
            ComparisonMetrics for this scenario.
        """
        # Run Backend A
        runner_a = SimRunner(solver=self._solver_a, clock=self._clock)
        result_a = runner_a.run(scenario)

        # Run Backend B
        runner_b = SimRunner(solver=self._solver_b, clock=self._clock)
        result_b = runner_b.run(scenario)

        # Compute comparison metrics
        metrics = ComparisonMetrics(scenario_name=scenario.name)

        # Backend A metrics
        metrics.a_cost_eur = result_a.metrics.total_cost_eur
        metrics.a_energy_kwh = result_a.metrics.total_energy_kwh
        metrics.a_solve_time_s = result_a.total_solve_time_seconds
        metrics.a_plan_changes = result_a.metrics.plan_changes
        metrics.a_constraint_violations = result_a.metrics.constraint_violations
        metrics.a_status = "success" if result_a.success else "failed"

        # Backend B metrics
        metrics.b_cost_eur = result_b.metrics.total_cost_eur
        metrics.b_energy_kwh = result_b.metrics.total_energy_kwh
        metrics.b_solve_time_s = result_b.total_solve_time_seconds
        metrics.b_plan_changes = result_b.metrics.plan_changes
        metrics.b_constraint_violations = result_b.metrics.constraint_violations
        metrics.b_status = "success" if result_b.success else "failed"

        # Distributed-specific
        if result_b.solver_results:
            last_result = result_b.solver_results[-1]
            metrics.b_iterations = last_result.iterations
            metrics.b_converged = last_result.diagnostics.get("converged", False) is True

        # Comparison metrics
        if metrics.a_cost_eur != 0:
            metrics.cost_gap_pct = (metrics.b_cost_eur - metrics.a_cost_eur) / abs(metrics.a_cost_eur) * 100
        elif metrics.b_cost_eur != 0:
            metrics.cost_gap_pct = 100.0
        else:
            metrics.cost_gap_pct = 0.0

        metrics.comfort_violations_diff = metrics.b_constraint_violations - metrics.a_constraint_violations

        if metrics.a_plan_changes > 0:
            metrics.plan_stability_ratio = metrics.b_plan_changes / metrics.a_plan_changes
        else:
            metrics.plan_stability_ratio = 1.0

        if metrics.a_solve_time_s > 0:
            metrics.speed_ratio = metrics.b_solve_time_s / metrics.a_solve_time_s
        else:
            metrics.speed_ratio = 1.0

        return metrics

    def compare_scenarios(self, scenarios: list[Scenario]) -> ComparisonReport:
        """Run multiple scenarios and produce a full comparison report.

        Args:
            scenarios: List of scenarios to compare.

        Returns:
            ComparisonReport with all metrics and summary.
        """
        start_time = self._clock.monotonic()
        report = ComparisonReport(timestamp=self._clock.now())

        for scenario in scenarios:
            metrics = self.compare_scenario(scenario)
            report.scenarios.append(metrics)

        report.total_time_seconds = self._clock.monotonic() - start_time

        # Generate summary
        if report.scenarios:
            avg_gap = sum(m.cost_gap_pct for m in report.scenarios) / len(report.scenarios)
            converged = sum(1 for m in report.scenarios if m.b_converged)
            report.summary = (
                f"{len(report.scenarios)} scenarios compared. "
                f"Avg cost gap: {avg_gap:+.2f}%. "
                f"Backend B converged: {converged}/{len(report.scenarios)}."
            )

        return report
