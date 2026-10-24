import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("session_control_amnezia", ROOT / "session-control.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SELECTED = "a" * 64
SECOND = "b" * 64
CATALOG = {"profiles": [{"id": SELECTED, "label": "Main"}, {"id": SECOND, "label": "Backup"}],
           "current": "Main", "currentProfileId": SELECTED, "state": "Connected"}


class AmneziaIntegrationTests(unittest.TestCase):
    def invoke(self, payload, command=None):
        handler = object.__new__(module.SessionControlHandler)
        handler._read_json_body = lambda: (payload, None)
        with patch.object(module, "send_json") as sender, \
             patch.object(module.amnezia_ax, "command", side_effect=command or [CATALOG, {
                 **CATALOG, "current": "Backup", "currentProfileId": SECOND,
             }]) as native:
            handler._handle_amnezia_select()
            return sender.call_args.args, native.call_args_list

    def test_invalid_id_never_invokes_native_control(self):
        for invalid in [None, "", "../profile", "Z" * 64, 12]:
            with self.subTest(invalid=invalid):
                (handler, status, payload), calls = self.invoke({"profileId": invalid})
                self.assertEqual(status, 400)
                self.assertEqual(payload["error"], "amnezia_invalid_profile")
                self.assertEqual(calls, [])

    def test_unknown_id_is_rejected_before_native_switch(self):
        (handler, status, payload), calls = self.invoke({"profileId": "c" * 64}, [CATALOG])
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "amnezia_profile_not_found")
        self.assertEqual([call.args[0] for call in calls], ["list"])

    def test_valid_id_is_checked_against_fresh_catalog(self):
        (handler, status, payload), calls = self.invoke({"profileId": SECOND})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual([call.args for call in calls], [("list",), ("select", SECOND)])

    def test_backend_does_not_claim_unconfirmed_switch(self):
        (handler, status, payload), calls = self.invoke({"profileId": SECOND}, [CATALOG, CATALOG])
        self.assertEqual(status, 504)
        self.assertEqual(payload["error"], "amnezia_selection_unconfirmed")

    def test_switch_lock_blocks_second_request(self):
        self.assertTrue(module.AMNEZIA_ACTION_LOCK.acquire(blocking=False))
        try:
            (handler, status, payload), calls = self.invoke({"profileId": SECOND}, [])
            self.assertEqual(status, 409)
            self.assertEqual(payload["error"], "amnezia_action_busy")
            self.assertEqual(calls, [])
        finally:
            module.AMNEZIA_ACTION_LOCK.release()

    def test_bridge_never_returns_raw_stderr(self):
        class Proc:
            returncode = 1
            stderr = "amnezia_screen_locked /private/secret/vpn"
            stdout = ""
        with patch.object(module.amnezia_ax, "executable", return_value="/tmp/test-amnezia"), \
             patch.object(module.amnezia_ax.subprocess, "run", return_value=Proc()):
            with self.assertRaisesRegex(module.amnezia_ax.AmneziaAXError, "^amnezia_screen_locked$"):
                module.amnezia_ax.command("list")


if __name__ == "__main__":
    unittest.main()
