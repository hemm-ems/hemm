"""HEMM CLI entry point."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    """Run the HEMM CLI."""
    parser = argparse.ArgumentParser(
        prog="hemm",
        description="HEMM — Distributed Energy Optimizer for Home Automation",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_get_version()}")

    subparsers = parser.add_subparsers(dest="command")

    # Placeholder for future subcommands
    subparsers.add_parser("info", help="Show system information")

    args = parser.parse_args(argv)

    if args.command == "info":
        print(f"hemm {_get_version()}")
        return 0

    parser.print_help()
    return 0


def _get_version() -> str:
    from hemm import __version__

    return __version__


if __name__ == "__main__":
    sys.exit(main())
