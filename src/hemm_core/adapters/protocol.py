"""Forecast adapter protocol — canonical schema and interface."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field


class ForecastPoint(BaseModel):
    """Single forecast data point — canonical schema.

    All forecast adapters produce sequences of ForecastPoint.
    """

    timestamp: datetime
    value: float = Field(description="Forecast value (kW for power, €/kWh for price, °C for temperature)")
    unit: str = Field(description="Unit of the value: 'kW', 'EUR_per_kWh', 'celsius'")


class AdapterProtocol(Protocol):
    """Protocol for forecast/price adapters.

    Adapters must implement fetch() which returns a list of ForecastPoints.
    """

    @property
    def name(self) -> str:
        """Adapter name."""
        ...

    @property
    def source_type(self) -> str:
        """Source type: 'solar', 'price', 'temperature', 'load'."""
        ...

    def fetch(self, **kwargs: object) -> list[ForecastPoint]:
        """Fetch forecast data.

        Kwargs are adapter-specific configuration (API keys, entity IDs, etc.)

        Returns:
            List of ForecastPoint in chronological order.
        """
        ...
