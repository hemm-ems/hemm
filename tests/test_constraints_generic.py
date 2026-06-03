"""Generic (primitive-targeted) constraint tests (feature 003).

Scaffold created in T003. Tests are added in T022 (003:FR-008): constraints
resolve to primitive state vars/flows (storage level / node thermal state /
flow integral), and a constraint targeting a state a device's primitives do not
provide is rejected at validation.
"""

from __future__ import annotations
