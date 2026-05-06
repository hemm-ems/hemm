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

    args = parser.parse_args(argv)

    if args.command == "info":
        print(f"hemm {_get_version()}")
        return 0

    if args.command == "schema":
        return _cmd_schema(args)

    if args.command == "validate":
        return _cmd_validate(args)

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


def _get_version() -> str:
    from hemm import __version__

    return __version__


if __name__ == "__main__":
    sys.exit(main())
