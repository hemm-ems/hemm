"""HEMM — Distributed Energy Optimizer for Home Automation."""

import tomllib
from importlib import metadata
from pathlib import Path


def _read_project_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        # Keep in sync with the version in pyproject.toml.
        return "2026.7.3"
    project = data.get("project")
    if isinstance(project, dict):
        version = project.get("version")
        if isinstance(version, str):
            return version
    # Keep in sync with the version in pyproject.toml.
    return "2026.7.3"


try:
    __version__ = metadata.version("hemm")
except metadata.PackageNotFoundError:
    __version__ = _read_project_version()
