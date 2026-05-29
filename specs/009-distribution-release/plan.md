# Implementation Plan: Distribution & Release

**Branch**: `009-distribution-release` | **Date**: 2026-05-29 |
**Spec**: [spec.md](./spec.md)

**Note**: Forward spec — drives new code for the soft-beta launch. All four FRs
are `⬜ todo`. FR-003's container test is expected to gate red until the first
PyPI publish turns it green.

## Summary

Make HEMM installable by the community. The core (`hemm`) publishes to PyPI on a
`v*` tag via a credential-free Trusted Publisher (OIDC); the integration pins its
`manifest.json` requirement to that exact version; an HA container resolves the
core from PyPI and the hub sets up. A single-source-of-truth version removes the
current `__version__` drift.

## Technical Context

**Language/Version**: Python 3.12 / 3.13
**Primary Dependencies**: `hemm/.github/workflows/release.yml`,
`pypa/gh-action-pypi-publish`, hatchling build, HA manifest requirement resolution
**Testing**: unit (workflow/manifest/version assertions) + container (install from
PyPI, hub setup via hactl)
**Project Type**: Release engineering across both child repos + the PyPI/GitHub
boundary
**Constraints**: no long-lived PyPI secret (OIDC only); manifest pin must equal a
real published version; `__version__` must equal the packaged version

## Constitution Check

- **III. Done = Green Tests on the right tier** — FR-001/002/004 are unit-tier
  (config/manifest/version assertions HA cannot observe); FR-003 is integration
  (real container install from PyPI). Each lands with a `req`-tagged test.
- **VII. Branding discipline** — release automation runs on `hemm-ems/hemm`; pairs
  with the Phase-3 org rename and the new `branding-audit`.
- **V. Clean Core/Integration Split** — unchanged; this is packaging only.

## Project Structure

```text
hemm/.github/workflows/release.yml              # + PyPI publish job (FR-001)
hemm/pyproject.toml                             # version source (FR-004)
hemm/src/hemm_core/__init__.py                  # __version__ from metadata (FR-004)
hemm/tests/test_release_packaging.py            # NEW unit: workflow + version (FR-001/004)
ha-hemm/custom_components/hemm/manifest.json    # exact pin == version (FR-002)
ha-hemm/tests/test_manifest_pin.py              # NEW unit: pin format/match (FR-002)
ha-hemm/tests/integration/test_pypi_install.py  # NEW container: PyPI resolve + hub setup (FR-003)
```

**Structure Decision**: New tests are additive; no source restructuring.

## Open Work (drives tasks.md)

- **FR-001** add a `publish-pypi` job to `release.yml` (`id-token: write`, env
  `pypi`, `pypa/gh-action-pypi-publish`) consuming the built `dist/*`.
- **FR-002** pin `manifest.json` `requirements` to `hemm==<version>` and make it
  equal `version`; add a unit test that reads and asserts both.
- **FR-003** add a container test that installs the integration with the core from
  PyPI (not `git+`) and asserts the hub config entry loads.
- **FR-004** derive `hemm_core.__version__` from `importlib.metadata.version("hemm")`
  (fallback for editable installs) and add a unit test asserting equality.

## Complexity Tracking

No violations. The only ordering subtlety: FR-003's green state depends on the
first real publish (FR-001) landing the version on PyPI; until then the test is
the intended gating red. Version reconciliation (the concrete number) is handled
in the master plan's Phase 4, consumed here.
