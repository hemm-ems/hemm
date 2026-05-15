"""Adapter registry — stores and retrieves forecast/price adapters."""

from __future__ import annotations

from hemm_core.adapters.protocol import AdapterProtocol
from hemm_core.time import Clock, WallClock


class AdapterRegistry:
    """Registry for forecast and price adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, AdapterProtocol] = {}

    def register(self, adapter: AdapterProtocol) -> None:
        """Register an adapter by its name."""
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> AdapterProtocol:
        """Get an adapter by name.

        Raises:
            KeyError: If adapter not found.
        """
        if name not in self._adapters:
            msg = f"Adapter '{name}' not registered. Available: {list(self._adapters.keys())}"
            raise KeyError(msg)
        return self._adapters[name]

    def list_adapters(self) -> list[str]:
        """List registered adapter names."""
        return list(self._adapters.keys())

    def has(self, name: str) -> bool:
        """Check if an adapter is registered."""
        return name in self._adapters


# Global registry singleton
_registry: AdapterRegistry | None = None


def get_registry(*, clock: Clock | None = None) -> AdapterRegistry:
    """Get the global adapter registry, creating it if needed.

    Args:
        clock: Time source used when constructing the built-in adapters on
            first access. Subsequent calls return the cached registry
            regardless of `clock`. Use `reset_registry()` to discard it.
    """
    global _registry
    if _registry is None:
        _registry = AdapterRegistry()
        _register_builtin_adapters(_registry, clock=clock if clock is not None else WallClock())
    return _registry


def reset_registry() -> None:
    """Discard the cached registry (test helper)."""
    global _registry
    _registry = None


def _register_builtin_adapters(registry: AdapterRegistry, *, clock: Clock) -> None:
    """Register built-in adapters."""
    from hemm_core.adapters.forecast_solar import ForecastSolarAdapter
    from hemm_core.adapters.solcast import SolcastAdapter
    from hemm_core.adapters.template import TemplateAdapter

    registry.register(SolcastAdapter(clock=clock))
    registry.register(ForecastSolarAdapter(clock=clock))
    registry.register(TemplateAdapter(clock=clock))
