"""Weekly scheduler regression tests, including midnight/week boundaries."""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
import recording_settings as settings


def ts(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=settings.ZONE).timestamp()


def rule(days, start, end):
    return {"days": days, "start": start, "end": end}


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "capture_settings.json"
        p = patch.object(settings, "PATH", self.path)
        p.start()
        self.addCleanup(p.stop)
        self.path.write_text(json.dumps({"mode": "voice", "recovery_id": "old"}))

    def test_disabled_preserves_manual_recording(self):
        self.assertEqual(settings.mode(), "voice")
        self.assertFalse(settings.status()["schedule"]["enabled"])
        settings.set_schedule({"enabled": False, "mode": "continuous", "rules": []})
        self.assertEqual(settings.mode(), "voice")

    def test_workday_active_and_next_boundary(self):
        settings.set_schedule({"enabled": True, "mode": "voice",
                               "rules": [rule([0, 1, 2, 3, 4], "09:00", "18:00")]})
        data = settings._read()
        active, info = settings._schedule_state(data, ts(2026, 10, 26, 10))  # Monday
        self.assertEqual(active, "voice")
        self.assertEqual(info["next_mode"], "off")
        self.assertEqual(info["next_transition_at"], ts(2026, 10, 26, 18))
        mode, info = settings._schedule_state(data, ts(2026, 10, 26, 18))
        self.assertEqual(mode, "off")
        self.assertEqual(info["next_transition_at"], ts(2026, 10, 27, 9))
        self.assertEqual(settings._schedule_state(data, ts(2026, 10, 31, 10))[0], "off")
        self.assertEqual(settings._schedule_state(data, ts(2026, 11, 2, 9))[0], "voice")

    def test_sunday_overnight_wraps_to_monday(self):
        settings.set_schedule({"enabled": True, "mode": "continuous",
                               "rules": [rule([6], "22:00", "07:00")]})
        data = settings._read()
        for instant in [ts(2026, 11, 1, 23), ts(2026, 11, 2, 0), ts(2026, 11, 2, 6, 59)]:
            self.assertEqual(settings._schedule_state(data, instant)[0], "continuous")
        self.assertEqual(settings._schedule_state(data, ts(2026, 11, 2, 7))[0], "off")
        mode, info = settings._schedule_state(data, ts(2026, 11, 1, 23))
        self.assertEqual(info["next_transition_at"], ts(2026, 11, 2, 7))
        self.assertEqual(info["next_mode"], "off")

    def test_consecutive_intervals_do_not_create_false_transition(self):
        settings.set_schedule({"enabled": True, "mode": "voice", "rules": [
            rule([0], "09:00", "12:00"), rule([0], "12:00", "18:00")]})
        _, info = settings._schedule_state(settings._read(), ts(2026, 10, 26, 10))
        self.assertEqual(info["next_transition_at"], ts(2026, 10, 26, 18))

    def test_midnight_days_apply_to_start_day(self):
        settings.set_schedule({"enabled": True, "mode": "voice",
                               "rules": [rule([0], "22:00", "03:30")]})
        saved = settings._read()
        self.assertEqual(settings._schedule_state(saved, ts(2026, 10, 27, 3, 29))[0], "voice")
        self.assertEqual(settings._schedule_state(saved, ts(2026, 10, 27, 3, 30))[0], "off")
        self.assertEqual(settings._schedule_state(saved, ts(2026, 10, 28, 2))[0], "off")

    def test_reject_overlap_crossing_midnight_and_week(self):
        invalid = [[rule([0], "22:00", "05:00"), rule([1], "04:00", "06:00")],
                   [rule([6], "23:00", "05:00"), rule([0], "01:00", "06:00")],
                   [rule([0], "09:00", "18:00"), rule([0], "11:00", "12:00")]]
        for rules in invalid:
            with self.subTest(rules=rules), self.assertRaises(ValueError):
                settings.validate_schedule({"enabled": True, "mode": "voice", "rules": rules})

    def test_validation_rejects_bad_days_and_times(self):
        for bad in [rule([], "09:00", "17:00"), rule([7], "09:00", "17:00"),
                    rule([False], "09:00", "17:00"), rule([0, 0], "09:00", "17:00"),
                    rule([0], "9:00", "17:00"), rule([0], "00:00", "00:00")]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                settings.validate_schedule({"enabled": True, "mode": "voice", "rules": [bad]})
        with self.assertRaises(ValueError):
            settings.validate_schedule({"enabled": True, "mode": "voice", "rules": []})

    def test_manual_mode_disables_schedule_preserving_saved_rules(self):
        rules = [rule([1, 2], "09:00", "18:00")]
        settings.set_schedule({"enabled": True, "mode": "continuous", "rules": rules})
        settings.set_mode("off")
        self.assertEqual(settings.mode(), "off")
        self.assertFalse(settings.status()["schedule"]["enabled"])
        self.assertEqual(settings.status()["schedule"]["rules"], rules)
        self.assertEqual(settings._read()["recovery_id"], "old")

    def test_schedule_survives_restart_and_does_not_change_fallback(self):
        settings.set_schedule({"enabled": True, "mode": "voice",
                               "rules": [rule([0, 1, 2], "08:30", "21:15")]})
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["mode"], "voice")
        self.assertEqual(saved["recovery_id"], "old")
        self.assertTrue(saved["schedule_enabled"])
        self.assertEqual(saved["schedule_rules"][0]["start"], "08:30")


if __name__ == "__main__":
    unittest.main()
