import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "session-control.py"
spec = importlib.util.spec_from_file_location("session_control_happ_native", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HappNativeSelectionTests(unittest.TestCase):
    def test_maps_current_subscription_locations_to_native_happ_ids(self):
        configs = [
            {"remarks": "DE", "outbounds": [{}]},
            {"remarks": "GRPC", "outbounds": [{"protocol": "vless"}]},
            {"remarks": "NL", "outbounds": [{"protocol": "trojan"}]},
        ]
        subscription = {
            "id": "catalog-edge",
            "label": "Edge VPN",
            "locations": module._happ_locations_from_configs(configs),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            native_subscription = root / "SUB-EDGE"
            native_subscription.mkdir()
            native_ids = ["SERVER-DE", "SERVER-GRPC", "SERVER-NL"]
            for native_id in native_ids:
                (native_subscription / native_id).mkdir()
            mapped = module._attach_happ_native_ids(
                subscription,
                native_root=root,
                native_subscription_id="SUB-EDGE",
                native_server_id="SERVER-NL",
                current_config=configs[2],
            )
        self.assertTrue(mapped)
        self.assertEqual(subscription["nativeSubscriptionId"], "SUB-EDGE")
        self.assertEqual(
            [item["nativeServerId"] for item in subscription["locations"]],
            native_ids,
        )

    def test_native_mapping_uses_unique_current_label_when_runtime_config_differs(self):
        configs = [
            {"remarks": "DE", "outbounds": [{}]},
            {"remarks": "NL", "outbounds": [{"protocol": "trojan"}]},
        ]
        transformed_current = {
            "remarks": "NL",
            "outbounds": [{"protocol": "trojan", "settings": {"runtime": True}}],
        }
        subscription = {
            "id": "edge", "label": "Edge VPN",
            "locations": module._happ_locations_from_configs(configs),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            native = root / "SUB"
            native.mkdir()
            (native / "SERVER-DE").mkdir()
            (native / "SERVER-NL").mkdir()
            mapped = module._attach_happ_native_ids(
                subscription, root, "SUB", "SERVER-NL", transformed_current,
            )
        self.assertTrue(mapped)
        self.assertEqual(subscription["locations"][1]["nativeServerId"], "SERVER-NL")

    def test_catalog_attaches_native_ids_for_verified_current_subscription(self):
        configs = [
            {"remarks": "DE", "outbounds": [{}]},
            {"remarks": "NL", "outbounds": [{"protocol": "trojan"}]},
        ]
        subscription = {
            "id": "catalog-edge", "label": "Edge VPN",
            "locations": module._happ_locations_from_configs(configs),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            native = root / "SUB-EDGE"
            native.mkdir()
            (native / "SERVER-DE").mkdir()
            (native / "SERVER-NL").mkdir()
            native_values = {
                "XRAY_CURRENT_SUBSCRIPTION": "SUB-EDGE",
                "XRAY_CURRENT": "SERVER-NL",
            }
            with patch.object(module, "HAPP_NATIVE_SUBSCRIPTIONS_DIR", root), \
                 patch.object(module, "happ_subscriptions", return_value=[subscription]), \
                 patch.object(module, "happ_current_config", return_value=configs[1]), \
                 patch.object(module, "_read_happ_preference", side_effect=lambda key: native_values.get(key, "")):
                catalog = module.happ_subscription_catalog()
        self.assertEqual(catalog["subscriptions"][0]["nativeSubscriptionId"], "SUB-EDGE")
        self.assertEqual(catalog["subscriptions"][0]["locations"][0]["nativeServerId"], "SERVER-DE")

    def test_writes_json_and_native_ids_through_defaults_domain(self):
        location = {
            "label": "DE",
            "config": {"remarks": "DE", "outbounds": [{}]},
            "nativeServerId": "SERVER-DE",
        }
        subscription = {"nativeSubscriptionId": "SUB-EDGE"}
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch.object(module.subprocess, "run", side_effect=fake_run):
            ok, error = module._write_happ_current_config(subscription, location)
        self.assertTrue(ok, error)
        domain = str(module.HAPP_PREFERENCES.with_suffix(""))
        self.assertIn(["defaults", "write", domain, "XRAY_CURRENT", "-string", "SERVER-DE"], calls)
        self.assertIn(["defaults", "write", domain, "XRAY_CURRENT_SUBSCRIPTION", "-string", "SUB-EDGE"], calls)
        json_write = next(command for command in calls if "connectedConfigJson" in command)
        self.assertEqual(json.loads(json_write[-1])["remarks"], "DE")


if __name__ == "__main__":
    unittest.main()
