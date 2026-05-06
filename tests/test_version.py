"""Tests for the version specifier resolver."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hemm.manifest.version import VersionSpecifier, check_version


class TestVersionSpecifierParsing:
    """Tests for parsing version specifier strings."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("spec_str", "expected_op", "expected_ver"),
        [
            (">=1", ">=", 1),
            ("<=2", "<=", 2),
            ("==1", "==", 1),
            ("!=1", "!=", 1),
            (">3", ">", 3),
            ("<5", "<", 5),
            (">=10", ">=", 10),
        ],
    )
    def test_parse_valid(self, spec_str: str, expected_op: str, expected_ver: int) -> None:
        spec = VersionSpecifier.parse(spec_str)
        assert spec.operator == expected_op
        assert spec.version == expected_ver

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "spec_str",
        [
            "",
            "abc",
            ">=",
            "1",
            ">>1",
            ">=1.0",
            ">=-1",
            "~ 1",
        ],
    )
    def test_parse_invalid(self, spec_str: str) -> None:
        with pytest.raises(ValueError, match="Invalid version specifier"):
            VersionSpecifier.parse(spec_str)

    @pytest.mark.unit
    def test_str_roundtrip(self) -> None:
        for spec_str in [">=1", "<=2", "==3", "!=4", ">5", "<6"]:
            spec = VersionSpecifier.parse(spec_str)
            assert str(spec) == spec_str


class TestCheckVersion:
    """Tests for version checking logic."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("version", "spec_str", "expected"),
        [
            (1, ">=1", True),
            (2, ">=1", True),
            (0, ">=1", False),
            (1, "<=1", True),
            (0, "<=1", True),
            (2, "<=1", False),
            (1, "==1", True),
            (2, "==1", False),
            (1, "!=1", False),
            (2, "!=1", True),
            (2, ">1", True),
            (1, ">1", False),
            (0, "<1", True),
            (1, "<1", False),
        ],
    )
    def test_check(self, version: int, spec_str: str, expected: bool) -> None:
        spec = VersionSpecifier.parse(spec_str)
        assert check_version(version, spec) == expected
        assert spec.matches(version) == expected

    @pytest.mark.unit
    @settings(max_examples=200)
    @given(
        version=st.integers(min_value=0, max_value=100),
        spec_version=st.integers(min_value=0, max_value=100),
    )
    def test_gte_property(self, version: int, spec_version: int) -> None:
        """Property: >= is equivalent to Python's >=."""
        spec = VersionSpecifier(operator=">=", version=spec_version)
        assert spec.matches(version) == (version >= spec_version)

    @pytest.mark.unit
    @settings(max_examples=200)
    @given(
        version=st.integers(min_value=0, max_value=100),
        spec_version=st.integers(min_value=0, max_value=100),
    )
    def test_eq_property(self, version: int, spec_version: int) -> None:
        """Property: == is equivalent to Python's ==."""
        spec = VersionSpecifier(operator="==", version=spec_version)
        assert spec.matches(version) == (version == spec_version)

    @pytest.mark.unit
    @settings(max_examples=200)
    @given(
        version=st.integers(min_value=0, max_value=100),
        spec_version=st.integers(min_value=0, max_value=100),
    )
    def test_lt_property(self, version: int, spec_version: int) -> None:
        """Property: < is equivalent to Python's <."""
        spec = VersionSpecifier(operator="<", version=spec_version)
        assert spec.matches(version) == (version < spec_version)
