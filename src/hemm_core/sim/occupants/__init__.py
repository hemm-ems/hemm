"""Occupant demand simulation support."""

from hemm_core.sim.occupants.adapters import load_household_profile, register_adapter
from hemm_core.sim.occupants.interventions import apply_interventions
from hemm_core.sim.occupants.profile import ApplianceEvent, HouseholdProfile, HouseholdSlot, read_profile, write_profile
from hemm_core.sim.occupants.synthetic import generate_synthetic_profile
from hemm_core.sim.occupants.validation import ResourceConflict, validate_profile

__all__ = [
    "ApplianceEvent",
    "HouseholdProfile",
    "HouseholdSlot",
    "ResourceConflict",
    "apply_interventions",
    "generate_synthetic_profile",
    "load_household_profile",
    "read_profile",
    "register_adapter",
    "validate_profile",
    "write_profile",
]
