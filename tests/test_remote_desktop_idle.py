import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "macos" / "remote_session.py"
spec = importlib.util.spec_from_file_location("remote_session", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RemoteDesktopIdleTests(unittest.TestCase):
    def test_default_idle_timeout_is_five_minutes(self):
        self.assertEqual(module.DEFAULT_IDLE_TIMEOUT_SECONDS, 300)

    def test_low_fps_threshold_is_thirty_seconds(self):
        self.assertEqual(module.DEFAULT_IDLE_FPS_AFTER_SECONDS, 30)
        guard = module.RemoteSessionIdleGuard(timeout_seconds=300, now=1000)
        self.assertFalse(guard.should_reduce_fps(now=1029.9))
        self.assertTrue(guard.should_reduce_fps(now=1030))

    def test_only_user_input_refreshes_idle_deadline(self):
        self.assertFalse(module.is_user_activity_message("configure"))
        self.assertFalse(module.is_user_activity_message("bridge_keepalive"))
        for message_type in ("mousemove", "mousedown", "mouseup", "wheel", "keydown", "keyup", "text", "clipboard"):
            with self.subTest(message_type=message_type):
                self.assertTrue(module.is_user_activity_message(message_type))

    def test_remaining_idle_time_uses_last_user_activity(self):
        guard = module.RemoteSessionIdleGuard(timeout_seconds=300, now=1000)
        self.assertEqual(guard.remaining(now=1100), 200)
        self.assertEqual(guard.idle_for(now=1100), 100)
        guard.mark_activity(now=1100)
        self.assertEqual(guard.remaining(now=1250), 150)
        self.assertEqual(guard.remaining(now=1401), 0)

    def test_timeout_can_change_without_erasing_activity_age(self):
        guard = module.RemoteSessionIdleGuard(timeout_seconds=300, now=1000)
        guard.set_timeout(600)
        self.assertEqual(guard.remaining(now=1100), 500)
        self.assertEqual(module.clamp_idle_timeout_seconds(5), 60)
        self.assertEqual(module.clamp_idle_timeout_seconds(99999), 3600)


if __name__ == "__main__":
    unittest.main()
