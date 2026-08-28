import unittest
from pathlib import Path

UI_JS = (Path(__file__).resolve().parents[1] / "vendor" / "novnc" / "app" / "ui.js").read_text(encoding="utf-8")


class NoVncIdleTimeoutTests(unittest.TestCase):
    def test_novnc_disconnects_after_five_minutes_of_no_user_input(self):
        self.assertIn("REMOTE_DESKTOP_IDLE_TIMEOUT_MS = 300000", UI_JS)
        self.assertIn("armRemoteDesktopIdleTimeout", UI_JS)
        self.assertIn("noteRemoteDesktopActivity", UI_JS)
        self.assertIn("UI.disconnect();", UI_JS)


if __name__ == "__main__":
    unittest.main()
