from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.branding_audit import audit_path


class BrandingAuditTests(unittest.TestCase):
    def test_accepts_hemm_identifiers_and_external_entities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            component = root / "ha-hemm" / "custom_components" / "hemm"
            examples = component / "examples"
            examples.mkdir(parents=True)
            (component / "manifest.json").write_text('{"domain": "hemm"}\n', encoding="utf-8")
            (component / "const.py").write_text(
                'DOMAIN = "hemm"\nEVENT_READY = f"{DOMAIN}_ready"\n',
                encoding="utf-8",
            )
            (component / "sensor.py").write_text(
                'self._attr_unique_id = f"{DOMAIN}_device_plan"\n'
                'self._attr_unique_id = f"{entry.entry_id}_{device_id}_plan"\n',
                encoding="utf-8",
            )
            (examples / "ok.yaml").write_text(
                "- id: hemm_example\n  trigger:\n    entity_id: binary_sensor.ev_plugged_in\n",
                encoding="utf-8",
            )

            self.assertEqual(audit_path(root), [])

    def test_reports_branding_and_generated_identifier_violations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            component = root / "ha-hemm" / "custom_components" / "bad"
            examples = root / "ha-hemm" / "custom_components" / "hemm" / "examples"
            component.mkdir(parents=True)
            examples.mkdir(parents=True)
            (component / "manifest.json").write_text(
                '{"domain": "bad", "documentation": "https://github.com/swifty99/ha-hemm"}\n',
                encoding="utf-8",
            )
            (component / "const.py").write_text(
                'DOMAIN = "bad"\nEVENT_READY = "ready"\nOWNER = "@hemm-energy"\n',
                encoding="utf-8",
            )
            (component / "sensor.py").write_text(
                'self._attr_unique_id = f"{device_id}_plan"\n',
                encoding="utf-8",
            )
            (examples / "bad.yaml").write_text("- id: plain_example\n", encoding="utf-8")
            (root / "README.md").write_text(
                "https://github.com/hemm-energy/ha-hemm hactl_companion\n",
                encoding="utf-8",
            )

            codes = {finding.code for finding in audit_path(root)}
            self.assertIn("forbidden-brand", codes)
            self.assertIn("custom-component-domain", codes)
            self.assertIn("manifest-domain", codes)
            self.assertIn("const-domain", codes)
            self.assertIn("event-prefix", codes)
            self.assertIn("unique-id-prefix", codes)
            self.assertIn("automation-id-prefix", codes)


if __name__ == "__main__":
    unittest.main()
