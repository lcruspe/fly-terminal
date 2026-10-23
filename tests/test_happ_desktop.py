import base64
import copy
import importlib.util
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import happ_desktop as desktop

spec = importlib.util.spec_from_file_location("session_control_desktop_test", Path(__file__).resolve().parents[1] / "session-control.py")
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


def fixture():
    return {"order": [2, 1], "map": {
        "1": {"name": "First", "inputUrl": "private-url-token", "serverOrder": [12, 11], "serverMap": {
            "11": {"guid": "a", "name": "Same", "config": "private-config"},
            "12": {"guid": "b", "name": "Same", "config": "private-config"},
            "13": {"guid": "c", "name": "Unordered", "host": "private-host"},
        }},
        "2": {"name": "Empty", "serverOrder": [], "serverMap": {}},
    }}


class DesktopCatalogTests(unittest.TestCase):
    def read(self, payload=None, preferences=None):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "preferences.plist"
            path.write_bytes(plistlib.dumps(preferences or {}))
            with patch.object(desktop, "PREFERENCES", path), patch.object(desktop, "_read_payload", return_value=payload or fixture()):
                return desktop.catalog()

    def test_all_subscriptions_and_servers_including_empty_and_duplicate_names(self):
        result = self.read()
        self.assertEqual([sub["label"] for sub in result["subscriptions"]], ["Empty", "First"])
        locations = result["subscriptions"][1]["locations"]
        self.assertEqual([loc["label"] for loc in locations], ["Same", "Same", "Unordered"])
        self.assertEqual(len({loc["id"] for loc in locations}), 3)
        self.assertFalse(result["canSwitch"])
        self.assertFalse(result["canReconnect"])
        self.assertNotIn("private-", json.dumps(result))

    def test_guids_keep_ids_stable_when_server_keys_change_and_match_selection(self):
        preferences = {"Preferences.lastSubscription": 1, "Preferences.lastServer": 999, "Preferences.lastServerGuid": "b"}
        before = self.read(preferences=preferences)
        payload = fixture()
        payload["map"]["1"]["serverMap"]["99"] = payload["map"]["1"]["serverMap"].pop("12")
        payload["map"]["1"]["serverOrder"] = [99, 11]
        after = self.read(payload, preferences)
        self.assertTrue(before["currentLocationId"])
        self.assertEqual(before["currentLocationId"], after["currentLocationId"])

    def test_stale_selection_is_not_guessed_by_name(self):
        result = self.read(preferences={"Preferences.lastSubscription": 1, "Preferences.lastServerGuid": "missing", "Preferences.lastServerName": "Same"})
        self.assertEqual(result["currentLocationId"], "")

    def test_probe_targets_are_validated_and_only_available_on_private_backend_opt_in(self):
        data = fixture()
        data["map"]["1"]["serverMap"]["11"].update(host="private.example", port="443")
        with patch.object(desktop, "_read_payload", return_value=data), patch.object(desktop, "PREFERENCES", Path("/missing.plist")):
            public = desktop.catalog()
            private = desktop.catalog(include_probe_targets=True)
        self.assertNotIn("private.example", json.dumps(public))
        location = next(loc for loc in private["subscriptions"][1]["locations"] if loc["_pingTarget"])
        self.assertEqual(location["_pingTarget"], ("private.example", 443))
        for host, port in (("example.test", "wrong"), ("example.test", 65536), ("bad host", 443), ("http://example.test", 443)):
            self.assertIsNone(desktop._ping_target({"host": host, "port": port}))

    def test_refresh_reloads_the_database_instead_of_returning_previous_catalogue(self):
        first = fixture()
        second = copy.deepcopy(first)
        second["map"]["1"]["serverMap"]["14"] = {"guid": "new", "name": "New"}
        with patch.object(desktop, "_read_payload", side_effect=[first, second]), patch.object(desktop, "PREFERENCES", Path("/missing.plist")):
            self.assertEqual(len(desktop.catalog()["subscriptions"][1]["locations"]), 3)
            self.assertEqual(len(desktop.catalog()["subscriptions"][1]["locations"]), 4)

    def test_new_reader_is_preferred_without_calling_happ_plus_accessibility(self):
        result = self.read()
        with patch.object(desktop, "available", return_value=True), patch.object(desktop, "catalog", return_value=result), patch.object(control, "happ_accessibility_catalog") as old:
            self.assertEqual(control.happ_ui_catalog(), result)
            old.assert_not_called()

    def test_http_catalogue_aliases_keep_credentials_private(self):
        handler = object.__new__(control.SessionControlHandler)
        for path in ("/api/vpn/happ/subscriptions", "/api/vpn/happ/subscriptions?refresh=1", "/api/vpn/happ/locations"):
            handler.path = path
            with patch.object(control, "happ_ui_catalog", return_value=self.read()), patch.object(control, "send_json") as send:
                handler.do_GET()
                status, payload = send.call_args.args[1:]
                self.assertEqual(status, 200)
                self.assertEqual(payload["source"], "happ-desktop")
                self.assertNotIn("private-", json.dumps(payload))

    def test_legacy_control_endpoints_do_not_act_on_happ_desktop(self):
        handler = object.__new__(control.SessionControlHandler)
        with patch.object(desktop, "available", return_value=True), patch.object(control, "send_json") as send, patch.object(control, "run_happ_vpn_command") as vpn, patch.object(control, "_happ_ax_command") as ax:
            handler._handle_happ_location()
            self.assertEqual(send.call_args.args[1], 409)
            handler._handle_happ_reconnect()
            self.assertEqual(send.call_args.args[1], 409)
            vpn.assert_not_called()
            ax.assert_not_called()

    def test_authentication_failure_is_a_public_error_not_private_details(self):
        handler = object.__new__(control.SessionControlHandler)
        handler.path = "/api/vpn/happ/subscriptions?refresh=1"
        with patch.object(control, "happ_ui_catalog", side_effect=desktop.HappDesktopError("happ_desktop_decryption_failed")), patch.object(control, "send_json") as send:
            handler.do_GET()
            self.assertEqual(send.call_args.args[1], 503)
            self.assertEqual(send.call_args.args[2]["error"], "happ_desktop_decryption_failed")


class MachOTests(unittest.TestCase):
    def test_resolves_symbols_from_segments_in_thin_and_universal_images(self):
        image = bytearray(600)
        struct.pack_into("<8I", image, 0, 0xFEEDFACF, 0x100000C, 0, 2, 2, 96, 0, 0)
        struct.pack_into("<II16sQQQQiiII", image, 32, 0x19, 72, b"__TEXT", 0x100000000, 600, 0, 600, 7, 5, 0, 0)
        struct.pack_into("<6I", image, 104, 2, 24, 128, 1, 144, 32)
        struct.pack_into("<IBBHQ", image, 128, 1, 0xF, 1, 0, 0x100000200)
        image[144:150] = b"\0test\0"
        image[512:515] = b"abc"
        fat = struct.pack(">7I", 0xCAFEBABE, 1, 0x100000C, 0, 28, len(image), 0) + image
        for binary in (bytes(image), bytes(fat)):
            self.assertEqual(desktop._symbol_bytes(binary, {b"test": 3}), {b"test": b"abc"})
        with self.assertRaises(ValueError):
            desktop._symbol_bytes(bytes(image), {b"missing": 3})


@unittest.skipUnless(sys.platform == "darwin", "CryptoKit requires macOS")
class CryptoKitTests(unittest.TestCase):
    # Public NIST AES-GCM vector: zero 128-bit key, zero 96-bit nonce,
    # 16 zero plaintext bytes. No real Happ secrets are stored in this test.
    def request(self, tag="ab6e47d42cec13bdf53a67b21257bddf"):
        return {"key": base64.b64encode(bytes(16)).decode(), "nonce": base64.b64encode(bytes(12)).decode(),
                "data": base64.b64encode(bytes.fromhex("0388dace60b6a392f328c2b971b2fe78")).decode(),
                "tag": base64.b64encode(bytes.fromhex(tag)).decode()}

    def test_decrypts_authenticated_data_and_emits_nothing_when_tag_is_wrong(self):
        helper = desktop._helper()
        valid = subprocess.run([str(helper)], input=json.dumps(self.request()).encode(), capture_output=True, timeout=10)
        self.assertEqual(valid.returncode, 0)
        self.assertEqual(valid.stdout, bytes(16))
        corrupt = subprocess.run([str(helper)], input=json.dumps(self.request("00" * 16)).encode(), capture_output=True, timeout=10)
        self.assertNotEqual(corrupt.returncode, 0)
        self.assertEqual(corrupt.stdout, b"")
        self.assertEqual(corrupt.stderr, b"")


if __name__ == "__main__":
    unittest.main()
