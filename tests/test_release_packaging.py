"""Release packaging guards for distribution requirements."""

from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.unit
@pytest.mark.req("009:FR-004")
def test_package_version_matches_module_version() -> None:
    """The importable version follows the installed distribution metadata."""
    import hemm_core

    assert hemm_core.__version__ == importlib.metadata.version("hemm")


@pytest.mark.unit
@pytest.mark.req("009:FR-001")
def test_release_workflow_publishes_to_pypi_with_oidc() -> None:
    """The release workflow uses PyPI Trusted Publishing, not stored secrets."""
    workflow_path = REPO_ROOT / ".github" / "workflows" / "release.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)

    publish_job = _find_pypi_publish_job(workflow)

    assert publish_job["permissions"]["id-token"] == "write"
    assert publish_job["environment"] == "pypi"

    publish_steps = [
        step for step in publish_job["steps"] if str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish@")
    ]
    assert publish_steps, "release.yml must publish with pypa/gh-action-pypi-publish"
    for step in publish_steps:
        action_ref = step["uses"].split("@", 1)[1]
        assert re.fullmatch(r"[0-9a-f]{40}", action_ref), "PyPI publish action must be pinned to a full SHA"

    assert not re.search(r"pypi[^\n]*(token|password|secret)", workflow_text, re.IGNORECASE)
    assert not re.search(r"(password|api-token):\s*\$\{\{\s*secrets\.", workflow_text, re.IGNORECASE)


def _find_pypi_publish_job(workflow: dict[str, Any]) -> dict[str, Any]:
    jobs = workflow.get("jobs", {})
    for job in jobs.values():
        steps = job.get("steps", [])
        if any(str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish@") for step in steps):
            return job
    raise AssertionError("No PyPI publish job found")
