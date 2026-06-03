# Specification Quality Checklist: Generic Entities — the Primitive Component Model

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-06-03
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- This is a HEMM **retro/house-format** spec: FRs carry `⬜ todo` status tags, a test-tier
  token (`unit` where the FR is pure solver/schema logic; default integration for the
  end-to-end thesis smoke test FR-012), and a `` `SR-NNN` `` parent tag, per
  `specs/README.md`. These tags are house traceability metadata parsed by
  `tools/req_coverage.py`, **not** the implementation-detail leakage the generic checklist
  warns against — the FR bodies stay capability-level.
- Specific file names (`manifest/components.py`, `solvers/milp_central.py`,
  `solvers/consumers.py`) are named in FRs because this is a **behavior-preserving refactor
  of named existing modules**; the *what/why* (dispatch on primitives, parity gate) is the
  requirement, the paths anchor traceability. The `/speckit-plan` step owns the detailed HOW.
- Four prior open questions were resolved before authoring (feature number 003; WaterHeater
  = node + converter + storage; DeviceRole → Primitive rename accepted as a schema break;
  parent SRs = SR-006 primary, SR-004/SR-005 for the backend cutovers). No
  [NEEDS CLARIFICATION] markers remain; `/speckit-clarify` is optional, not blocking.
- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`.
