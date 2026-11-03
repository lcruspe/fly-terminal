import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "session-control.py"
spec = importlib.util.spec_from_file_location("session_control_native_preferences", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NativePreferencesTests(unittest.TestCase):
    def test_native_profiles_are_validated_independently(self):
        normalized = module.normalize_ui_preferences({
            "nativeDesktopQualityMode": "text",
            "nativeBrowserQualityMode": "smooth",
            "nativeDesktopIdleTimeoutSeconds": 900,
            "nativeBrowserIdleTimeoutSeconds": 300,
            "nativeDesktopHudPinned": True,
            "nativeBrowserHudPinned": False,
            "nativeDesktopHudPosition": {"x": 120, "y": 200},
            "nativeBrowserHudPosition": {"x": 16.5, "y": 30},
            "nativeBrowserResolution": "1600x900",
            "nativeBrowserFps": 45,
            "nativeBrowserScaleMode": "fill",
            "desktopResolution": "2560x1440",
            "desktopFps": 60,
        })
        self.assertEqual(normalized["nativeDesktopQualityMode"], "text")
        self.assertEqual(normalized["nativeBrowserQualityMode"], "smooth")
        self.assertEqual(normalized["nativeDesktopIdleTimeoutSeconds"], 900)
        self.assertEqual(normalized["nativeBrowserIdleTimeoutSeconds"], 300)
        self.assertTrue(normalized["nativeDesktopHudPinned"])
        self.assertFalse(normalized["nativeBrowserHudPinned"])
        self.assertEqual(normalized["nativeDesktopHudPosition"], {"x": 120.0, "y": 200.0})
        self.assertEqual(normalized["nativeBrowserHudPosition"], {"x": 16.5, "y": 30.0})
        self.assertEqual(normalized["nativeBrowserResolution"], "1600x900")
        self.assertEqual(normalized["nativeBrowserFps"], 45)
        self.assertEqual(normalized["nativeBrowserScaleMode"], "fill")
        self.assertEqual(normalized["desktopResolution"], "2560x1440")

    def test_invalid_native_inputs_cannot_be_stored(self):
        malformed = module.normalize_ui_preferences({
            "nativeDesktopQualityMode": "<script>",
            "nativeBrowserQualityMode": "unknown",
            "nativeDesktopIdleTimeoutSeconds": 99999,
            "nativeBrowserIdleTimeoutSeconds": -10,
            "nativeDesktopHudPinned": "yes",
            "nativeBrowserHudPinned": 1,
            "nativeDesktopHudPosition": {"x": float("nan"), "y": 100},
            "nativeBrowserHudPosition": {"x": -5, "y": 250},
            "nativeBrowserResolution": "9999x9999",
            "nativeBrowserFps": 999,
            "nativeBrowserScaleMode": "center",
        })
        self.assertEqual(malformed, {})

    def test_partial_updates_survive_new_sessions_and_browser_cache_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.json"
            with patch.object(module, "UI_PREFERENCES_FILE", path):
                # The normal terminal UI has already saved its preferences.
                module.write_ui_preferences(module.normalize_ui_preferences({
                    "theme": "graphite", "desktopFps": 30, "desktopResolution": "1600x900"
                }))
                # Native client writes just its changed fields.
                module.write_ui_preferences(module.normalize_ui_preferences({
                    "nativeDesktopQualityMode": "smooth",
                    "nativeDesktopHudPinned": True,
                    "nativeDesktopIdleTimeoutSeconds": 1800
                }))
                # Another device changes resolution; unrelated fields remain intact.
                module.write_ui_preferences(module.normalize_ui_preferences({
                    "desktopResolution": "2560x1440",
                    "nativeBrowserQualityMode": "text"
                }))
                # Fresh reader has no dependency on localStorage.
                current = module.read_ui_preferences()
                self.assertEqual(current["theme"], "graphite")
                self.assertEqual(current["desktopFps"], 30)
                self.assertEqual(current["desktopResolution"], "2560x1440")
                self.assertEqual(current["nativeDesktopQualityMode"], "smooth")
                self.assertEqual(current["nativeDesktopIdleTimeoutSeconds"], 1800)
                self.assertTrue(current["nativeDesktopHudPinned"])
                self.assertEqual(current["nativeBrowserQualityMode"], "text")
                self.assertEqual(json.loads(path.read_text())["nativeBrowserQualityMode"], "text")


if __name__ == "__main__":
    unittest.main()
