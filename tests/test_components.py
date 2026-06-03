"""Unit tests for the primitive component model (feature 003).

Scaffold created in T003. Tests are added in later phases:
- T008 — Primitive enum / DeviceRole retirement (003:FR-001, 003:FR-011)
- T009 — to_components() per named type (003:FR-002, 003:FR-003)
- T010 — every testdata manifest round-trips to a component set (003:FR-004)
- T016 — ConverterSpec.factor_at piecewise interpolation + clamping (003:FR-007)
"""

from __future__ import annotations
