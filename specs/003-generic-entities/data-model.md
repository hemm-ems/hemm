# Phase 1 Data Model: Generic Entities — the Primitive Component Model

All new types live in `src/hemm_core/manifest/components.py` (pure-Python, Pydantic v2).
The 8 named manifest types in `types.py` are **unchanged** except that each gains a
`to_components()` method and the `DeviceRole` enum is replaced by `Primitive`.

## Primitive (enum) — replaces `DeviceRole`

```text
Primitive = source | sink | storage | converter | node
```

| Member | Meaning | State var | Solver contribution |
|--------|---------|-----------|---------------------|
| `source`   | non-dispatchable injection | — | `0 ≤ p ≤ forecast` into a bus |
| `sink`     | a load (controllable or fixed) | — | bounded draw from a bus |
| `storage`  | conserved-quantity store | `level` | level dynamics + η + bounds on a bus |
| `converter`| couples input bus → output bus | — | `p_out = factor_at(ctx) · p_in` |
| `node`     | balance point for a conserved quantity | `quantity` (optional) | `Σin = Σout` (+ optional state dynamics, cap, comfort band) |

Cardinality change vs. `DeviceRole`: a named type maps to **one or more** primitives
(WaterHeater → 3). The type→primitive(s) mapping is `to_components()`; there is no standalone
`_TYPE_ROLES` dict anymore.

## ComponentSpec (base) and variants

`ComponentSpec` carries only **solver-relevant** parameters — no HA, no UX. Every component
keeps its owning device's `device_id` (so multi-component devices share a namespace and still
emit one `PlanMessage`).

| Field | Type | Notes |
|-------|------|-------|
| `device_id` | `str` | owning named-manifest device |
| `primitive` | `Primitive` | discriminator |
| `bus` | `str` | bus/node this component draws from / injects into (`"elec"` default, implicit/global) |

**SourceSpec** (`primitive=source`)
| `forecast` | `list[float] | None` | per-slot upper bound; PV mapping pins `(0,0)` in Backend A today (research D2) |

**SinkSpec** (`primitive=sink`)
| `min_power_kw` / `max_power_kw` | `float` | bounds (fixed load → min==max, e.g. PassiveLoad avg) |
| `controllable` | `bool` | `False` ⇒ fixed profile (PassiveLoad) |

**StorageSpec** (`primitive=storage`)
| `capacity` | `float` | kWh (battery/EV) or thermal-mass-derived (DHW) |
| `charge_efficiency` / `discharge_efficiency` | `float` | η |
| `min_level` / `max_level` | `float` | SoC/level bounds (abs units, derived from pct where applicable) |
| `charge_only` | `bool` | `True` for EV |
| `leakage` | `float | None` | standby loss (DHW storage leakage; `None`/0 for battery/EV) |
| `node` | `str | None` | for storage *on a node* (DHW); `None` ⇒ electrical |

**ConverterSpec** (`primitive=converter`)
| `input_bus` / `output_bus` | `str` | e.g. `elec` → `thermal:<room_id>` |
| `max_input_kw` | `float` | input power bound |
| `factor_map` | `list[tuple[float, float]]` | piecewise-linear `(ctx, factor)` (COP map; η≈1 ⇒ `[(_, 1.0)]`) |
| `factor_ctx` | `str` | which context drives the factor (`"outdoor_temp"`); η-converters ignore it |
| **method** `factor_at(ctx) -> float` | | generic lift of `_piecewise_cop`; clamps at map ends |

**NodeSpec** (`primitive=node`)
| `quantity` | `str` | `"thermal"` (rooms, DHW) |
| `thermal_mass` | `float` | C (kWh/K) |
| `ua` | `float` | UA (kW/K), derived from U-value × envelope area |
| `ambient_ctx` | `str` | `"outdoor_temp"` for rooms; DHW uses its surrounding temp |
| `comfort_band` | `tuple[float,float] | None` | min/max if a band applies |
| `initial` | `float | None` | initial state (room: indoor default; DHW: tank default) |

## Compile mapping — `to_components()` per named type

| Named type | Components produced |
|------------|---------------------|
| `PVForecast` | `SourceSpec(bus=elec, forecast=…)` — **(0,0) Backend-A bounds preserved, D2** |
| `PassiveLoad` | `SinkSpec(bus=elec, controllable=False, min==max=typical_daily_kwh/24)` |
| `Battery` | `StorageSpec(bus=elec, cap, η, min/max from pct, charge_only=False)` |
| `EVCharger` | `StorageSpec(bus=elec, charge_only=True, deadline-aware via constraints)` |
| `Room` | `NodeSpec(quantity=thermal, thermal_mass, ua, ambient=outdoor_temp, comfort_band, initial)` |
| `HeatPump` | `ConverterSpec(elec → thermal:<room_id>, factor_map=cop_map, factor_ctx=outdoor_temp)` **iff `room_id`**, else `SinkSpec(elec)` (degenerate, mirrors ThermostatLoad — see research D4 symmetry; the scenario HPs have no `room_id` and stay sinks) |
| `ThermostatLoad` | `ConverterSpec(elec → thermal:<room_id>, factor_map=[(_,1.0)])` **iff `room_id`**, else `SinkSpec(elec)` (D4) |
| `WaterHeater` | `NodeSpec(quantity=thermal, DHW)` + `ConverterSpec(elec → thermal:<dhw>, η=1)` + `StorageSpec(node=<dhw>, leakage=standby_loss)` (D3) |

> **Parity note (research D8)**: `EVCharger → storage` and `WaterHeater → node+storage` give
> the EV a SoC `level` and the tank a thermal state these devices lacked pre-refactor, so a
> `min_soc_until` / `reach_min_temp_once` they already declared now *binds* instead of being
> silently dropped. Those devices are the FR-006 **intended divergence set** — validated by
> US3 correctness tests, not golden parity. All other mappings are behavior-preserving.

## Relationships

- A **converter**'s `output_bus` references a **node** (`thermal:<room_id>` or `thermal:<dhw>`).
  Today's `room_id` field is the link; validation rejects a converter whose `output_bus` node
  is absent (Edge Cases).
- A device's `PlanMessage` aggregates the power decision(s) of its component(s) under its
  single `device_id` (multi-component devices still emit one plan).
- The electrical bus is implicit/global; not declared per-manifest (research D1).

## Validation rules (additive — FR-010, Constitution II)

- Component metadata is **derived**, never a required manifest field; old manifests validate
  unchanged.
- A constraint must target a state var its device's primitives provide (`min_soc_until` ⇒
  device has `storage`; `hold_temp_band`/`reach_min_temp_once` ⇒ device contributes to a
  thermal `node`); otherwise rejected with a clear message (research D5).
- A `converter.output_bus` must reference an existing node in the scenario.

## State transitions

Only **storage** (`level` across slots) and **node** (thermal `quantity` across slots) carry
state dynamics; both already exist in Backend A (SoC recursion line 191–193; RC recursion
line 254–256) and are re-expressed by the storage and node builders with identical equations.
