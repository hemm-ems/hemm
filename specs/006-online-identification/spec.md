# Feature Specification: Online Identification (Self-Models)

**Feature Branch**: `006-online-identification`

**Created**: 2026-05-28

**Status**: Retroactive — Framework stub (Phase 5); estimation algorithms open

**Input**: `concept-hemm.md` ("Online identification as a first-class feature"),
code at `ha-hemm/custom_components/hemm/identification.py`,
`local-concept-roast.md` weakness #6 (over-promised; expect ≥ 50 % rejection)
and recommendation #7 (ship disabled by default, manual trigger).

> FRs tagged `✅ done` / `🔶 partial` / `⬜ todo`. This capability spans repos but
> lives integration-side today; the refined parameters feed the manifests
> ([001](../001-manifest-schema/spec.md)) consumed by the solver
> ([002](../002-milp-central-solver/spec.md)).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Refine a device model from history, with consent (Priority: P1)

Once enough HA history exists, an identifier estimates better model parameters
(room U-value, HP COP, tank loss, battery efficiency, PV bias). Refined models
are **not** applied silently — the user confirms via a repair-issue prompt
("U=0.32 (old 0.45), apply?"). Identification status is a sensor.

**Why this priority**: Good predictions need good models; this is HEMM's answer
to the model-quality problem. But it is also the most over-promised piece, so the
*consent + transparency* path matters more than the estimator's sophistication.

**Independent Test**: For each device type, `get_identifier(type)` returns an
identifier whose `identify(observations)` runs and returns either an
`IdentificationResult` (with confidence) or `None` (keep current).

**Acceptance Scenarios**:

1. **Given** a registered device type, **When** `get_identifier` is called,
   **Then** the matching identifier instance is returned.
2. **Given** an unknown device type, **When** `get_identifier` is called,
   **Then** `None` is returned and a warning is logged.
3. **Given** an identifier produces a significant change, **When** it runs,
   **Then** a repair issue is raised for confirmation (NOT auto-applied).

### Edge Cases

- Insufficient/observability-poor history → identifier returns `None` (no
  overfitting to recorder noise).
- A confirmed update must be reversible (user can revert to prior parameters).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `✅ done` `unit` `SR-010`: System MUST define a `DeviceIdentifier` ABC
  (`identify(observations) -> IdentificationResult | None`, `device_type`) and an
  `IdentificationResult` (device_id, parameter_updates, confidence, message).
- **FR-002** `✅ done` `unit` `SR-010`: System MUST register an identifier per device type (7
  types) and resolve them via `get_identifier`, warning on unknown types.
- **FR-003** `🔶 partial` `SR-010`: Every identifier currently returns `None` (stub). The
  estimation algorithms MUST be implemented per device type (RC thermal-model ID
  for rooms, COP-curve fit for HP, loss-coefficient for tanks, efficiency for
  batteries, bias calibration for PV).
- **FR-004** `⬜ todo` `SR-010`: A significant parameter change MUST surface as a
  **repair issue** for user confirmation; refined models MUST NOT be applied
  silently. *(Integration wiring; concept's transparency promise.)*
- **FR-005** `⬜ todo` `SR-010`: Identification status MUST be exposed as
  `sensor.hemm_<device>_model_confidence`.
- **FR-006** `⬜ todo` `SR-010`: Online-ID MUST ship **disabled by default** with a manual
  "try identifying my <device>" trigger, not background-on. *(Source: roast
  recommendation #7 — lower surface area until real inputs are seen.)*

### Key Entities

- **DeviceIdentifier / IdentificationResult**: the estimation contract.
- **IDENTIFIER_REGISTRY**: device-type → identifier mapping.
- **Repair issue / confidence sensor**: the consent + transparency surface (HA).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** `✅`: The framework resolves an identifier for all 7 device types;
  unknown types return `None` with a warning.
- **SC-002** `⬜`: On a synthetic room trajectory with known U-value, the room
  identifier recovers it within a stated tolerance and reports calibrated
  confidence (covers FR-003).
- **SC-003** `⬜`: A significant change raises a repair issue and is applied only
  after confirmation; status sensor reflects confidence (covers FR-004/005).
- **SC-004** `⬜`: With the feature default-off, no identification runs until the
  manual trigger fires (covers FR-006).

## Assumptions

- Observability is borderline (often one temp sensor + one heat switch); the
  estimator MUST be conservative and prefer `None` over a noisy fit.
- Estimation logic could move to the core (`hemm`) for standalone testability;
  today it lives in the integration. This is an open design choice in plan.md.
