# Feature Specification: HA Config Flow & Tiered Device Setup

**Feature Branch**: `007-ha-config-flow`

**Created**: 2026-05-28

**Status**: Retroactive — Built (Phase 4/5); all FRs test-backed

**Input**: `concept-hemm.md` ("Positioning", "Custom component in HA",
"Tiered config flow", onboarding walkthrough), code at
`ha-hemm/custom_components/hemm/config_flow.py` and `device_flow.py`.

> FRs tagged `✅ done` / `🔶 partial` / `⬜ todo` with their parent System
> Requirement. This feature realizes **SR-001** (HEMM is an HA integration,
> configured in HA — hub + sub-entries, no YAML) and the *tiered-setup* half of
> **SR-010** (setup scales beginner→pro). The online-ID half of SR-010 lives in
> [006](../006-online-identification/spec.md). Device entries feed the manifest
> builder ([001](../001-manifest-schema/spec.md)) consumed by the coordinator
> ([008](../008-coordinator-runtime/spec.md)).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Set up the hub, then add devices (Priority: P1)

A user installs HEMM and configures it entirely through the HA UI. The first
step creates a single **hub** entry (name, horizon, max iterations, price
adapter, solver backend). Afterwards the options flow adds **devices** — one
sub-entry per energy-relevant thing — choosing a type and a difficulty tier.

**Why this priority**: This is the front door. SR-001 says all config is in HA;
without it nothing else is reachable by a non-developer.

**Independent Test**: Start the config flow → submit hub data → entry created;
open options → add a battery (beginner) → device stored on the entry.

**Acceptance Scenarios**:

1. **Given** no HEMM entry, **When** the config flow is submitted with valid hub
   data, **Then** a config entry is created with `devices: []`.
2. **Given** a HEMM entry exists, **When** a second config flow is started,
   **Then** it aborts with `already_configured` (HEMM is a singleton hub).
3. **Given** a hub entry, **When** the options flow runs add-device →
   select-device → configure-device, **Then** the device is appended to the
   entry's `devices` list.

### Edge Cases

- A device configured without `safe_default_script` is rejected (see
  [001](../001-manifest-schema/spec.md) FR-003 — enforced in this flow).
- Selecting `pro` tier for a device type that doesn't support it downgrades to
  `advanced` rather than erroring.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `✅ done` `SR-001`: The hub MUST be created through a UI config flow
  capturing name, `horizon_hours` (1–72), `max_iterations` (5–500),
  `price_adapter`, and `solver_backend` — no YAML.
- **FR-002** `✅ done` `SR-001`: HEMM MUST be a singleton hub — a second config
  flow MUST abort with `already_configured` (unique_id = domain).
- **FR-003** `✅ done` `SR-001`: Devices MUST be added as sub-entries via the
  options flow (action → `select_device` → `configure_device`) and stored under
  the hub entry's `devices` key. *(HA 2024.12 lacks `ConfigSubentryFlow`; the
  device list is the stand-in.)*
- **FR-004** `✅ done` `unit` `SR-001`: Hub settings (horizon, iterations,
  adapters, backend) MUST be editable post-setup via the options flow `settings`
  step, and the change MUST round-trip into the entry options.
- **FR-005** `✅ done` `unit` `SR-010`: Each of the 7 device types MUST offer a
  tiered schema (beginner → advanced → pro) that progressively exposes more
  fields; beginner uses documented defaults.
- **FR-006** `✅ done` `unit` `SR-010`: `pro` tier MUST be offered only for the 5
  types in `DEVICE_PRO_SUPPORT`; selecting `pro` for an unsupported type MUST
  downgrade to `advanced`.
- **FR-007** `✅ done` `SR-001`: The config entry MUST set up and reload/unload
  cleanly (reentrant), staying `loaded` across a reload.

### Key Entities

- **Hub config entry**: the single HEMM instance (solver + global settings).
- **Device entry** (`devices[]`): type + tier + per-type parameters +
  `safe_default_script`.
- **Tier (beginner/advanced/pro)** + **DEVICE_PRO_SUPPORT**: the skill-floor
  ladder.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** `✅`: A hub entry is created from the UI and a second attempt aborts
  (covers FR-001/002).
- **SC-002** `✅`: A device of each of the 7 types reaches `configure_device` and
  a beginner device persists on the entry (covers FR-003/005).
- **SC-003** `✅`: Editing a hub setting via the options flow round-trips into
  the entry options (covers FR-004).
- **SC-004** `✅`: Selecting `pro` for an unsupported type downgrades to
  `advanced`, asserted by a test (covers FR-006).

## Assumptions

- One hub per HA instance is sufficient (multi-house is out of scope per the
  implementation plan's "Deliberately Omitted").
- The device-list-in-entry model is a temporary stand-in until HA exposes a
  stable sub-entry flow; FRs are written against the *behavior*, not that
  mechanism.
