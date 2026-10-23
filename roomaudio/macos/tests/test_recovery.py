import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "macos"))
sys.path.insert(0, str(ROOT / "windows"))
import recording_settings
from live_relay import LiveHub
from client_transport import ClientTransport


class RecoveryTests(unittest.TestCase):
    def manager_module(self):
        config = json.dumps({"server": "http://primary", "ingest_key": "test"})
        with patch.object(Path, "read_text", return_value=config), patch("logging.basicConfig"):
            spec = importlib.util.spec_from_file_location("test_capture_manager", ROOT / "windows/capture_manager.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return module

    def test_request_survives_mode_updates_and_needs_fresh_ack(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(
            recording_settings, "PATH", Path(folder) / "settings.json"
        ), patch.dict(recording_settings.STATE, recovery_ack=None, last_seen=None):
            recording_settings.set_mode("voice")
            token, created = recording_settings.request_recovery()
            self.assertTrue(created)
            self.assertEqual(recording_settings.mode(), "voice")
            self.assertEqual(recording_settings.request_recovery(), (token, False))
            recording_settings.set_mode("off")
            self.assertEqual(recording_settings.status()["recovery_id"], token)
            self.assertIsNone(recording_settings.status()["recovery_ack"])
            recording_settings.heartbeat("off", recovery_ack=token)
            self.assertEqual(recording_settings.status()["recovery_ack"], token)
            self.assertEqual(recording_settings.mode(), "off")
            with patch("recording_settings.time.time", return_value=1e12):
                self.assertIsNone(recording_settings.status()["recovery_ack"])

    def test_relay_reset_removes_stale_audio_and_closes_old_reader(self):
        hub = LiveHub()
        hub.ingest_packet("a" * 32, 0, b"old")
        generation, sequence = hub.subscribe()
        hub.reset()
        self.assertEqual(hub.status()["buffer_bytes"], 0)
        self.assertFalse(hub.status()["online"])
        self.assertIsNone(hub.read(generation, sequence, wait=0))
        self.assertFalse(hub.ingest_packet("a" * 32, 1, b"stale"))
        self.assertTrue(hub.ingest_packet("b" * 32, 0, b"fresh"))

    def test_dns_failure_uses_configured_fallback_and_remembers_it(self):
        client = ClientTransport({"server": "http://unresolved.local:8766",
                                  "server_fallbacks": ["http://192.0.2.10:8766"]})
        response = MagicMock()
        with patch.object(client.http, "open", side_effect=[URLError("DNS"), response, response]) as call:
            self.assertIs(client.open("/client/recording-mode"), response)
            self.assertEqual(client.current, "http://192.0.2.10:8766")
            client.open("/ingest/live", data=b"mp3", method="POST")
            self.assertEqual(call.call_args.args[0].full_url, "http://192.0.2.10:8766/ingest/live")
            self.assertEqual(call.call_count, 3)

    def test_http_rejection_does_not_replay_credentials_to_fallback(self):
        client = ClientTransport({"server": "http://primary", "server_fallbacks": ["http://backup"]})
        with patch.object(client.http, "open", side_effect=HTTPError("http://primary", 403, "no", {}, None)) as call:
            with self.assertRaises(HTTPError):
                client.open("/ingest/live", data=b"mp3", method="POST")
            self.assertEqual(call.call_count, 1)

    def test_manager_acknowledges_only_after_successful_restart(self):
        manager_module = self.manager_module()
        manager = manager_module.Manager()
        manager.active = "voice"
        manager.recovery_id = "old"
        with patch.object(manager, "poll", side_effect=[("voice", "new"), KeyboardInterrupt]), \
             patch.object(manager, "start") as start, patch.object(manager, "stop"), \
             patch.object(manager_module.time, "sleep"):
            with self.assertRaises(KeyboardInterrupt):
                manager.loop()
            start.assert_called_once_with("voice")
            self.assertEqual(manager.recovery_id, "new")

    def test_failed_restart_does_not_acknowledge_command(self):
        module = self.manager_module()
        manager = module.Manager()
        manager.recovery_id = "old"
        with patch.object(manager, "poll", side_effect=[("voice", "new"), KeyboardInterrupt]), \
             patch.object(manager, "start", side_effect=OSError("Cannot start capture")), \
             patch.object(manager, "stop"), patch.object(module.time, "sleep"), \
             patch.object(module.logging, "error"):
            with self.assertRaises(KeyboardInterrupt):
                manager.loop()
            self.assertEqual(manager.recovery_id, "old")

    def test_off_mode_never_opens_microphone_on_restart(self):
        module = self.manager_module()
        manager = module.Manager()
        with patch.object(manager, "stop") as stop, patch.object(module.subprocess, "Popen") as spawn:
            manager.start("off")
            stop.assert_called_once()
            spawn.assert_not_called()
            self.assertEqual(manager.active, "off")


if __name__ == "__main__":
    unittest.main()
