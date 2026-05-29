# Feature Specification: Distribution & Release

**Feature Branch**: `009-distribution-release`

**Created**: 2026-05-29

**Status**: Planned — soft-beta launch (forward spec, drives new code)

**Input**: `implementation-plan-hemm.md` Phase 9 (HACS readiness & release),
`concept-hemm.md` ("Repo layout"), the soft-beta launch plan. Code at
`hemm/.github/workflows/release.yml`, `hemm/pyproject.toml`,
`hemm/src/hemm_core/__init__.py`, `ha-hemm/custom_components/hemm/manifest.json`.

> FRs tagged `✅ done` / `🔶 partial` / `⬜ todo` with their parent System
> Requirement. This feature realizes **SR-012** (HEMM is distributed as a PyPI
> core and a HACS-installable HA integration). It is the delivery mechanism for
> the standalone core ([SR-011](../requirements.md)) into a running HA
> ([SR-001](../requirements.md)). Scope is the soft-beta launch: installability
> via a HACS custom repository. Phase 7 actuator work and HACS-default submission
> are out of scope.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A community user installs HEMM (Priority: P1)

A Home Assistant user adds the integration as a HACS custom repository, installs
"HEMM Energy Optimizer", restarts HA, and adds the integration. Home Assistant
resolves the pinned `hemm` core from PyPI automatically; the hub config entry
sets up without manual Python steps.

**Why this priority**: Today this fails — the manifest pins `hemm==2026.5.0`, which
is not on PyPI, so HA's requirement install errors and the integration never loads.
This is the load-bearing requirement for any community launch.

**Independent Test**: In a clean environment, `pip install hemm==<version>` resolves
from PyPI; in an HA container with the integration installed and its manifest pinned
to that version, the hub config entry sets up successfully.

### User Story 2 - A maintainer cuts a release (Priority: P1)

A maintainer pushes a `v*` tag on the core repo. CI builds the package and publishes
it to PyPI through a Trusted Publisher (OIDC) — no long-lived tokens stored anywhere.
The integration's manifest is pinned to that exact version.

**Why this priority**: Repeatable, credential-free releases are the mechanism behind
User Story 1; without automation the PyPI artifact drifts from the manifest pin.

**Acceptance Scenarios**:

1. **Given** the core repo at a release commit, **When** a `v*` tag is pushed,
   **Then** CI publishes the `hemm` package to PyPI via OIDC with no stored secret.
2. **Given** a published core version, **When** the integration manifest is read,
   **Then** its `requirements` pins `hemm==` that exact version and its `version`
   field equals the pinned version.
3. **Given** a clean HA container, **When** the integration is installed with the
   pinned manifest, **Then** the core resolves from PyPI and the hub sets up.

### Edge Cases

- Tag pushed without a matching `CHANGELOG` section → release notes fall back to a
  generic line (existing behavior), publish still proceeds.
- `__version__` and packaged version disagree → FR-004 guard fails in unit tests
  before release, surfacing the drift early.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `✅ done` `unit` `SR-012`: The core repo MUST publish the `hemm`
  package to PyPI automatically on a `v*` tag, via a PyPI **Trusted Publisher**
  (OIDC) with `id-token: write` and a dedicated `pypi` environment — no long-lived
  PyPI credentials stored in the repo or CI secrets.
- **FR-002** `✅ done` `unit` `SR-012`: The integration `manifest.json`
  `requirements` MUST pin the core to an exact published version (`hemm==X.Y.Z`),
  and that pinned version MUST equal the integration's own `version` field.
- **FR-003** `✅ done` `SR-012`: An HA instance that installs the integration MUST
  resolve the pinned `hemm` core from PyPI and bring up the HEMM hub config entry
  successfully — proven end-to-end in a container against the manifest-pinned
  version (not a `git+` install).
- **FR-004** `✅ done` `unit` `SR-012`: `hemm_core.__version__` MUST equal the
  packaged distribution version (single source of truth), removing the current
  `0.1.0` vs `2026.5.0` drift so `hemm --version` and the published wheel agree.

### Key Entities

- **PyPI Trusted Publisher**: OIDC link between `hemm-ems/hemm` / `release.yml` /
  env `pypi` and the PyPI `hemm` project (pre-registered, pending first publish).
- **`release.yml`**: builds the wheel/sdist, creates the GitHub release, and (new)
  publishes to PyPI.
- **`manifest.json`**: the integration's pin to the published core version.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** `✅`: After a `v*` tag, the exact version is installable via
  `pip install hemm==<version>` from PyPI in a clean venv (covers FR-001).
- **SC-002** `✅`: A unit test reads `manifest.json` and asserts an exact `hemm==`
  pin equal to the integration `version` (covers FR-002).
- **SC-003** `✅`: A container test installs the integration with the core resolved
  from PyPI and the hub config entry reaches "loaded" (covers FR-003).
- **SC-004** `✅`: A unit test asserts `hemm_core.__version__ ==`
  `importlib.metadata.version("hemm")` (covers FR-004).

## Assumptions

- The PyPI `hemm` project and its pending Trusted Publisher are pre-registered
  out-of-band (confirmed 2026-05-29).
- The canonical org is `hemm-ems`; release automation runs on `hemm-ems/hemm`.
- FR-003's container test installs from PyPI once the first version is published;
  until then it is expected to be the gating "red" test that the release turns green.
