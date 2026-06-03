# Contract: Component Model & `to_components()`

The internal contract the manifest layer exposes to the solvers. This is a **library
contract** (function calls + Pydantic models), not a network API.

## `Primitive` enum

```python
class Primitive(StrEnum):
    SOURCE = "source"
    SINK = "sink"
    STORAGE = "storage"
    CONVERTER = "converter"
    NODE = "node"
```

Replaces `DeviceRole`. Exported from `manifest/__init__.py` (`__all__`) and surfaced in the
JSON schema (FR-010, FR-011). The exported enum **name changes** from `DeviceRole` to
`Primitive` — the single accepted breaking change.

## `ComponentSpec` family

Pydantic models in `manifest/components.py`, discriminated on `primitive` (see data-model.md
for fields). Contract guarantees:

- **Pure data + pure functions.** No HA imports; the only behavior is `ConverterSpec.factor_at(ctx)`
  (a deterministic piecewise-linear lookup lifting `_piecewise_cop`, clamped at map ends).
- **`device_id` preserved** on every component so the solver can aggregate a multi-component
  device into one `PlanMessage`.
- **Bus/node references are strings** resolvable within a single scenario's manifest set.

## `to_components()` contract

```python
# on each named manifest type (RoomManifest, HeatPumpManifest, …)
def to_components(self) -> list[ComponentSpec]: ...
```

- **Total**: defined for all 8 named types; returns a non-empty list.
- **Declarative**: the mapping is a fixed table (data-model.md), **no per-manifest custom
  Python branching beyond the documented conditional** (`ThermostatLoad` with/without
  `room_id`, research D4). Adding a new device type means a new manifest whose
  `to_components()` returns existing primitives — **no solver edit** (FR-003, the thesis).
- **Behavior-pinning**: mappings reproduce current Backend-A behavior exactly, including
  - PV `source` → `(0,0)` Backend-A power bounds (research D2),
  - PassiveLoad `sink` → `min==max==typical_daily_kwh/24`,
  - ThermostatLoad/WaterHeater converters → η = 1 (electrical ≈ heat),
  - Battery/EV `storage` → initial SoC 50 %, pct→abs level bounds.
- **Round-trip guarantee** (FR-004): every `testdata/scenarios/*.yaml` manifest compiles to a
  well-formed component set (validated before any solver cutover).

## Acceptance for this contract

| FR | Test (unit) | Assertion |
|----|-------------|-----------|
| FR-001 | `test_components.py::test_primitive_enum` | 5 members; `DeviceRole` gone |
| FR-002 | `test_components.py::test_to_components_<type>` (×8) | each type → expected primitive set |
| FR-003 | `test_components.py::test_mapping_is_declarative` | no isinstance-on-named-type in the compile path |
| FR-004 | `test_components.py::test_testdata_round_trips` | all 7 scenarios' manifests compile cleanly |
| FR-011 | `test_components.py::test_device_role_folded` | `Primitive` exported; type→primitive(s) mapping replaces `_TYPE_ROLES` |
