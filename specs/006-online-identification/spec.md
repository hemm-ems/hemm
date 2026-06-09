# Feature Specification: Online Identification (Self-Models)

**Feature Branch**: `006-online-identification`

**Created**: 2026-05-28

**Status**: Retroactive — Framework stub (Phase 5); estimation algorithms open.
Extended 2026-06-09 with the multi-input room thermal model (sun / occupancy /
insulation) and its demand-prediction contract (FR-007…FR-009).

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
  for rooms — detailed in FR-007, COP-curve fit for HP, loss-coefficient for
  tanks, efficiency for batteries, bias calibration for PV).
- **FR-004** `⬜ todo` `SR-010`: A significant parameter change MUST surface as a
  **repair issue** for user confirmation; refined models MUST NOT be applied
  silently. *(Integration wiring; concept's transparency promise.)*
- **FR-005** `⬜ todo` `SR-010`: Identification status MUST be exposed as
  `sensor.hemm_<device>_model_confidence`.
- **FR-006** `⬜ todo` `SR-010`: Online-ID MUST ship **disabled by default** with a manual
  "try identifying my <device>" trigger, not background-on. *(Source: roast
  recommendation #7 — lower surface area until real inputs are seen.)*
- **FR-007** `⬜ todo` `SR-011` `SR-010`: The room identifier MUST be a **multi-input
  grey-box RC thermal model** `C·dT/dt = (T_out−T_in)/R + A_sol·I_solar +
  Q_occ·presence + Q_heat`, identifying `{R (insulation), C (thermal mass),
  A_sol (solar aperture), Q_occ (per-occupant gain)}`. The pure estimator MUST
  live in **core** (`hemm/src/hemm_core/identification/`), consuming a defined
  `ThermalObservation` series (indoor temp, outdoor temp, solar irradiance,
  occupancy/internal gains, heat actuation) and using a single `ExogenousForecast`
  contract for the presence / internal-gain inputs — re-cut against the 003
  component model (starting from the closed `occupants-demand-sim` branch's
  `sim/exogenous.py` dataclasses), not a parallel one. *(Resolves the plan's T004
  core-vs-integration decision and gives SR-011 its first FR trace.)*
- **FR-008** `⬜ todo` `SR-010`: Estimation MUST follow an **identifiability ladder** —
  1R1C heat-only `{R,C}` → +solar `A_sol` → +occupancy `Q_occ` — climbing a rung
  only when the data supports that term (information / condition-number gate),
  else returning the lower rung or `None`. Each term's confidence is reported
  separately. *(Concretises the "prefer `None` over a noisy fit" assumption and
  roast #6's ≥50 % rejection expectation; one temp sensor + one heat switch can
  rarely separate all four parameters.)*
- **FR-009** `⬜ todo` `SR-011` `SR-010`: A confirmed room model MUST expose
  `predict_demand(horizon) -> ExogenousForecast`, emitting the per-slot heat
  energy required to hold each zone's comfort band — feeding the solver
  ([002](../002-milp-central-solver/spec.md)) as an exogenous demand input and
  closing the identify→plan loop.

### Key Entities

- **DeviceIdentifier / IdentificationResult**: the estimation contract.
- **IDENTIFIER_REGISTRY**: device-type → identifier mapping.
- **Repair issue / confidence sensor**: the consent + transparency surface (HA).
- **RoomThermalModel `{R, C, A_sol, Q_occ}`**: the identified grey-box parameters
  (FR-007); `predict_demand` turns them into a forecast.
- **ThermalObservation**: the estimator input series (indoor/outdoor temp, solar
  irradiance, occupancy/internal gains, heat actuation).
- **ExogenousForecast** (`sim/exogenous.py`, shared with the occupant simulator):
  the demand contract `predict_demand` emits and the solver consumes.

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
- **SC-005** `⬜`: On a synthetic occupant trajectory generated by the demand
  simulator (`sim/occupants`, known internal gains + thermal params), the room
  identifier recovers `{R, C, A_sol, Q_occ}` within tolerance and its
  `predict_demand` reproduces the baked-in demand within a stated error band
  (covers FR-007/009; reuses the simulator as ground truth).
- **SC-006** `⬜`: Given history that only supports 1R1C (no occupancy/solar
  variance), the identifier returns the `{R, C}` rung with the higher terms
  withheld and flagged low-confidence — never an over-fit four-parameter result
  (covers FR-008).

## Assumptions

- Observability is borderline (often one temp sensor + one heat switch); the
  estimator MUST be conservative and prefer `None` over a noisy fit.
- Estimation logic moves to the core (`hemm`) for standalone testability (FR-007
  decides this for the room model; the other identifiers follow). HA keeps only
  the repair-issue + sensor surface.
- The room model **reuses** the occupant simulator's `ExogenousForecast`
  contract; the two are inverse directions (simulate-forward vs. learn-inverse)
  and must not fork the demand representation. Solar irradiance is a weather
  input, not an occupant output, so it enters via `ThermalObservation`, not
  `ExogenousSlot`.
