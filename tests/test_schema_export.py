"""Tests for JSON Schema export and CLI commands."""

from __future__ import annotations

import json

import pytest

from hemm_core.cli import main
from hemm_core.manifest.schema_export import (
    export_schemas_json,
    get_all_schemas,
    get_constraint_schema,
    get_manifest_schema,
    get_message_schema,
)


@pytest.mark.req("001:FR-011")
class TestSchemaExport:
    """Tests for schema export functions."""

    @pytest.mark.unit
    def test_get_manifest_schema_room(self) -> None:
        schema = get_manifest_schema("room")
        assert schema["title"] == "RoomManifest"
        assert "properties" in schema

    @pytest.mark.unit
    def test_get_manifest_schema_all_types(self) -> None:
        for t in [
            "room",
            "thermostat_load",
            "heat_pump",
            "water_heater",
            "battery",
            "pv_forecast",
            "ev_charger",
            "passive_load",
        ]:
            schema = get_manifest_schema(t)
            assert "properties" in schema

    @pytest.mark.unit
    def test_get_manifest_schema_unknown(self) -> None:
        with pytest.raises(ValueError, match="Unknown manifest type"):
            get_manifest_schema("teleporter")

    @pytest.mark.unit
    def test_get_constraint_schema(self) -> None:
        schema = get_constraint_schema("min_soc_until")
        assert "properties" in schema

    @pytest.mark.unit
    def test_get_constraint_schema_unknown(self) -> None:
        with pytest.raises(ValueError, match="Unknown constraint type"):
            get_constraint_schema("warp_drive")

    @pytest.mark.unit
    def test_get_message_schema(self) -> None:
        schema = get_message_schema("plan_message")
        assert "properties" in schema

    @pytest.mark.unit
    def test_get_all_schemas(self) -> None:
        schemas = get_all_schemas()
        # 8 manifests + 7 constraints + 4 messages = 19
        assert len(schemas) == 19

    @pytest.mark.unit
    def test_export_schemas_json_valid(self) -> None:
        result = export_schemas_json()
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert len(parsed) == 19


class TestCLISchema:
    """Tests for CLI schema export command."""

    @pytest.mark.unit
    def test_schema_all(self, capsys: pytest.CaptureFixture[str]) -> None:
        ret = main(["schema"])
        assert ret == 0
        output = capsys.readouterr().out
        parsed = json.loads(output)
        assert len(parsed) == 19

    @pytest.mark.unit
    def test_schema_specific_type(self, capsys: pytest.CaptureFixture[str]) -> None:
        ret = main(["schema", "battery"])
        assert ret == 0
        output = capsys.readouterr().out
        parsed = json.loads(output)
        assert parsed["title"] == "BatteryManifest"

    @pytest.mark.unit
    def test_schema_constraint(self, capsys: pytest.CaptureFixture[str]) -> None:
        ret = main(["schema", "min_soc_until"])
        assert ret == 0
        output = capsys.readouterr().out
        parsed = json.loads(output)
        assert "min_soc_pct" in str(parsed)

    @pytest.mark.unit
    def test_schema_unknown(self) -> None:
        ret = main(["schema", "nonexistent"])
        assert ret == 1


@pytest.mark.req("001:FR-011")
class TestCLIValidate:
    """Tests for CLI validate command."""

    @pytest.mark.unit
    def test_validate_valid_file(self, tmp_path: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]) -> None:
        manifest = {
            "type": "room",
            "device_id": "r1",
            "name": "Room",
            "floor_area_m2": 20.0,
            "safe_default": {"script": "script.safe"},
        }
        f = tmp_path / "test.json"  # type: ignore[operator]
        f.write_text(json.dumps(manifest))
        ret = main(["validate", str(f)])
        assert ret == 0
        assert "OK" in capsys.readouterr().out

    @pytest.mark.unit
    def test_validate_invalid_file(self, tmp_path: pytest.TempPathFactory) -> None:
        manifest = {"type": "room", "device_id": "r1", "name": "Room"}  # missing safe_default + floor_area
        f = tmp_path / "bad.json"  # type: ignore[operator]
        f.write_text(json.dumps(manifest))
        ret = main(["validate", str(f)])
        assert ret == 1

    @pytest.mark.unit
    def test_validate_missing_file(self) -> None:
        ret = main(["validate", "/nonexistent/path.json"])
        assert ret == 1

    @pytest.mark.unit
    def test_validate_invalid_json(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "broken.json"  # type: ignore[operator]
        f.write_text("not json{{{")
        ret = main(["validate", str(f)])
        assert ret == 1
