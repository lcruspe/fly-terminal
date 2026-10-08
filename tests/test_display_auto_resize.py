import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "session-control.py"
spec = importlib.util.spec_from_file_location("session_control", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DisplayAutoResizeTests(unittest.TestCase):
    def test_auto_resize_preference_is_boolean(self):
        self.assertTrue(module.normalize_ui_preferences({"desktopAutoResize": True})["desktopAutoResize"])
        self.assertNotIn("desktopAutoResize", module.normalize_ui_preferences({"desktopAutoResize": "true"}))

    def test_unchanged_virtual_mode_does_not_reconfigure_betterdisplay(self):
        with patch.object(module, "get_display_resolution", return_value=("1280x720", "")), patch.object(module, "betterdisplay_command") as command:
            self.assertEqual(module.set_display_resolution("virtual", "1280x720"), (True, ""))
        command.assert_not_called()

    def test_main_display_uses_nearest_supported_aspect_and_area(self):
        modes = ["1280x720", "1600x900", "1920x1080", "1024x768"]
        self.assertEqual(module.closest_display_mode("1500x850", modes), "1600x900")
        self.assertEqual(module.closest_display_mode("1100x800", modes), "1024x768")

    def test_unsafe_modes_are_excluded_from_automatic_selection(self):
        listing = "42 - 1280x720 60Hz\n144 - 720x480 60Hz Unsafe"
        with patch.object(module, "betterdisplay_command", return_value=(listing, "")):
            self.assertEqual(module.get_display_modes("main"), (["1280x720"], ""))
        self.assertEqual(module.closest_display_mode("1200x800", ["720x480", "1280x720"]), "1280x720")

    def test_unsafe_exact_mode_is_not_used(self):
        listing = "42 - 1280x720 60Hz Unsafe\n43 - 1280x720 60Hz"
        with patch.object(module, "betterdisplay_command", side_effect=[(listing, ""), ("off", ""), ("60Hz", "")]):
            self.assertEqual(module.get_display_mode_number("main", "1280x720"), ("43", ""))

    def test_main_display_uses_exact_mode_number_without_hidpi_switch(self):
        listing = "38 - 1280x720 HiDPI 60Hz\n42 - 1280x720 60Hz\n56 - 2560x1440 60Hz"
        with patch.object(module, "betterdisplay_command", side_effect=[(listing, ""), ("off", ""), ("60Hz", "")]):
            self.assertEqual(module.get_display_mode_number("main", "1280x720"), ("42", ""))

        calls = []

        def command(*arguments):
            calls.append(arguments)
            return "", ""

        with patch.object(module, "get_display_resolution", side_effect=[("2560x1440", ""), ("1280x720", "")]), patch.object(module, "get_display_mode_number", return_value=("42", "")), patch.object(module, "betterdisplay_command", side_effect=command), patch.object(module.time, "sleep"):
            self.assertEqual(module.set_display_resolution("main", "1280x720"), (True, ""))
        self.assertIn(("set", "-displayWithMainStatus", "-displayModeNumber=42"), calls)

    def test_virtual_display_accepts_custom_window_geometry(self):
        calls = []

        def command(*arguments):
            calls.append(arguments)
            return "", ""

        with patch.object(module, "get_display_resolution", side_effect=[("1280x720", ""), ("1440x900", "")]), patch.object(module, "betterdisplay_command", side_effect=command), patch.object(module.time, "sleep"):
            self.assertEqual(module.set_display_resolution("virtual", "1440x900"), (True, ""))
        self.assertTrue(any("-resolution=1440x900" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
