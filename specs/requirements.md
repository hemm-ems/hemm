# HEMM System Requirements (SR)

The top of the V. These are the **foundational requirements** — what HEMM *is*, where
it runs, and the core mechanisms everything else is built on. They are deliberately few
and architectural. Feature detail belongs one level down, in the per-feature
Functional Requirements (`FR-NNN` in each `specs/NNN-slug/spec.md`), which trace up to
the SR they realize via a `` `SR-NN` `` tag on the FR line.

- **Single owner, hand-authored.** This is the one requirements artifact a human edits.
  Everything below it (FRs, `tasks.md`, `coverage.md`) is feature-local or derived.
- **Foundation, not a feature mirror.** An SR states bedrock ("HEMM shall plan energy
  entities with a MILP solver"), never a restatement of a single FR. If a candidate SR
  maps one-to-one onto one feature's detail, it's an FR, not an SR.
- **Status is derived.** SRs carry no hand-typed status. FRs tag their parent
  (`` `SR-NN` `` as the last token before the colon); `tools/req_coverage.py` rolls
  coverage up: SR → FR → test.
- **Source material:** `concept-hemm.md`, `.specify/memory/constitution.md`.

---

## SR-001 — HEMM is a Home Assistant integration, configured in HA

HEMM shall be installed and operated as a Home Assistant integration. All configuration
shall be done in HA through a click-based config flow — no YAML. A single **hub** config
entry hosts the solver/coordinator; each energy-relevant device is a **sub-entry** under
that hub.

> *Source: concept "Positioning", "Custom component in HA", onboarding walkthrough.*

## SR-002 — HEMM plans the energy-relevant entities of a house

HEMM shall coordinate heterogeneous producers and consumers (PV, battery, EV, heat pump,
hot water, rooms, …) over a planning horizon, producing one coherent plan of
consumption/production per device per time slot.

> *Source: concept "Problem", "Plan message".*

## SR-003 — HEMM re-plans against reality on a periodic tick

HEMM shall re-plan on a periodic tick over a rolling horizon, pulling current state from
HA each tick so the plan continuously re-adjusts to reality and absorbs forecast error,
without churning near-term actuator commands.

> *Source: concept "Problem" (iterative re-adjustment), "MPC on top", "Plan-change penalty".*

## SR-004 — A central MILP solver produces the plan (the default backend)

HEMM shall provide a central MILP solver that builds a single optimization problem over
all devices and returns the optimal plan. This backend is the default and the **oracle**
against which any alternative is measured.

> *Source: concept "Backend A: Central MILP"; constitution IV.*

## SR-005 — A distributed backend exists behind the same interface, evaluated against the oracle

HEMM shall support a second, distributed solver backend behind one shared solver
interface, selectable by configuration, and shall evaluate it against the oracle on
identical, reproducible scenarios (the sim harness). It is promoted to default only if
it beats the oracle on agreed, measurable criteria.

> *Source: concept "Backend B", "Two-solver architecture", "Falsifiable success criterion"; constitution IV.*

## SR-006 — Devices describe themselves declaratively; the core holds no vendor knowledge

Every device shall be represented by a declarative **manifest** — its constraints,
executable actions, and cost-function shape — using a shared, versioned vocabulary and
containing no code. The HEMM core shall contain no vendor- or installation-specific
knowledge; new device types are added without changing the core.

> *Source: concept "Main thesis", "Device specifics", "Constraint vocabulary".*

## SR-007 — Forecast and price signals enter through pluggable adapters

Forecast and electricity-price signals shall be ingested through pluggable **adapters**
that normalize any source into a single canonical form, with a template adapter as a
universal fallback so new sources need no core change.

> *Source: concept "Forecast adapter pattern".*

## SR-008 — Demand enters through a service API driven by HA automations

Demand — constraints with deadlines and numeric flex — shall be registered into the
solver from HA automations through HEMM's **service API**; HEMM optimizes timing within
the registered windows. Preconditions and conditional logic stay in HA, not in HEMM.

> *Source: concept "Plug point 1: demand registration".*

## SR-009 — HEMM observes and plans, but actuates only through verified user actions

HEMM shall never drive hardware directly. It shall support an observe-first, read-only
mode, and any actuation shall go through user-defined HA scripts that are **verified**
(expected change / timeout / retry). Every device shall declare a mandatory
`safe_default`, and side-effecting services shall support `dry_run`.

> *Source: concept "Plug point 2", read-only onboarding; constitution VI.*

## SR-010 — Setup scales from beginner to pro, with transparent model refinement

Device configuration shall be tiered (beginner ↔ advanced ↔ pro), letting a standard
house be set up in minutes on sane defaults while experts enter raw parameters. HEMM
shall refine device models from real history only with explicit user confirmation —
never silently — and expose model confidence.

> *Source: concept "Self-models: low skill floor, high ceiling", "Online identification".*

## SR-011 — Solver/domain logic is a standalone, HA-independent core

The planning and domain logic shall live in a standalone, pure-Python package (`hemm`)
with no Home Assistant imports, usable and testable on its own (including a CLI sim
harness). The HA integration (`ha-hemm`) shall hold HA glue only.

> *Source: concept "Repo layout"; constitution V.*

## SR-012 — HEMM is distributed as a PyPI core and a HACS-installable HA integration

HEMM shall be delivered as two published artifacts: the standalone core as a versioned
package on PyPI (`hemm`), and the HA integration as a HACS-installable custom component
that depends on a pinned core version. A user shall be able to install the integration
through HACS and have the core resolved automatically, without manual Python steps.

> *Source: concept "Repo layout"; implementation-plan Phase 9 (HACS readiness & release).
> Complements SR-001 (configured in HA) and SR-011 (standalone core) by stating how the
> two halves are delivered to users.*
