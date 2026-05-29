---
description: "Task list for 009 Distribution & Release"
---

# Tasks: Distribution & Release

**Input**: [spec.md](./spec.md), [plan.md](./plan.md). `[X]` = built & tested.
All tasks land with a `req`-tagged test (TDD: red test first, then green).

## Phase 1: Version single-source-of-truth (FR-004)

- [ ] T001 [US2] Derive `hemm_core.__version__` from `importlib.metadata.version("hemm")` with an editable-install fallback — `hemm/src/hemm_core/__init__.py` (FR-004)
- [ ] T002 [US2] Unit test: `hemm_core.__version__ == importlib.metadata.version("hemm")` — `hemm/tests/test_release_packaging.py` `@req("009:FR-004")` (SC-004)

## Phase 2: PyPI publish automation (FR-001)

- [ ] T003 [US2] Add `publish-pypi` job to `release.yml` — `id-token: write`, env `pypi`, `pypa/gh-action-pypi-publish`, consumes built `dist/*` — `hemm/.github/workflows/release.yml` (FR-001)
- [ ] T004 [US2] Unit test asserting the workflow declares OIDC publish (id-token, env, action) and stores no PyPI token — `hemm/tests/test_release_packaging.py` `@req("009:FR-001")` (SC-001)

## Phase 3: Manifest pin (FR-002)

- [ ] T005 [US1] Pin `manifest.json` `requirements` to `hemm==<version>` equal to `version` — `ha-hemm/custom_components/hemm/manifest.json` (FR-002)
- [ ] T006 [US1] Unit test: manifest `requirements` is an exact `hemm==` pin equal to `version` — `ha-hemm/tests/test_manifest_pin.py` `@req("009:FR-002")` (SC-002)

## Phase 4: End-to-end install (FR-003)

- [ ] T007 [US1] Container test: install integration with core resolved from PyPI (not `git+`), assert hub config entry loads — `ha-hemm/tests/integration/test_pypi_install.py` `@req("009:FR-003")` (SC-003)

## Dependencies

- T001→T002 (version source before its test). T003→T004 (job before assertion).
  T005→T006. T007 (FR-003) gates **red** until the first `v*` publish (T003 + the
  Phase-6 tag) lands the version on PyPI; it turns green post-release.
- The concrete release version number is decided in the master plan's Phase 4 and
  consumed by T001/T005.
