"""HEMM CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    """Run the HEMM CLI."""
    parser = argparse.ArgumentParser(
        prog="hemm",
        description="HEMM — Distributed Energy Optimizer for Home Automation",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_get_version()}")

    subparsers = parser.add_subparsers(dest="command")

    # Info command
    subparsers.add_parser("info", help="Show system information")

    # Schema export command
    schema_parser = subparsers.add_parser("schema", help="Export JSON schemas")
    schema_parser.add_argument(
        "schema_type",
        nargs="?",
        default="all",
        help="Schema to export: 'all', or type like 'room', 'battery', 'plan_message', etc.",
    )
    schema_parser.add_argument("--indent", type=int, default=2, help="JSON indentation level")

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate manifest files")
    validate_parser.add_argument("files", nargs="+", help="Manifest JSON files to validate")

    # Sim command
    sim_parser = subparsers.add_parser("sim", help="Run simulation scenarios")
    sim_subparsers = sim_parser.add_subparsers(dest="sim_command")
    sim_run_parser = sim_subparsers.add_parser("run", help="Run a scenario file")
    sim_run_parser.add_argument("scenario", help="Path to scenario YAML file")
    sim_run_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    sim_run_parser.add_argument("--ab-interventions", action="store_true", help="Run baseline and intervention delta")
    sim_run_parser.add_argument(
        "--solver", choices=["milp_central", "distributed"], default="milp_central", help="Solver backend"
    )

    bake_parser = sim_subparsers.add_parser("bake-profile", help="Bake a household profile")
    bake_parser.add_argument("--archetype", required=True, help="Household archetype")
    bake_parser.add_argument("--year", type=int, required=True, help="Profile year")
    bake_parser.add_argument("--seed", type=int, required=True, help="Deterministic seed")
    bake_parser.add_argument("--output", "-o", required=True, help="Output .parquet or .csv path")
    bake_parser.add_argument("--resolution-minutes", type=int, default=15, help="Profile resolution")
    bake_parser.add_argument("--lpg-version", default="unknown", help="LPG version string for cache attribution")
    bake_parser.add_argument("--synthetic-fixture", action="store_true", help="Write deterministic fixture data")

    # Compare command
    compare_parser = sim_subparsers.add_parser("compare", help="A/B comparison of solver backends")
    compare_parser.add_argument("scenarios", nargs="+", help="Scenario YAML files to compare")
    compare_parser.add_argument("--output", "-o", help="Output file (CSV or Markdown based on extension)")
    compare_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    sweep_parser = sim_subparsers.add_parser("sweep", help="Run multiple scenarios and emit a savings table")
    sweep_parser.add_argument("scenarios", nargs="+", help="Scenario YAML files to run")

    args = parser.parse_args(argv)

    if args.command == "info":
        print(f"hemm {_get_version()}")
        return 0

    if args.command == "schema":
        return _cmd_schema(args)

    if args.command == "validate":
        return _cmd_validate(args)

    if args.command == "sim":
        return _cmd_sim(args)

    parser.print_help()
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    """Export JSON schemas."""
    from hemm_core.manifest.schema_export import (
        export_schemas_json,
        get_constraint_schema,
        get_manifest_schema,
        get_message_schema,
    )

    schema_type: str = args.schema_type
    indent: int = args.indent

    if schema_type == "all":
        print(export_schemas_json(indent=indent))
        return 0

    # Try manifest types first, then constraints, then messages
    try:
        schema = get_manifest_schema(schema_type)
    except ValueError:
        try:
            schema = get_constraint_schema(schema_type)
        except ValueError:
            try:
                schema = get_message_schema(schema_type)
            except ValueError:
                print(f"Error: Unknown schema type '{schema_type}'.", file=sys.stderr)
                print("Use 'hemm schema all' to see available types.", file=sys.stderr)
                return 1

    print(json.dumps(schema, indent=indent))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate manifest files."""
    import pathlib

    from hemm_core.manifest.validator import ValidationError, validate_manifest

    all_ok = True
    for filepath in args.files:
        path = pathlib.Path(filepath)
        if not path.exists():
            print(f"ERROR: File not found: {filepath}", file=sys.stderr)
            all_ok = False
            continue

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"ERROR: {filepath}: Invalid JSON: {e}", file=sys.stderr)
            all_ok = False
            continue

        try:
            validate_manifest(data)
            print(f"OK: {filepath}")
        except ValidationError as e:
            print(f"ERROR: {filepath}:", file=sys.stderr)
            for err in e.errors:
                print(f"  - {err}", file=sys.stderr)
            all_ok = False

    return 0 if all_ok else 1


def _cmd_sim(args: argparse.Namespace) -> int:
    """Run simulation scenarios."""
    if args.sim_command == "compare":
        return _cmd_sim_compare(args)
    if args.sim_command == "bake-profile":
        return _cmd_sim_bake_profile(args)
    if args.sim_command == "sweep":
        return _cmd_sim_sweep(args)

    if args.sim_command != "run":
        print("Usage: hemm sim run <scenario.yaml> | hemm sim compare <scenarios...>", file=sys.stderr)
        return 1

    from hemm_core.sim.runner import SimRunner
    from hemm_core.sim.scenario import load_scenario

    scenario_path: str = args.scenario
    verbose: bool = args.verbose
    ab_interventions: bool = args.ab_interventions
    solver_name: str = args.solver

    try:
        scenario = load_scenario(scenario_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if verbose:
        print(f"Running scenario: {scenario.name}")
        print(f"  Devices: {len(scenario.manifests)}")
        print(f"  Horizon: {scenario.horizon_hours}h @ {scenario.resolution_minutes}min")
        print(f"  Days: {scenario.days}")
        print(f"  Solver: {solver_name}")

    # Select solver
    solver: object
    if solver_name == "distributed":
        from hemm_core.solvers.distributed import DistributedSolver

        solver = DistributedSolver()
    else:
        from hemm_core.solvers.milp_central import MILPCentralSolver

        solver = MILPCentralSolver()

    runner = SimRunner(solver=solver)
    if ab_interventions:
        from dataclasses import replace

        baseline_result = runner.run(replace(scenario, interventions=[]))
        intervention_result = runner.run(scenario)
        if not baseline_result.success:
            print(f"FAILED baseline: {baseline_result.error}", file=sys.stderr)
            return 1
        if not intervention_result.success:
            print(f"FAILED interventions: {intervention_result.error}", file=sys.stderr)
            return 1
        print(f"OK: {scenario.name}")
        print(f"  Baseline cost: €{baseline_result.metrics.total_cost_eur:.2f}")
        print(f"  Intervention cost: €{intervention_result.metrics.total_cost_eur:.2f}")
        print(
            f"  Delta cost: €{intervention_result.metrics.total_cost_eur - baseline_result.metrics.total_cost_eur:+.2f}"
        )
        print(
            "  Delta energy: "
            f"{intervention_result.metrics.total_energy_kwh - baseline_result.metrics.total_energy_kwh:+.1f} kWh"
        )
        print(f"  Peak power: {intervention_result.metrics.peak_total_power_kw:.1f} kW")
        return 0

    result = runner.run(scenario)

    if result.success:
        print(f"OK: {result.scenario_name}")
        print(f"  Solve time: {result.total_solve_time_seconds:.3f}s")
        print(f"  Total cost: €{result.metrics.total_cost_eur:.2f}")
        print(f"  Total energy: {result.metrics.total_energy_kwh:.1f} kWh")
        if result.metrics.household_energy_kwh:
            print(f"  Household demand: {result.metrics.household_energy_kwh:.1f} kWh")
            print(f"  Peak total power: {result.metrics.peak_total_power_kw:.1f} kW")
        if result.metrics.solve_times:
            print(f"  Avg solve: {sum(result.metrics.solve_times) / len(result.metrics.solve_times):.3f}s")
        return 0
    else:
        print(f"FAILED: {result.scenario_name}", file=sys.stderr)
        if result.error:
            print(f"  Error: {result.error}", file=sys.stderr)
        return 1


def _cmd_sim_bake_profile(args: argparse.Namespace) -> int:
    """Bake a canonical household profile."""
    from pathlib import Path

    from hemm_core.sim.occupants.lpg import bake_lpg_profile

    try:
        profile = bake_lpg_profile(
            archetype=args.archetype,
            year=args.year,
            seed=args.seed,
            output=Path(args.output),
            resolution_minutes=args.resolution_minutes,
            lpg_version=args.lpg_version,
            synthetic_fixture=args.synthetic_fixture,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"OK: wrote {args.output}")
    print(f"  Slots: {len(profile.slots)}")
    print(f"  Source: {profile.source}")
    return 0


def _cmd_sim_sweep(args: argparse.Namespace) -> int:
    """Run a compact intervention sweep."""
    from dataclasses import replace

    from hemm_core.sim.runner import SimRunner
    from hemm_core.sim.scenario import load_scenario

    runner = SimRunner()
    rows = []
    for path in args.scenarios:
        try:
            scenario = load_scenario(path)
        except (FileNotFoundError, ValueError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        baseline = runner.run(replace(scenario, interventions=[]))
        intervention = runner.run(scenario)
        if not baseline.success or not intervention.success:
            print(f"ERROR: {scenario.name}: {baseline.error or intervention.error}", file=sys.stderr)
            return 1
        rows.append(
            (
                scenario.name,
                baseline.metrics.total_cost_eur,
                intervention.metrics.total_cost_eur,
                intervention.metrics.total_cost_eur - baseline.metrics.total_cost_eur,
                intervention.metrics.peak_total_power_kw,
            )
        )

    print("| Scenario | Baseline € | Interventions € | Delta € | Peak kW |")
    print("|---|---:|---:|---:|---:|")
    for name, base, inter, delta, peak in rows:
        print(f"| {name} | {base:.2f} | {inter:.2f} | {delta:+.2f} | {peak:.1f} |")
    return 0


def _cmd_sim_compare(args: argparse.Namespace) -> int:
    """Run A/B comparison across scenarios."""
    import pathlib

    from hemm_core.sim.comparison import ABComparisonRunner
    from hemm_core.sim.scenario import load_scenario

    verbose: bool = args.verbose
    output_path: str | None = args.output

    scenarios = []
    for path_str in args.scenarios:
        try:
            scenario = load_scenario(path_str)
            scenarios.append(scenario)
        except (FileNotFoundError, ValueError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1

    if verbose:
        print(f"Comparing {len(scenarios)} scenarios with Backend A (MILP) vs Backend B (Distributed)...")

    runner = ABComparisonRunner()
    report = runner.compare_scenarios(scenarios)

    # Output
    if output_path:
        out = pathlib.Path(output_path)
        if out.suffix == ".csv":
            out.write_text(report.to_csv(), encoding="utf-8")
        else:
            out.write_text(report.to_markdown(), encoding="utf-8")
        print(f"Report written to: {output_path}")
    else:
        print(report.to_markdown())

    return 0


def _get_version() -> str:
    from hemm_core import __version__

    return __version__


if __name__ == "__main__":
    sys.exit(main())
