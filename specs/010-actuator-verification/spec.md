# Feature Specification: Actuator / Verification / Watchdog Engine

**Feature Branch**: `010-actuator-verification`

**Created**: 2026-05-29

**Status**: Phase 7 landed 2026-05-29 (ha-hemm `2f6c2b8`..`c3f78f3`); 5 FRs done, 2 partial pending test-ordering polish

**Input**: `concept-hemm.md` ("Plug point 2: actuation", read-only onboarding,
"safe default"); `local-concept-roast.md` weaknesses #4 (self-confirming verify)
and the watchdog/safe-default discussion; `AGENT.md` → "Write-path always
dry-run capable"; constitution Principle VI (Safe Write-Path). Core actuation
types already exist (`hemm_core.manifest.types`: `Action`,
`VerificationContract`, `RetryPolicy`, mandatory `safe_default`); this feature
wires them live in `ha-hemm`.

> FRs tagged `✅ done` / `🔶 partial` / `⬜ todo` with their parent System
> Requirement. This feature realizes **SR-009** (HEMM observes and plans, but
> actuates only through verified user actions; observe-first read-only mode;
> mandatory `safe_default`; `dry_run`). The manifest-level pieces are owned by
> [001](../001-manifest-schema/spec.md) (`safe_default` mandatory = 001:FR-003,
> verify contract = 001:FR-008, verify-independence warn = 001:FR-013); service
> `dry_run` is [008](../008-coordinator-runtime/spec.md):FR-008. This spec owns
> the **live actuation engine** that consumes them.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Verified actuation through a user script (Priority: P1)

For a `planned`/`reactive` device whose manifest declares an action with a
`verify` contract, when HEMM decides to actuate, it calls the user-defined HA
script, then watches the verify entity. If the entity reaches the expected value
within the contract timeout, the attempt succeeds and is logged. If not, HEMM
retries per the `RetryPolicy`; on terminal failure it invokes the device's
`safe_default` and raises a repair issue. HEMM never writes the hardware itself —
only the user's script does.

**Why this priority**: This is plug point 2 and the heart of SR-009 — the 1.0
safety story. Without verified actuation, HEMM either does nothing or acts
blindly.

**Independent Test**: In a container, a planned device with a mock script + a
verify entity that flips to the expected value → attempt succeeds and is
recorded; a verify entity that never changes → retry then safe_default + repair
issue.

### User Story 2 - Observe-first, read-only by default (Priority: P1)

A freshly onboarded HEMM plans and surfaces plan/confidence/mode sensors but
issues **no** script calls until the user explicitly enables actuation. The
onboarding house runs end-to-end in read-only mode with zero actuator calls.

**Why this priority**: SR-009 mandates an observe-first read-only mode; it is the
trust contract for a new install and the default posture.

**Acceptance Scenarios**:

1. **Given** actuation disabled (default), **When** a solve produces an action,
   **Then** no script is called and the audit log records `skipped: read_only`.
2. **Given** actuation enabled and a passing verify entity, **When** HEMM
   actuates, **Then** the script is called once and the attempt is `verified`.
3. **Given** a device override switch is on, **When** HEMM would actuate that
   device, **Then** the device is treated as observe-only (no call) while other
   devices still actuate.
4. **Given** any actuation, **When** invoked with `dry_run: true`, **Then** the
   full path including verification evaluation runs with no real script call.

### Edge Cases

- Action has no `verify` contract → call the script, mark `unverified` (no
  false-confirm); do not invoke safe_default on a missing contract alone.
- `verify.entity` is the same entity the script writes through (self-confirming) →
  refuse/flag (complements 001:FR-013 at manifest time).
- Coordinator stalls (no successful update) → watchdog fires safe_default for
  every device regardless of the read-only flag (safety overrides observe-first).
- Override switch on AND watchdog fires → safe_default still runs (safety wins).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `✅ done` `SR-009`: The actuator engine MUST, for a decided action,
  call the user's HA script, then evaluate the `VerificationContract` (entity
  reaches `expected` within `within_seconds`); on verify failure it MUST retry
  per `RetryPolicy` (`max_attempts`, `backoff_seconds`) and, on terminal failure,
  invoke the device's `safe_default` and raise a repair issue. HEMM MUST NOT
  write the target entity directly — only the user script does.
- **FR-002** `✅ done` `SR-009`: HEMM MUST default to an observe-first, read-only
  mode in which it produces plans and sensors but issues no script calls.
  Actuation MUST be opt-in (an explicit, persisted enable); the onboarding
  scenario MUST pass end-to-end with zero actuator calls in the default mode.
- **FR-003** `✅ done` `SR-009`: The actuator engine MUST honor `dry_run: true` —
  run the full path including verification evaluation and audit recording, with
  no real script call and no state change.
- **FR-004** `🔶 partial` `SR-009`: Immediately before every actuation call, HEMM
  MUST re-validate the hard constraints / current state for that device; if the
  pre-call check fails, HEMM MUST skip the script call and fall back to the
  device's `safe_default`. *(Engine + unit-tested; container SC-005 passes in
  isolation but is flaky in the full Phase 7 suite due to shared HA session
  state — needs deterministic constraint-state reset between tests.)*
- **FR-005** `✅ done` `SR-009`: A watchdog MUST invoke each device's
  `safe_default` action when the coordinator has not completed a successful
  update within a configurable timeout (default 30 min). Watchdog-driven
  safe_default MUST run even when actuation is in read-only mode or a device
  override is active (safety overrides observe-first).
- **FR-006** `✅ done` `SR-009`: HEMM MUST expose a per-device override
  (`switch.hemm_<device>_override`) that, while on, suspends HEMM actuation for
  that device (treated as observe-only) without affecting other devices.
- **FR-007** `🔶 partial` `SR-009`: HEMM MUST maintain an inspectable, anonymized
  actuation audit log (a sensor and/or the diagnostics dump) recording each
  attempt and its outcome (`verified` / `unverified` / `retried` /
  `safe_default` / `skipped:read_only` / `skipped:override` / `dry_run`), with no
  raw entity values that would leak PII. *(Engine + unit-tested; container SC-008
  passes in isolation but the anonymization-audit assertion is flaky when run
  after several other SCs — same shared-session-state cause as FR-004.)*

### Key Entities

- **ActuatorEngine** (new, `ha-hemm`): consumes a decided plan + device
  manifests, performs call→verify→retry→safe_default, records audit entries,
  raises repair issues. Honors read-only mode, per-device override, and
  `dry_run`.
- **Watchdog**: tracks last successful coordinator update; on timeout drives
  `safe_default` for all devices.
- **Override switch**: `switch.hemm_<device>_override` platform entity.
- **Audit log**: sensor (`sensor.hemm_actuation_log` or per-device) + diagnostics
  section; anonymized.
- **Repair issues**: terminal verify failure and self-confirming-contract issues
  (replaces the never-raised `solver_degraded` stub in `repairs.py`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** `⬜`: Container — a planned device with a passing verify entity is
  actuated exactly once and recorded `verified` (covers FR-001 happy path).
- **SC-002** `⬜`: Container — a never-changing verify entity yields
  `max_attempts` calls then `safe_default` + a repair issue (covers FR-001
  failure path).
- **SC-003** `⬜`: Container — onboarding house in default mode completes a full
  solve with **zero** script calls (covers FR-002).
- **SC-004** `⬜`: Container — `dry_run: true` actuation runs verification logic
  and writes an audit entry with no script call (covers FR-003).
- **SC-005** `⬜`: Container — a device whose pre-call hard-constraint check fails
  is not actuated and falls to `safe_default` (covers FR-004).
- **SC-006** `⬜`: Container — stalling the coordinator past the watchdog timeout
  invokes `safe_default` for every device, including read-only/overridden ones
  (covers FR-005).
- **SC-007** `⬜`: Container — toggling `switch.hemm_<device>_override` suspends
  actuation for that device only (covers FR-006).
- **SC-008** `⬜`: The audit log/diagnostics expose attempt outcomes and contain
  no raw PII entity values (covers FR-007).

## Out of Scope / Folded-in

- **008:FR-004** (automatic periodic solve, `🔶 partial`, SR-003): close it in
  spec 008 by wiring a scheduled solve so the watchdog and actuation run on a
  real tick without an external `hemm.tick` automation. Tracked in 008, not here.
- **001:FR-013** (verify-independence warn, `🔶 partial`, SR-009): restore the
  validator test lost upstream; the engine's self-confirming-contract guard
  (Edge Cases) complements it. Tracked in 001.

## Assumptions

- Core actuation types (`Action`, `VerificationContract`, `RetryPolicy`,
  `safe_default`) are stable and already mandatory (001). No manifest-schema
  change is required for Phase 7.
- Actuation is exercised against a real HA container via `hactl`; mocked-core
  unit tests may cover pure engine logic (retry math, audit anonymization,
  read-only/override gating), but every `done` FR here is integration-tier and
  must be container-proven.
- The expected-value expression grammar in `VerificationContract.expected`
  (`>= 60`, `== off`, …) is interpreted by the engine; its parser is engine-owned
  and unit-testable.
