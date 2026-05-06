"""Tests for constraint vocabulary models."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError as PydanticValidationError

from hemm.manifest.constraints import (
    CONSTRAINT_VERSIONS,
    ConstraintType,
    ConstraintVocabulary,
    ForbiddenWindow,
    HoldTempBand,
    MaxRuntimePerDay,
    MinEnergyUntil,
    MinRuntimePerDay,
    MinSocUntil,
    ReachMinTempOnce,
)


class TestConstraintTypes:
    """Tests for constraint type enum."""

    @pytest.mark.unit
    def test_all_types_in_vocabulary(self) -> None:
        """Every ConstraintType must have a version in CONSTRAINT_VERSIONS."""
        for ct in ConstraintType:
            assert ct in CONSTRAINT_VERSIONS

    @pytest.mark.unit
    def test_vocabulary_versions_are_positive(self) -> None:
        for ct, version in CONSTRAINT_VERSIONS.items():
            assert version >= 1, f"{ct} has invalid version {version}"

    @pytest.mark.unit
    def test_constraint_vocabulary_model(self) -> None:
        vocab = ConstraintVocabulary()
        assert vocab.version == "1.0"
        assert len(vocab.constraints) == 7


class TestReachMinTempOnce:
    """Tests for reach_min_temp_once constraint."""

    @pytest.mark.unit
    def test_valid(self) -> None:
        c = ReachMinTempOnce(target_temp_c=60.0)
        assert c.type == "reach_min_temp_once"
        assert c.target_temp_c == 60.0

    @pytest.mark.unit
    def test_invalid_temp_zero(self) -> None:
        with pytest.raises(PydanticValidationError):
            ReachMinTempOnce(target_temp_c=0)

    @pytest.mark.unit
    def test_invalid_temp_over_100(self) -> None:
        with pytest.raises(PydanticValidationError):
            ReachMinTempOnce(target_temp_c=101)

    @pytest.mark.unit
    @settings(max_examples=100)
    @given(temp=st.floats(min_value=0.01, max_value=100.0, allow_nan=False))
    def test_valid_temps_property(self, temp: float) -> None:
        c = ReachMinTempOnce(target_temp_c=temp)
        assert c.target_temp_c == temp


class TestHoldTempBand:
    """Tests for hold_temp_band constraint."""

    @pytest.mark.unit
    def test_valid(self) -> None:
        c = HoldTempBand(min_temp_c=18.0, max_temp_c=22.0)
        assert c.type == "hold_temp_band"
        assert c.min_temp_c == 18.0
        assert c.max_temp_c == 22.0

    @pytest.mark.unit
    @settings(max_examples=100)
    @given(
        min_t=st.floats(min_value=-20, max_value=40, allow_nan=False),
        delta=st.floats(min_value=0.1, max_value=20, allow_nan=False),
    )
    def test_band_property(self, min_t: float, delta: float) -> None:
        """Property: band always has min <= max when constructed properly."""
        c = HoldTempBand(min_temp_c=min_t, max_temp_c=min_t + delta)
        assert c.min_temp_c <= c.max_temp_c


class TestMinSocUntil:
    """Tests for min_soc_until constraint."""

    @pytest.mark.unit
    def test_valid(self) -> None:
        c = MinSocUntil(min_soc_pct=80.0)
        assert c.type == "min_soc_until"
        assert c.min_soc_pct == 80.0

    @pytest.mark.unit
    def test_invalid_over_100(self) -> None:
        with pytest.raises(PydanticValidationError):
            MinSocUntil(min_soc_pct=101)

    @pytest.mark.unit
    def test_invalid_negative(self) -> None:
        with pytest.raises(PydanticValidationError):
            MinSocUntil(min_soc_pct=-1)

    @pytest.mark.unit
    @settings(max_examples=100)
    @given(soc=st.floats(min_value=0, max_value=100, allow_nan=False))
    def test_valid_soc_property(self, soc: float) -> None:
        c = MinSocUntil(min_soc_pct=soc)
        assert 0 <= c.min_soc_pct <= 100


class TestMinEnergyUntil:
    """Tests for min_energy_until constraint — semantically different from min_soc_until."""

    @pytest.mark.unit
    def test_valid(self) -> None:
        c = MinEnergyUntil(min_energy_kwh=60.0)
        assert c.type == "min_energy_until"
        assert c.min_energy_kwh == 60.0

    @pytest.mark.unit
    def test_invalid_zero(self) -> None:
        with pytest.raises(PydanticValidationError):
            MinEnergyUntil(min_energy_kwh=0)

    @pytest.mark.unit
    def test_invalid_negative(self) -> None:
        with pytest.raises(PydanticValidationError):
            MinEnergyUntil(min_energy_kwh=-10)

    @pytest.mark.unit
    def test_semantic_difference_from_soc(self) -> None:
        """min_energy_until targets cumulative flow, min_soc_until targets state variable."""
        energy = MinEnergyUntil(min_energy_kwh=60.0)
        soc = MinSocUntil(min_soc_pct=80.0)
        assert energy.type != soc.type
        # Energy is in kWh (absolute), SoC is in percent (relative)
        assert hasattr(energy, "min_energy_kwh")
        assert hasattr(soc, "min_soc_pct")


class TestForbiddenWindow:
    """Tests for forbidden_window constraint."""

    @pytest.mark.unit
    def test_valid(self) -> None:
        c = ForbiddenWindow()
        assert c.type == "forbidden_window"


class TestRuntimeConstraints:
    """Tests for min/max runtime per day."""

    @pytest.mark.unit
    def test_min_runtime_valid(self) -> None:
        c = MinRuntimePerDay(min_hours=2.0)
        assert c.min_hours == 2.0

    @pytest.mark.unit
    def test_max_runtime_valid(self) -> None:
        c = MaxRuntimePerDay(max_hours=8.0)
        assert c.max_hours == 8.0

    @pytest.mark.unit
    def test_min_runtime_invalid_zero(self) -> None:
        with pytest.raises(PydanticValidationError):
            MinRuntimePerDay(min_hours=0)

    @pytest.mark.unit
    def test_max_runtime_invalid_over_24(self) -> None:
        with pytest.raises(PydanticValidationError):
            MaxRuntimePerDay(max_hours=25)

    @pytest.mark.unit
    @settings(max_examples=100)
    @given(hours=st.floats(min_value=0.01, max_value=24.0, allow_nan=False))
    def test_valid_hours_property(self, hours: float) -> None:
        min_c = MinRuntimePerDay(min_hours=hours)
        max_c = MaxRuntimePerDay(max_hours=hours)
        assert min_c.min_hours == hours
        assert max_c.max_hours == hours
