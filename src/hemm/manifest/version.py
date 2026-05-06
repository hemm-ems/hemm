"""Version specifier resolver for constraint endpoints."""

from __future__ import annotations

import re
from typing import Self

from pydantic import BaseModel, field_validator

_VERSION_PATTERN = re.compile(r"^(>=|<=|==|!=|>|<)(\d+)$")


class VersionSpecifier(BaseModel):
    """A version specifier for constraint endpoint compatibility.

    Format: operator + integer version, e.g. ">=1", "==2", "!=1".
    """

    operator: str
    version: int

    @classmethod
    def parse(cls, spec: str) -> Self:
        """Parse a version specifier string like '>=1'."""
        match = _VERSION_PATTERN.match(spec.strip())
        if not match:
            msg = f"Invalid version specifier: '{spec}'. Expected format like '>=1', '==2', '<3'."
            raise ValueError(msg)
        return cls(operator=match.group(1), version=int(match.group(2)))

    @field_validator("operator")
    @classmethod
    def _validate_operator(cls, v: str) -> str:
        valid = {">=", "<=", "==", "!=", ">", "<"}
        if v not in valid:
            msg = f"Invalid operator: '{v}'. Must be one of {valid}."
            raise ValueError(msg)
        return v

    def matches(self, version: int) -> bool:
        """Check if a given version satisfies this specifier."""
        return check_version(version, self)

    def __str__(self) -> str:
        return f"{self.operator}{self.version}"


def check_version(version: int, spec: VersionSpecifier) -> bool:
    """Check if a version satisfies a specifier."""
    ops: dict[str, bool] = {
        ">=": version >= spec.version,
        "<=": version <= spec.version,
        "==": version == spec.version,
        "!=": version != spec.version,
        ">": version > spec.version,
        "<": version < spec.version,
    }
    return ops[spec.operator]
