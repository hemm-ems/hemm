"""Canonical household demand profile for the simulation harness."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_DHW_KWH_PER_LITER = 4.186 / 3600.0 * 35.0


@dataclass(frozen=True)
class ApplianceEvent:
    """A typed appliance or behavior event attached to a profile slot."""

    appliance: str
    start: datetime
    energy_kwh: float = 0.0
    deadline_default: datetime | None = None
    duration_minutes: int = 0
    resource_use: list[str] = field(default_factory=list)
    device_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApplianceEvent:
        return cls(
            appliance=str(data["appliance"]),
            start=_parse_dt(data["start"]),
            energy_kwh=float(data.get("energy_kwh", 0.0)),
            deadline_default=_parse_dt(data["deadline_default"]) if data.get("deadline_default") else None,
            duration_minutes=int(data.get("duration_minutes", 0)),
            resource_use=[str(v) for v in data.get("resource_use", [])],
            device_id=str(data["device_id"]) if data.get("device_id") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "appliance": self.appliance,
            "start": self.start.isoformat(),
            "energy_kwh": self.energy_kwh,
            "deadline_default": self.deadline_default.isoformat() if self.deadline_default else None,
            "duration_minutes": self.duration_minutes,
            "resource_use": list(self.resource_use),
            "device_id": self.device_id,
        }


@dataclass(frozen=True)
class HouseholdSlot:
    """One canonical household profile slot."""

    timestamp: datetime
    presence: int
    electric_baseload_w: float = 0.0
    electric_appliances_w: float = 0.0
    appliance_events: list[ApplianceEvent] = field(default_factory=list)
    dhw_draw_l_per_min: float = 0.0
    internal_gains_w: float = 0.0

    def total_electric_kw(self) -> float:
        return (self.electric_baseload_w + self.electric_appliances_w) / 1000.0

    def dhw_energy_kwh(self, resolution_minutes: int) -> float:
        return max(0.0, self.dhw_draw_l_per_min) * resolution_minutes * _DHW_KWH_PER_LITER


@dataclass(frozen=True)
class HouseholdProfile:
    """Canonical, immutable household profile."""

    slots: list[HouseholdSlot]
    resolution_minutes: int
    source: str = "unknown"
    archetype: str = "unknown"
    seed: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.resolution_minutes <= 0:
            msg = "resolution_minutes must be positive"
            raise ValueError(msg)
        if not self.slots:
            msg = "household profile must contain at least one slot"
            raise ValueError(msg)

    @property
    def start(self) -> datetime:
        return self.slots[0].timestamp

    @property
    def end(self) -> datetime:
        return self.slots[-1].timestamp + timedelta(minutes=self.resolution_minutes)

    def slice(self, start: datetime, hours: int) -> HouseholdProfile:
        start = _ensure_utc(start)
        end = start + timedelta(hours=hours)
        slots = [slot for slot in self.slots if start <= slot.timestamp < end]
        if not slots:
            msg = f"profile has no slots in requested window {start.isoformat()}..{end.isoformat()}"
            raise ValueError(msg)
        return HouseholdProfile(
            slots=slots,
            resolution_minutes=self.resolution_minutes,
            source=self.source,
            archetype=self.archetype,
            seed=self.seed,
            metadata=dict(self.metadata),
        )

    def with_slots(self, slots: list[HouseholdSlot], *, source_suffix: str) -> HouseholdProfile:
        return HouseholdProfile(
            slots=slots,
            resolution_minutes=self.resolution_minutes,
            source=f"{self.source}+{source_suffix}",
            archetype=self.archetype,
            seed=self.seed,
            metadata=dict(self.metadata),
        )

    def align_values(self, start: datetime, n_slots: int, resolution_minutes: int) -> list[HouseholdSlot]:
        """Return profile slots aligned to a solver axis, forward-filling misses with zeros."""
        start = _ensure_utc(start)
        by_ts = {slot.timestamp: slot for slot in self.slots}
        aligned: list[HouseholdSlot] = []
        for i in range(n_slots):
            ts = start + timedelta(minutes=i * resolution_minutes)
            slot = by_ts.get(ts)
            if slot is None:
                slot = HouseholdSlot(timestamp=ts, presence=0)
            aligned.append(slot)
        return aligned


def read_profile(path: str | Path, *, resolution_minutes: int | None = None) -> HouseholdProfile:
    """Read a canonical household profile from parquet or CSV."""
    p = Path(path)
    if p.suffix == ".parquet":
        return _read_parquet(p, resolution_minutes=resolution_minutes)
    if p.suffix == ".csv":
        return _read_csv(p, resolution_minutes=resolution_minutes)
    msg = f"Unsupported household profile format: {p.suffix}"
    raise ValueError(msg)


def write_profile(profile: HouseholdProfile, path: str | Path) -> None:
    """Write a canonical household profile to parquet or CSV."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix == ".parquet":
        _write_parquet(profile, p)
        return
    if p.suffix == ".csv":
        _write_csv(profile, p)
        return
    msg = f"Unsupported household profile format: {p.suffix}"
    raise ValueError(msg)


def _read_csv(path: Path, *, resolution_minutes: int | None) -> HouseholdProfile:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        msg = f"empty household profile: {path}"
        raise ValueError(msg)
    slots = [_slot_from_row(row) for row in rows]
    return HouseholdProfile(
        slots=slots,
        resolution_minutes=resolution_minutes or _infer_resolution(slots),
        source="csv",
        metadata={"path": str(path)},
    )


def _write_csv(profile: HouseholdProfile, path: Path) -> None:
    fields = [
        "timestamp",
        "presence",
        "electric_baseload_w",
        "electric_appliances_w",
        "appliance_events",
        "dhw_draw_l_per_min",
        "internal_gains_w",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for slot in profile.slots:
            writer.writerow(_slot_to_row(slot))


def _read_parquet(path: Path, *, resolution_minutes: int | None) -> HouseholdProfile:
    try:
        import pyarrow.parquet as pq
    except ImportError as e:  # pragma: no cover - exercised when optional dep is missing
        msg = "Reading parquet profiles requires pyarrow"
        raise RuntimeError(msg) from e

    table = pq.read_table(path)  # type: ignore[no-untyped-call]
    rows = table.to_pylist()
    slots = [_slot_from_row(row) for row in rows]
    metadata = table.schema.metadata or {}
    md = {k.decode(): v.decode() for k, v in metadata.items()}
    return HouseholdProfile(
        slots=slots,
        resolution_minutes=resolution_minutes or int(md.get("resolution_minutes") or _infer_resolution(slots)),
        source=md.get("source", "parquet"),
        archetype=md.get("archetype", "unknown"),
        seed=int(md["seed"]) if md.get("seed") else None,
        metadata=md,
    )


def _write_parquet(profile: HouseholdProfile, path: Path) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as e:  # pragma: no cover - exercised when optional dep is missing
        msg = "Writing parquet profiles requires pyarrow"
        raise RuntimeError(msg) from e

    rows = [_slot_to_row(slot) for slot in profile.slots]
    metadata = {
        "source": profile.source,
        "archetype": profile.archetype,
        "resolution_minutes": str(profile.resolution_minutes),
    }
    if profile.seed is not None:
        metadata["seed"] = str(profile.seed)
    metadata.update(profile.metadata)
    table = pa.Table.from_pylist(rows).replace_schema_metadata(dict(metadata))
    pq.write_table(table, path)  # type: ignore[no-untyped-call]


def _slot_from_row(row: dict[str, Any]) -> HouseholdSlot:
    raw_events = row.get("appliance_events") or "[]"
    events_data = json.loads(raw_events) if isinstance(raw_events, str) else raw_events
    return HouseholdSlot(
        timestamp=_parse_dt(row["timestamp"]),
        presence=int(row.get("presence") or 0),
        electric_baseload_w=float(row.get("electric_baseload_w") or 0.0),
        electric_appliances_w=float(row.get("electric_appliances_w") or 0.0),
        appliance_events=[ApplianceEvent.from_dict(e) for e in events_data],
        dhw_draw_l_per_min=float(row.get("dhw_draw_l_per_min") or 0.0),
        internal_gains_w=float(row.get("internal_gains_w") or 0.0),
    )


def _slot_to_row(slot: HouseholdSlot) -> dict[str, Any]:
    return {
        "timestamp": slot.timestamp.isoformat(),
        "presence": slot.presence,
        "electric_baseload_w": round(slot.electric_baseload_w, 6),
        "electric_appliances_w": round(slot.electric_appliances_w, 6),
        "appliance_events": json.dumps([event.to_dict() for event in slot.appliance_events], sort_keys=True),
        "dhw_draw_l_per_min": round(slot.dhw_draw_l_per_min, 6),
        "internal_gains_w": round(slot.internal_gains_w, 6),
    }


def _infer_resolution(slots: list[HouseholdSlot]) -> int:
    if len(slots) < 2:
        return 15
    delta = slots[1].timestamp - slots[0].timestamp
    return max(1, int(delta.total_seconds() // 60))


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _ensure_utc(value)
    text = str(value).replace("Z", "+00:00")
    return _ensure_utc(datetime.fromisoformat(text))


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
