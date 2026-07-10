"""Scenario definition — YAML-based scenario files for simulation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Scenario:
    """A simulation scenario with devices, constraints, and configuration."""

    name: str
    description: str = ""
    horizon_hours: int = 24
    resolution_minutes: int = 15
    days: int = 1
    manifests: list[dict[str, Any]] = field(default_factory=list)
    constraint_windows: list[dict[str, Any]] = field(default_factory=list)
    price_profile: str = "default"
    weather_profile: str = "default"
    price_params: dict[str, Any] = field(default_factory=dict)
    weather_params: dict[str, Any] = field(default_factory=dict)
    # Export price (€/kWh). None → exports settle at the import price (FR-002).
    feed_in_tariff: float | None = None
    expected_solve_time_seconds: float | None = None
    tags: list[str] = field(default_factory=list)


def load_scenario(path: str | Path) -> Scenario:
    """Load a scenario from a YAML file.

    Args:
        path: Path to the scenario YAML file.

    Returns:
        Parsed Scenario object.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the YAML is invalid.
    """
    filepath = Path(path)
    if not filepath.exists():
        msg = f"Scenario file not found: {filepath}"
        raise FileNotFoundError(msg)

    content = filepath.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    if not isinstance(data, dict):
        msg = f"Scenario file must contain a YAML mapping: {filepath}"
        raise ValueError(msg)

    # Load manifests from references or inline
    manifests = _load_manifests(data.get("manifests", []), filepath.parent)

    return Scenario(
        name=data.get("name", filepath.stem),
        description=data.get("description", ""),
        horizon_hours=data.get("horizon_hours", 24),
        resolution_minutes=data.get("resolution_minutes", 15),
        days=data.get("days", 1),
        manifests=manifests,
        constraint_windows=data.get("constraint_windows", []),
        price_profile=data.get("price_profile", "default"),
        weather_profile=data.get("weather_profile", "default"),
        price_params=data.get("price_params", {}),
        weather_params=data.get("weather_params", {}),
        feed_in_tariff=data.get("feed_in_tariff"),
        expected_solve_time_seconds=data.get("expected_solve_time_seconds"),
        tags=data.get("tags", []),
    )


def _load_manifests(manifest_specs: list[Any], base_dir: Path) -> list[dict[str, Any]]:
    """Load manifests from file references or inline dicts."""
    manifests: list[dict[str, Any]] = []

    for spec in manifest_specs:
        if isinstance(spec, str):
            # File reference — resolve relative to scenario file
            manifest_path = base_dir / spec
            if not manifest_path.exists():
                msg = f"Referenced manifest not found: {manifest_path}"
                raise FileNotFoundError(msg)
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifests.append(data)
        elif isinstance(spec, dict):
            manifests.append(spec)
        else:
            msg = f"Invalid manifest spec: {spec}"
            raise ValueError(msg)

    return manifests
