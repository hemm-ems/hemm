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
    sim_run_parser.add_argument(
        "--solver", choices=["milp_central", "distributed"], default="milp_central", help="Solver backend"
    )

    # Compare command
    compare_parser = sim_subparsers.add_parser("compare", help="A/B comparison of solver backends")
    compare_parser.add_argument("scenarios", nargs="+", help="Scenario YAML files to compare")
    compare_parser.add_argument("--output", "-o", help="Output file (CSV or Markdown based on extension)")
    compare_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

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
    from hemm.manifest.schema_export import (
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

    from hemm.manifest.validator import ValidationError, validate_manifest

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

    if args.sim_command != "run":
        print("Usage: hemm sim run <scenario.yaml> | hemm sim compare <scenarios...>", file=sys.stderr)
        return 1

    from hemm.sim.runner import SimRunner
    from hemm.sim.scenario import load_scenario

    scenario_path: str = args.scenario
    verbose: bool = args.verbose
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
        from hemm.solvers.distributed import DistributedSolver

        solver = DistributedSolver()
    else:
        from hemm.solvers.milp_central import MILPCentralSolver

        solver = MILPCentralSolver()

    runner = SimRunner(solver=solver)
    result = runner.run(scenario)

    if result.success:
        print(f"OK: {result.scenario_name}")
        print(f"  Solve time: {result.total_solve_time_seconds:.3f}s")
        print(f"  Total cost: €{result.metrics.total_cost_eur:.2f}")
        print(f"  Total energy: {result.metrics.total_energy_kwh:.1f} kWh")
        if result.metrics.solve_times:
            print(f"  Avg solve: {sum(result.metrics.solve_times) / len(result.metrics.solve_times):.3f}s")
        return 0
    else:
        print(f"FAILED: {result.scenario_name}", file=sys.stderr)
        if result.error:
            print(f"  Error: {result.error}", file=sys.stderr)
        return 1


def _cmd_sim_compare(args: argparse.Namespace) -> int:
    """Run A/B comparison across scenarios."""
    import pathlib

    from hemm.sim.comparison import ABComparisonRunner
    from hemm.sim.scenario import load_scenario

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
    from hemm import __version__

    return __version__


if __name__ == "__main__":
    sys.exit(main())
