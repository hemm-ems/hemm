"""Smoke tests for hemm core — verifies basic importability and CLI."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.unit
class TestImport:
    """Verify the package is importable."""

    def test_import_hemm(self) -> None:
        import hemm

        assert hemm.__version__ == "0.1.0"

    def test_import_cli(self) -> None:
        from hemm.cli import main

        assert callable(main)


@pytest.mark.unit
class TestCLI:
    """Verify CLI entry point works."""

    def test_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "hemm.cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "HEMM" in result.stdout

    def test_version(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "hemm.cli", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "0.1.0" in result.stdout

    def test_info_command(self) -> None:
        from hemm.cli import main

        assert main(["info"]) == 0

    def test_no_command(self) -> None:
        from hemm.cli import main

        assert main([]) == 0
