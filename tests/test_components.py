"""Unit tests for the primitive component model (feature 003).

Scaffold created in T003. Tests are added in later phases:
- T008 — Primitive enum / DeviceRole retirement (003:FR-001, 003:FR-011)
- T009 — to_components() per named type (003:FR-002, 003:FR-003)
- T010 — every testdata manifest round-trips to a component set (003:FR-004)
- T016 — ConverterSpec.factor_at piecewise interpolation + clamping (003:FR-007)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hemm_core.manifest.components import ComponentSpec, ConverterSpec
from hemm_core.manifest.types import (
    _ManifestBase,
    BatteryManifest,
    EVChargerManifest,
    HeatPumpManifest,
    ManifestType,
    PVForecastManifest,
    PassiveLoadManifest,
    Primitive,
    RoomManifest,
    ThermostatLoadManifest,
    WaterHeaterManifest,
)
from hemm_core.manifest.validator import validate_manifest
from hemm_core.sim.scenario import load_scenario

SCENARIOS_DIR = Path(__file__).parent.parent / "testdata" / "scenarios"


def _safe_default() -> dict[str, str]:
    return {"script": "script.safe"}


def _primitive_set(manifest: _ManifestBase) -> set[Primitive]:
    return {component.primitive for component in manifest.to_components()}


@pytest.mark.req("003:FR-001", "003:FR-011")
class TestPrimitive:
    """Primitive enum and DeviceRole retirement tests."""

    @pytest.mark.unit
    def test_five_primitives(self) -> None:
        assert len(Primitive) == 5
        assert {p.value for p in Primitive} == {"source", "sink", "storage", "converter", "node"}

    @pytest.mark.unit
    def test_device_role_export_is_gone(self) -> None:
        with pytest.raises(ImportError):
            from hemm_core.manifest import DeviceRole  # noqa: F401

    @pytest.mark.unit
    def test_every_manifest_type_has_primitives(self) -> None:
        for manifest_type in ManifestType:
            assert manifest_type.primitives
            assert all(isinstance(primitive, Primitive) for primitive in manifest_type.primitives)


@pytest.mark.req("003:FR-002", "003:FR-003")
class TestToComponents:
    """Named manifest compile-step tests."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("manifest", "expected"),
        [
            (
                RoomManifest(
                    device_id="room1",
                    name="Room",
                    floor_area_m2=20.0,
                    safe_default=_safe_default(),
                ),
                {Primitive.NODE},
            ),
            (
                ThermostatLoadManifest(
                    device_id="thermo1",
                    name="Thermostat",
                    max_power_kw=2.0,
                    safe_default=_safe_default(),
                ),
                {Primitive.SINK},
            ),
            (
                HeatPumpManifest(
                    device_id="hp1",
                    name="Heat Pump",
                    max_power_kw=5.0,
                    safe_default=_safe_default(),
                ),
                {Primitive.SINK},
            ),
            (
                WaterHeaterManifest(
                    device_id="dhw1",
                    name="Water Heater",
                    volume_liters=180.0,
                    max_power_kw=3.0,
                    safe_default=_safe_default(),
                ),
                {Primitive.NODE, Primitive.CONVERTER, Primitive.STORAGE},
            ),
            (
                BatteryManifest(
                    device_id="bat1",
                    name="Battery",
                    capacity_kwh=10.0,
                    max_charge_kw=5.0,
                    max_discharge_kw=5.0,
                    safe_default=_safe_default(),
                ),
                {Primitive.STORAGE},
            ),
            (
                PVForecastManifest(
                    device_id="pv1",
                    name="PV",
                    peak_power_kwp=6.0,
                    safe_default=_safe_default(),
                ),
                {Primitive.SOURCE},
            ),
            (
                EVChargerManifest(
                    device_id="ev1",
                    name="EV",
                    max_charge_kw=11.0,
                    safe_default=_safe_default(),
                ),
                {Primitive.STORAGE},
            ),
            (
                PassiveLoadManifest(
                    device_id="base1",
                    name="Base Load",
                    typical_daily_kwh=12.0,
                    safe_default=_safe_default(),
                ),
                {Primitive.SINK},
            ),
        ],
    )
    def test_named_types_return_expected_primitives(self, manifest: _ManifestBase, expected: set[Primitive]) -> None:
        assert _primitive_set(manifest) == expected
        assert type(manifest).to_components is not _ManifestBase.to_components

    @pytest.mark.unit
    def test_heat_pump_with_room_compiles_to_converter(self) -> None:
        manifest = HeatPumpManifest(
            device_id="hp1",
            name="Heat Pump",
            max_power_kw=5.0,
            room_id="room1",
            safe_default=_safe_default(),
        )

        components = manifest.to_components()

        assert _primitive_set(manifest) == {Primitive.CONVERTER}
        assert isinstance(components[0], ConverterSpec)
        assert components[0].output_bus == "thermal:room1"

    @pytest.mark.unit
    def test_thermostat_with_room_compiles_to_converter(self) -> None:
        manifest = ThermostatLoadManifest(
            device_id="thermo1",
            name="Thermostat",
            max_power_kw=2.0,
            room_id="room1",
            safe_default=_safe_default(),
        )

        components = manifest.to_components()

        assert _primitive_set(manifest) == {Primitive.CONVERTER}
        assert isinstance(components[0], ConverterSpec)
        assert components[0].output_bus == "thermal:room1"

    @pytest.mark.unit
    def test_thermal_nodes_use_thermal_bus_ids(self) -> None:
        room = RoomManifest(
            device_id="room1",
            name="Room",
            floor_area_m2=20.0,
            safe_default=_safe_default(),
        )
        water_heater = WaterHeaterManifest(
            device_id="dhw1",
            name="Water Heater",
            volume_liters=180.0,
            max_power_kw=3.0,
            safe_default=_safe_default(),
        )

        assert room.to_components()[0].bus == "thermal:room1"
        assert water_heater.to_components()[0].bus == "thermal:dhw1"

    @pytest.mark.unit
    def test_passive_load_is_fixed_sink(self) -> None:
        manifest = PassiveLoadManifest(
            device_id="base1",
            name="Base Load",
            typical_daily_kwh=12.0,
            safe_default=_safe_default(),
        )

        sink = manifest.to_components()[0]

        assert sink.primitive == Primitive.SINK
        assert sink.min_power_kw == 0.5
        assert sink.max_power_kw == 0.5
        assert sink.controllable is False


@pytest.mark.req("003:FR-004")
class TestScenarioComponents:
    """Scenario manifest component round-trip tests."""

    @pytest.mark.unit
    @pytest.mark.parametrize("scenario_path", sorted(SCENARIOS_DIR.glob("*.yaml")))
    def test_scenario_manifests_compile_to_components(self, scenario_path: Path) -> None:
        scenario = load_scenario(scenario_path)

        for manifest_data in scenario.manifests:
            manifest = validate_manifest(manifest_data)
            components = manifest.to_components()

            assert isinstance(components, list)
            assert components
            assert all(isinstance(component, ComponentSpec) for component in components)
            for component in components:
                assert component.device_id == manifest.device_id
                assert component.bus
                if isinstance(component, ConverterSpec):
                    assert component.input_bus
                    assert component.output_bus


@pytest.mark.req("003:FR-007")
class TestConverterSpec:
    """Converter factor interpolation tests."""

    @pytest.mark.unit
    def test_factor_at_interpolates_and_clamps(self) -> None:
        converter = ConverterSpec(
            device_id="conv1",
            output_bus="thermal:room1",
            max_input_kw=5.0,
            factor_map=[(10.0, 4.5), (-10.0, 2.5), (0.0, 3.5)],
        )

        assert converter.factor_at(-20.0) == 2.5
        assert converter.factor_at(20.0) == 4.5
        assert converter.factor_at(5.0) == 4.0

    @pytest.mark.unit
    def test_factor_at_empty_map_defaults_to_eta_one(self) -> None:
        converter = ConverterSpec(
            device_id="conv1",
            output_bus="thermal:room1",
            max_input_kw=5.0,
            factor_map=[],
        )

        assert converter.factor_at(5.0) == 1.0
