# Phase 0 Research: Generic Entities — the Primitive Component Model

All Technical Context items are known (the stack is fixed). The open questions here are
**design decisions** that make a behavior-preserving refactor actually preserve behavior.

## D1 — Electrical "bus balance" must reproduce today's independent-sum objective

**Decision**: The electrical bus is modeled with a **free, tariff-priced grid-exchange
term**, *not* a hard `Σpower = 0` balance. Each device's `power[d,t]` contributes to the
objective as `price[t] · power[d,t] · dt` exactly as today; the "bus balance" introduces a
grid slack `g[t]` with `g[t] = Σ_d power[d,t]` and prices `g[t]` — algebraically identical to
the current per-device sum. No constraint reduces the feasible set.

**Rationale**: The current Backend A (`milp_central.py`) has **no** electrical balance
constraint. Devices are coupled only through shared SoC and thermal RC state; `power` is
summed straight into the objective (`obj_rule`, line 289). Introducing a hard `Σin = Σout`
electrical balance would forbid grid import/export and **change the optimum**, breaking
golden parity (FR-006) and the oracle (Constitution IV). The grid-exchange formulation keeps
the electrical bus a *bookkeeping* node, matching today.

**Alternatives considered**:
- *Hard electrical balance with no grid node* — rejected: changes behavior, infeasible for
  any net-import scenario.
- *No electrical node at all (keep pure objective sum)* — workable but loses the uniformity
  the concept wants (thermal nodes are real balance nodes); the grid-exchange node gives one
  consistent "node" abstraction while staying parity-safe.

**Implication**: Thermal nodes (rooms, DHW) DO carry a real balance (RC dynamics, no free
slack) — that is the existing behavior and is preserved. Only the electrical bus is "open".

## D2 — `source` primitive must preserve PV's current `(0,0)` Backend-A bounds

**Decision**: `PVForecast → source(elec)` compiles to a component whose Backend-A power
bounds are `(0.0, 0.0)` — i.e. PV injects nothing into Backend A's objective today — until a
future spec gives PV a real injection. The generic `source` primitive supports
`0 ≤ p ≤ forecast`, but the PV mapping pins the current behavior.

**Rationale**: `_get_power_bounds` (line 392) returns `(0.0, 0.0)` for PV and Room today.
Golden parity requires the component build to reproduce this exactly. The `source` primitive's
general capability (bounded by a forecast) is correct for the model; the *PV mapping* must not
silently start crediting PV generation in Backend A or the objective shifts.

**Alternatives considered**: Wire PV forecast into the bus now — rejected: behavior change,
out of scope, would break parity. Captured as a candidate for a later spec.

## D3 — WaterHeater = node + converter + storage (resolved decision, grounded)

**Decision**: `WaterHeater → ` (a) a DHW **thermal node** with a temperature state var and
optional comfort band; (b) a **converter** elec→DHW with η≈1; (c) **storage** on the DHW node
(volume-derived thermal mass + standby loss as the storage leakage term).

**Rationale**: Gives DHW a real temperature/comfort state uniform with Room, and lets
`hold_temp_band` / `reach_min_temp_once` target the DHW node for free (FR-008, US3). Today the
water heater is a plain sink whose `reach_min_temp_once` is handled via a tank thermal-mass
special-case (002:FR-009). The node+storage decomposition generalizes that.

**Parity note (corrected — see D8)**: An empirical check of the captured golden (T001)
showed the pre-refactor WaterHeater has **no** temperature trajectory at all: as a plain
sink with no `room_id`, `dhw` has no `model.temp` var, so `reach_min_temp_once` finds no
target and is *silently dropped* — `water_heater_legionella` and `full_house`'s `dhw` plan
**zero power** today. The decomposition therefore does **not** "reproduce an existing
trajectory" (there is none); it makes the tank finally heat to 60 °C. That is an **intended
divergence** (enumerated in FR-006), validated by a US3 correctness test (DHW reaches 60 °C
by the deadline), **not** by golden parity. The storage leakage term = the current
`standby_loss_w`; converter η = 1 keeps the "electrical ≈ heat" assumption.

**Alternative considered**: a single fused "thermal storage with electric input" primitive —
rejected by the resolved decision (less uniform with Room, no real DHW comfort state).

## D4 — `ThermostatLoad` mapping is conditional on `room_id`

**Decision**: `ThermostatLoad → converter(elec→thermal[room_id], η≈1)` when `room_id` is set;
otherwise `→ sink(elec)`. This mirrors the current code: a thermostat with `room_id` injects
into its room's RC model (`room_heaters` map, line 205–209, the `else` branch at line 250
adds power 1:1 as heat); without `room_id` it is just a bounded load.

**Rationale**: Preserves the existing `room → heaters` wiring exactly while expressing it as a
converter into a thermal node. Edge case (no `room_id`) is the degenerate-but-valid sink.

**Symmetry (HeatPump)**: The same conditional applies to `HeatPump → converter(elec→thermal
[room_id]) | sink(elec) if no room_id`. The scenario heat pumps (`heat_pump.json`, used by
`heat_pump_shift` and `full_house`) carry **no `room_id`**, so today they are plain sinks via
`_get_power_bounds`. Without this degenerate rule a no-`room_id` HeatPump would compile to a
converter pointing at a non-existent node and either error or silently drop power — breaking
parity. With it, those heat pumps stay parity-preserving plain loads.

## D5 — Constraint targets resolve to primitive state vars/flows via a small dispatch on Primitive

**Decision**: `_apply_constraint_windows` stops switching on the device's Python type and
instead resolves the constraint's target from the **primitive(s)** the device compiled to:
`min_soc_until` → the device's `storage` level var; `reach_min_temp_once` / `hold_temp_band` →
the `node` thermal state var the device contributes to; `min_energy_until` → a flow integral
over the device's sink/storage power var; `forbidden_window`, `min/max_runtime_per_day` → the
device `on`/power var. Constraint **semantics and versions are unchanged** (Constitution II);
only the *target resolution* generalizes.

**Rationale**: Today these are isinstance/`hasattr(model, "temp")` branches (lines 422–477).
Resolving the target from the component set removes the type coupling and makes
`hold_temp_band`-on-DHW and `min_soc_until`-on-EV fall out for free (US3) — strictly more
expressive, same semantics.

**Validation rule (new, additive)**: a constraint targeting a state var the device's
primitives do not provide (e.g. `min_soc_until` on a non-storage) is rejected at validation
with a clear message (spec Edge Cases), not an opaque solver failure.

## D6 — COP generalizes to `ConverterSpec.factor_at(ctx)`

**Decision**: Lift `_piecewise_cop` (module-level, generic already) so that
`ConverterSpec.factor_at(ctx)` evaluates a piecewise-linear factor against a context
(`outdoor_temp` for heat pumps). HeatPump's `cop_map` becomes the converter's factor map; the
default map (`DEFAULT_COP_MAP`) is the fallback. Clamping at map ends is unchanged.

**Rationale**: `_piecewise_cop` is already type-agnostic; only `cop_at_temp` is HP-specific.
Generalizing the wrapper removes the heat-pump special case in the room thermal block
(line 246–251) — the converter carries its own factor.

**Alternatives considered**: keep COP as a heat-pump attribute read by the room builder —
rejected: re-introduces the special case the feature exists to remove.

## D7 — `DeviceRole → Primitive` is the one accepted breaking change

**Decision**: Rename/replace the `DeviceRole` enum (members
`generator/adjustable_sink/passive_sink/storage/thermal_zone`) with `Primitive`
(`source/sink/storage/converter/node`) and replace the `_TYPE_ROLES` map with a
type→primitive(s) mapping. The exported JSON-schema enum **name changes** — accepted, since
nothing reads `DeviceRole` for behavior today (dead code).

**Rationale**: The resolved decision. Folding the dead enum into the live primitive set stops
it being dead code (concept goal) and keeps one vocabulary. Note the cardinality shift: a type
maps to *one role* today but may map to *several primitives* (WaterHeater → 3), so the mapping
returns a list and lives alongside `to_components()`.

**Migration note**: Update `manifest/__init__.py` `__all__` and `schema_export.py`; the
branding/schema audits and any snapshot of the exported schema must be regenerated.

## D8 — Golden parity is per-device, with a closed enumerated divergence allowlist

**Decision**: FR-006 is evaluated **per device**, not per whole scenario. A device whose
component mapping reproduces its pre-refactor solver treatment must match its golden per-slot
power within tolerance. A small, **closed, enumerated** set of devices is *expected* to
diverge because the refactor gives them a state variable they lacked, so a constraint they
already declared finally binds — these are excluded from golden parity and validated by US3
correctness tests instead. Empirically confirmed against the T001 golden, the set is:

| Device · scenario | Pre-refactor (golden) | Post-refactor | Cause | Validated by |
|---|---|---|---|---|
| `dhw` · `water_heater_legionella`, `full_house` | 0 power (sink, no temp var → `reach_min_temp_once` dropped) | heats to 60 °C | D3 DHW node+storage | DHW reaches 60 °C by deadline |
| `ev_charger_garage` · `onboarding` | 0 power (sink, no SoC var → `min_soc_until` dropped) | charges to 80 % SoC | D5/FR-002 EV→storage | EV reaches target SoC by deadline |
| `ev_charger_garage` `min_energy_until` · `control_class_mix`, `full_house` | 30 / 25 kWh (sink + flow) | **at-risk** — storage η may shift kWh | EV sink→storage | Phase 3 empirical: parity if unchanged, else allowlist + justify |

**Rationale**: The original "byte-parity on all 7 scenarios" (FR-006 v1) is **logically
incompatible** with FR-002 (WaterHeater gains a thermal node) and US3 (`min_soc_until` on an
EV must work) — the very features the spec exists to deliver. Capturing the golden (T001)
made this concrete: the diverging devices plan *nothing* today because the oracle has no
state var to hang their constraint on. Making the oracle honor a constraint it *silently
dropped* does not "break the oracle" (Constitution IV) — the oracle never produced those
plans; it produced no plan. So the honest gate is: preserve every plan the oracle actually
made (per-device parity), and prove the new behavior is correct (US3 tests), with the
divergence set closed and justified so it cannot become a licence for unflagged regressions.

**Alternatives considered**:
- *Re-scope parity to purely-electrical scenarios only* — rejected: coarser oracle coverage,
  loses per-device granularity in mixed scenarios like `full_house` (its battery/EV must
  still be pinned even though its `dhw` diverges).
- *Re-capture the golden after the refactor* — rejected: makes parity vacuous (always
  passes), abandoning the oracle.
- *Keep FR-006 v1 and suppress the DHW/EV state to force zero* — rejected: defeats FR-002/US3.

**Implication for tests**: `test_solver_parity.py` (T015) asserts per-device parity for all
devices minus the allowlist, asserts the allowlisted devices honor their constraint, and
**fails on any unlisted divergence**. The captured golden stays frozen as the honest
pre-state.

## Open questions deferred (not blocking)

- Exposing buses/nodes as user-authored manifest entities — deferred to a later spec; here
  they stay derived from `room_id`/the WaterHeater decomposition (spec Out of Scope).
- Crediting PV injection into Backend A (D2) — deferred; would be its own behavior-changing FR.
