"""Product-thesis guard: pool_pump adds zero solver-specific code."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
@pytest.mark.req("003:FR-003")
def test_pool_pump_has_zero_solver_references() -> None:
    """The new named manifest type must not appear in either solver file."""
    repo = Path(__file__).resolve().parent.parent
    solver_paths = [
        repo / "src" / "hemm_core" / "solvers" / "milp_central.py",
        repo / "src" / "hemm_core" / "solvers" / "consumers.py",
    ]

    for path in solver_paths:
        text = path.read_text(encoding="utf-8")
        assert "pool_pump" not in text
        assert "PoolPump" not in text
