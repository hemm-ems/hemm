<!--
Sync Impact Report
Version change: 1.0.0 → 1.1.0
Modified principles: I (Spec Before Code) — now scoped to product capability, not dev-process
Added sections: Principle VIII (Spec It, or Don't — Process vs. Product)
Amended sections: Spec Workflow (specs now live in the core repo, not a separate parent;
  the umbrella has been dissolved into two repos)
Removed sections: none
Templates requiring updates:
  ✅ .specify/templates/plan-template.md — Constitution Check aligns (generic gates, no conflict)
  ✅ .specify/templates/spec-template.md — testable-requirements expectation compatible
  ✅ .specify/templates/tasks-template.md — test-tier task types compatible
Follow-up TODOs: none
-->

# HEMM Constitution

This constitution is intentionally thin. The authoritative, detailed norms for
working on HEMM live in **`AGENT.md`** (shared norms kept in sync between
`hemm/` and `ha-hemm/`; the core's `AGENT.md` additionally owns the specs/gate
sections). This document states the load-bearing principles and the
Spec-Driven workflow layered on top of them; it never duplicates `AGENT.md` —
it points to it.

## Core Principles

### I. Spec Before Code

Every new **product capability** (see Principle VIII) or change to an existing
one MUST have a spec under `specs/` before implementation begins. The spec
defines testable Functional Requirements (FRs) and Acceptance Criteria; code
follows the spec, not the reverse. This extends `AGENT.md`'s "Plan before
acting" with a durable, versioned requirements artifact. Retroactive specs for
already-built capabilities are descriptive: each FR carries a status
(`✅ done` / `🔶 partial` / `⬜ todo`), and `done` FRs MUST be backed by
existing tests. Dev-process / tooling / CI / release-plumbing changes are
explicitly out of scope here — they need no spec (Principle VIII).

### II. Manifest Is the Contract

The manifest schema and constraint vocabulary are the central design artifact.
Constraint types are semantically versioned (`reach_min_temp_once: ">=1"`). v1
semantics MUST NOT change silently; extensions go to v2. The core MUST NOT
require a manifest field absent from older manifests. See `AGENT.md` →
"Manifest is the contract".

### III. Done = Green Tests, On the Right Tier

A capability without tests is unfinished. Acceptance Criteria MUST be testable
with measurable thresholds (e.g. `cost gap < 3 %`, `p95 < 5 s`), never vague
language. Test tiers (`unit` / `container` / `pi` / `slow`) and canonical
Make targets are defined in `AGENT.md`; specs reference the tier that proves a
given FR. Docker integration tests are mandatory per phase or fix.

### IV. Two Backends, Data-Driven A/B

Backend A (central MILP) is the default and oracle; Backend B (distributed) is
a falsifiable hypothesis with kill criteria. Both implement one `Solver`
interface and are tested against identical scenarios. The A/B decision is
data-driven, documented in `docs/solver-decision.md`. No implementation may be
biased to favor one backend, and no merge may break Backend A's oracle status.

### V. Clean Core/Integration Split

`hemm` (core) is pure Python with no HA imports — schema, solvers, adapters,
sim, online-ID. `ha-hemm` (integration) holds HA glue only. If tempted to put
HA imports in the core: stop. The split is the architecture. See `AGENT.md` →
"What goes where".

### VI. Safe Write-Path (Dry-Run, Verification, Safe-Default)

Every service with side effects MUST accept `dry_run: true` and run the full
path — including verification — without real effect. Actuator calls MUST carry
a three-element verification contract (expected change / timeout / retry); a
call without one is rejected by the validator. Every manifest MUST define a
mandatory `safe_default`. Hard constraints are re-checked before every call.

### VII. Branding & Time Discipline

Every HA-visible identifier carries the `hemm` prefix (enforced by the branding
audit). All time reads in domain logic go through an injected `Clock`, never
direct `datetime.now()`/`asyncio.sleep` for business logic; the `make
check-clock` audit breaks the build on violation.

### VIII. Spec It, or Don't — Process vs. Product

Not every change earns a spec/FR. The default is decided by *what the change
affects*, to avoid re-litigating "do we even spec this?" per change:

- **Product capability** — changes what HEMM *does* and is user-observable
  (solver behavior, manifest schema, services, sensors, the produced plan).
  → Full FR in `specs/`, traces to an SR, test-backed at its intended tier.
- **Dev-process / tooling / CI / release-plumbing** — the coverage gate,
  audits, CI workflows, build scripts, dev Make targets. → **No spec/FR.**
  Governed by this constitution and its own tagged tests (the way the coverage
  gate and branding audit were hardened).
- **Grey-zone (distribution / release)** — an FR only per **user-observable
  outcome** ("installs via HACS"), never one per plumbing file.

Test: would a HEMM *user* notice the change? Yes → product → spec it. Only a
*developer* notices → process → no spec. See `AGENT.md` → "Spec it, or don't".

## Authoritative Norms

`AGENT.md` is the single source of truth for: repo layout, canonical Make
targets and test tiers, working principles (read-before-write, no speculative
fixes), what-goes-where, the manifest contract, two-backend discipline,
branding, the time-warp mechanisms, and onboarding-first. This constitution
MUST NOT restate those details; when they conflict in wording, `AGENT.md`
prevails on the detail and this document prevails on the workflow gate.

## Spec Workflow

Specs live in the **core repo** (`hemm`) under `specs/NNN-slug/` — the home
base — even though features are cross-cutting (core + integration), because the
core owns the spec/gate tooling. Implementation branches and commits happen in
the affected repo(s) (`hemm` / `ha-hemm`); the gate scans both via the sibling
`../ha-hemm` checkout.

Per-spec lifecycle (Spec Kit skills): `/speckit-specify` → `/speckit-clarify`
(de-risk) → `/speckit-plan` → `/speckit-tasks` → `/speckit-analyze`
(consistency gate) → `/speckit-implement`. For retroactive specs of built
capabilities, the same artifacts are produced descriptively and `tasks.md`
reflects completed work; only `⬜`/`🔶` FRs become live tasks.

The concept (`concept-hemm.md`), phase plan (`implementation-plan-hemm.md`),
test concept (`test-concept-hemm.md`), and review (`local-concept-roast.md`)
remain source material; specs reference them rather than replacing them.

## Governance

This constitution sits above ad-hoc practice for the spec-workflow gate; on
detailed norms it defers to `AGENT.md` (see Authoritative Norms). Amendments
require: a written rationale, a semantic version bump (MAJOR = incompatible
principle removal/redefinition; MINOR = new principle/section; PATCH =
clarification), and a Sync Impact Report prepended to this file. When an
amendment changes mandatory spec/plan/task structure, the corresponding
templates under `.specify/templates/` MUST be updated in the same change.
Compliance is verified at `/speckit-analyze` and at code review.

**Version**: 1.1.0 | **Ratified**: 2026-05-06 | **Last Amended**: 2026-05-29
