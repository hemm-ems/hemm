"""HEMM simulation harness — synthetic scenarios and multi-day simulation runner."""

from hemm.sim.comparison import ABComparisonRunner, ComparisonMetrics, ComparisonReport
from hemm.sim.runner import SimResult, SimRunner
from hemm.sim.scenario import Scenario, load_scenario
from hemm.sim.synthetic import generate_price_series, generate_weather_series

__all__ = [
    "ABComparisonRunner",
    "ComparisonMetrics",
    "ComparisonReport",
    "Scenario",
    "SimResult",
    "SimRunner",
    "generate_price_series",
    "generate_weather_series",
    "load_scenario",
]
