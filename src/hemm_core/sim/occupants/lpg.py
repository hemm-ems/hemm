"""LoadProfileGenerator bake and normalization helpers."""

from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from hemm_core.sim.occupants.profile import HouseholdProfile, read_profile, write_profile
from hemm_core.sim.occupants.synthetic import generate_synthetic_profile


def cache_key(*, archetype: str, lpg_version: str, seed: int, year: int, resolution_minutes: int) -> str:
    data = f"{archetype}|{lpg_version}|{seed}|{year}|{resolution_minutes}".encode()
    return hashlib.sha256(data).hexdigest()


def default_cache_path(*, archetype: str, lpg_version: str, seed: int, year: int, resolution_minutes: int) -> Path:
    key = cache_key(
        archetype=archetype,
        lpg_version=lpg_version,
        seed=seed,
        year=year,
        resolution_minutes=resolution_minutes,
    )
    return Path.home() / ".cache" / "hemm" / "profiles" / f"{key}.parquet"


def bake_lpg_profile(
    *,
    archetype: str,
    year: int,
    seed: int,
    output: Path,
    resolution_minutes: int = 15,
    lpg_version: str = "unknown",
    synthetic_fixture: bool = False,
) -> HouseholdProfile:
    """Bake an LPG profile or deterministic synthetic fixture into canonical parquet."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if synthetic_fixture:
        profile = generate_synthetic_profile(
            archetype=archetype,
            seed=seed,
            start=datetime(year, 1, 1, tzinfo=UTC),
            hours=24 * 366,
            resolution_minutes=resolution_minutes,
        )
        write_profile(profile, output)
        return profile

    engine = os.environ.get("HEMM_LPG_ENGINE")
    docker_image = os.environ.get("HEMM_LPG_DOCKER_IMAGE")
    if not engine and not docker_image:
        msg = "Set HEMM_LPG_ENGINE or HEMM_LPG_DOCKER_IMAGE, or pass --synthetic-fixture"
        raise RuntimeError(msg)

    work_dir = output.parent / f"lpg-{archetype}-{year}-s{seed}"
    work_dir.mkdir(parents=True, exist_ok=True)
    cmd = _command(
        engine=engine, docker_image=docker_image, archetype=archetype, year=year, seed=seed, work_dir=work_dir
    )
    subprocess.run(cmd, check=True, timeout=1800)
    profile = normalize_lpg_output(work_dir, resolution_minutes=resolution_minutes)
    profile = HouseholdProfile(
        slots=profile.slots,
        resolution_minutes=profile.resolution_minutes,
        source="lpg",
        archetype=archetype,
        seed=seed,
        metadata={"lpg_version": lpg_version},
    )
    write_profile(profile, output)
    return profile


def normalize_lpg_output(path: Path, *, resolution_minutes: int = 15) -> HouseholdProfile:
    """Normalize LPG output into the canonical profile.

    v1 supports already-normalized CSV/parquet files in the output directory.
    This keeps CI independent from LPG binaries while preserving the adapter
    boundary for real local bakes.
    """
    candidates = [
        *path.glob("*canonical*.parquet"),
        *path.glob("*canonical*.csv"),
        *path.glob("*.parquet"),
        *path.glob("*.csv"),
    ]
    if not candidates:
        msg = f"No normalizable LPG output found in {path}"
        raise FileNotFoundError(msg)
    return read_profile(candidates[0], resolution_minutes=resolution_minutes)


def _command(
    *,
    engine: str | None,
    docker_image: str | None,
    archetype: str,
    year: int,
    seed: int,
    work_dir: Path,
) -> list[str]:
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    if docker_image:
        return [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{work_dir}:/out",
            docker_image,
            "--Calculate",
            "--LoadType",
            archetype,
            "--StartDate",
            start,
            "--EndDate",
            end,
            "--RandomSeed",
            str(seed),
            "--OutputDirectory",
            "/out",
        ]
    assert engine is not None
    return [
        engine,
        "--Calculate",
        "--LoadType",
        archetype,
        "--StartDate",
        start,
        "--EndDate",
        end,
        "--RandomSeed",
        str(seed),
        "--OutputDirectory",
        str(work_dir),
    ]
