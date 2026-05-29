# Implementation Plan: HA Config Flow & Tiered Device Setup

**Branch**: `007-ha-config-flow` | **Date**: 2026-05-28 |
**Spec**: [spec.md](./spec.md)

**Note**: Retroactive. The hub config flow, options flow, and 7 tiered device
schemas are built (Phase 4/5) and test-backed. The former gaps (FR-004 settings
round-trip, FR-006 tier downgrade) are now covered by unit tests.

## Summary

All HEMM configuration happens in HA. A singleton hub config entry holds global
settings and a `devices` list; the options flow adds devices through a
type-then-tier selection that drives a per-type schema. Beginner tiers map a few
simple inputs to full manifest values; advanced/pro progressively expose more.

## Technical Context

**Language/Version**: Python 3.12 / 3.13
**Primary Dependencies**: Home Assistant config-entries / options-flow,
voluptuous, HA selectors
**Testing**: unit (`pytest_homeassistant_custom_component`) + container (hactl)
**Project Type**: Integration glue (`ha-hemm`) — no core changes
**Constraints**: no YAML config; `safe_default_script` mandatory per device
(enforced here, owned by 001:FR-003); `hemm`-prefixed identifiers (SR-012)

## Constitution Check

- **V. Clean Core/Integration Split** — OK. Pure glue; device entries are handed
  to the core manifest builder, no HA types leak into `hemm`.
- **III. Done = Green Tests** — FR-001/002/003/007 are container-backed;
  FR-004/005/006 are unit-backed (options-flow round-trip and tier schema/
  downgrade are form logic an HA-level test would only observe indirectly).

## Project Structure

```text
ha-hemm/custom_components/hemm/config_flow.py   # hub flow + options (settings)
ha-hemm/custom_components/hemm/device_flow.py   # 7 tiered device schemas + add steps
ha-hemm/custom_components/hemm/const.py         # DeviceType, ConfigTier, DEVICE_PRO_SUPPORT
ha-hemm/tests/test_config_flow.py               # hub flow (unit)
ha-hemm/tests/test_device_flow.py               # device/options flow (unit)
ha-hemm/tests/integration/test_hactl_config.py  # full flow (container)
```

**Structure Decision**: Stable. The only open structural question is migrating
the `devices`-list stand-in to a real HA sub-entry flow when the API stabilizes.

## Open Work (drives tasks.md)

- None functional. Optional hardening: a container-level settings round-trip and
  tier-downgrade test would raise FR-004/006 from unit to integration tier.

## Complexity Tracking

No violations. Watch the `devices`-in-entry-data pattern: if HA ships
`ConfigSubentryFlow`, migrate rather than accrete more list-management logic.
