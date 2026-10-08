import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "session-control.py"
spec = importlib.util.spec_from_file_location("session_control_happ_ax", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def catalog_with_locations():
    return {
        "subscriptions": [
            {"id": "edge", "label": "Edge VPN", "locations": [
                {"id": "fr", "label": "Франция [Wi-Fi] | Gemini ✅"},
                {"id": "nl", "label": "Нидерланды [Wi-Fi]"},
            ]},
            {"id": "renewal", "label": "Продление", "locations": [
                {"id": "fr2", "label": "Франция [Wi-Fi] | Gemini ✅"},
            ]},
        ],
        "current": "",
        "currentLocationId": "",
        "currentSubscriptionId": "",
        "currentSubscription": "",
    }


class HappAccessibilityTests(unittest.TestCase):
    def test_flag_icon_omitted_by_accessibility(self):
        listing = catalog_with_locations()
        listing["subscriptions"][1]["locations"] = []
        with patch.object(module, "_happ_ax_command", return_value=listing), \
             patch.object(module, "happ_current_location", return_value="🇫🇷 Франция [Wi-Fi] | Gemini ✅"):
            result = module.happ_accessibility_catalog()
        self.assertEqual(result["currentSubscriptionId"], "edge")
        self.assertEqual(result["currentLocationId"], "fr")

    def test_duplicate_labels_cannot_be_assigned_to_wrong_subscription(self):
        with patch.object(module, "_happ_ax_command", return_value=catalog_with_locations()), \
             patch.object(module, "happ_current_location", return_value="🇫🇷 Франция [Wi-Fi] | Gemini ✅"):
            result = module.happ_accessibility_catalog()
        self.assertEqual(result["currentLocationId"], "")
        self.assertEqual(result["currentSubscriptionId"], "")

    def test_does_not_press_if_requested_location_is_already_active(self):
        listing = catalog_with_locations()
        listing.update(currentSubscriptionId="edge", currentLocationId="fr")
        selected = listing["subscriptions"][0]["locations"][0]
        with patch.object(module, "happ_current_location", return_value="🇫🇷 Франция [Wi-Fi] | Gemini ✅"), \
             patch.object(module, "happ_accessibility_catalog", return_value=listing), \
             patch.object(module, "_happ_ax_command") as native:
            success, error = module.select_happ_accessibility_location(listing["subscriptions"][0], selected)
        self.assertTrue(success, error)
        native.assert_not_called()

    def test_selection_calls_native_action_and_waits_for_confirmation(self):
        listing = catalog_with_locations()
        listing["subscriptions"][1]["locations"] = []
        listing.update(currentSubscriptionId="edge", currentLocationId="nl")
        selected = listing["subscriptions"][0]["locations"][1]
        with patch.object(module, "happ_current_location", return_value="🇫🇷 Франция [Wi-Fi] | Gemini ✅"), \
             patch.object(module, "happ_accessibility_catalog", return_value=listing), \
             patch.object(module, "_happ_ax_command", return_value={"ok": True}) as native:
            success, error = module.select_happ_accessibility_location(listing["subscriptions"][0], selected)
        self.assertTrue(success, error)
        native.assert_called_once_with("select", "edge", "nl")

    def test_native_bridge_errors_are_not_exposed_as_raw_stderr(self):
        class Result:
            returncode = 1
            stderr = "happ_accessibility_denied; private debug"
            stdout = ""
        with patch.object(module, "_happ_ax_executable", return_value="/tmp/happ-ax"), \
             patch.object(module.subprocess, "run", return_value=Result()):
            with self.assertRaisesRegex(module.HappAXError, "^happ_accessibility_denied$"):
                module._happ_ax_command("list")

    def test_locked_screen_returns_stable_error(self):
        class Result:
            returncode = 1
            stderr = 'Error Domain=happ_screen_locked Code=8'
            stdout = ""
        with patch.object(module, "_happ_ax_executable", return_value="/tmp/happ-ax"), \
             patch.object(module.subprocess, "run", return_value=Result()):
            with self.assertRaisesRegex(module.HappAXError, "^happ_screen_locked$"):
                module._happ_ax_command("list")


if __name__ == "__main__":
    unittest.main()
