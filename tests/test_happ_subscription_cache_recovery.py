import importlib.util
import json
import plistlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "session-control.py"
spec = importlib.util.spec_from_file_location("session_control_happ_recovery", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit=-1):
        return self.body if limit < 0 else self.body[:limit]


class HappSubscriptionCacheRecoveryTests(unittest.TestCase):
    def test_recovers_missing_fs_cache_body_from_saved_happ_request(self):
        config = {"remarks": "NL test", "outbounds": [{}]}
        body = json.dumps([config]).encode("utf-8")
        request_object = plistlib.dumps({
            "User-Agent": "Happ/4.11.0/macos catalyst/test",
            "X-HWID": "test-hwid",
            "Accept": "*/*",
            "Accept-Language": "ru",
        })
        response_object = plistlib.dumps({"profile-title": "Edge VPN"})

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "fsCachedData"
            cache_dir.mkdir()
            cache_db = Path(temp_dir) / "Cache.db"
            connection = sqlite3.connect(cache_db)
            connection.executescript("""
                CREATE TABLE cfurl_cache_response(
                    entry_ID INTEGER PRIMARY KEY,
                    request_key TEXT,
                    time_stamp TEXT
                );
                CREATE TABLE cfurl_cache_receiver_data(
                    entry_ID INTEGER PRIMARY KEY,
                    isDataOnFS INTEGER,
                    receiver_data BLOB
                );
                CREATE TABLE cfurl_cache_blob_data(
                    entry_ID INTEGER PRIMARY KEY,
                    response_object BLOB,
                    request_object BLOB
                );
            """)
            connection.execute(
                "INSERT INTO cfurl_cache_response VALUES (?, ?, ?)",
                (1, "https://provider.example/sub/token", "2026-08-31 09:00:00"),
            )
            connection.execute(
                "INSERT INTO cfurl_cache_receiver_data VALUES (?, ?, ?)",
                (1, 1, b"MISSING-CACHE-FILE"),
            )
            connection.execute(
                "INSERT INTO cfurl_cache_blob_data VALUES (?, ?, ?)",
                (1, response_object, request_object),
            )
            connection.commit()
            connection.close()

            calls = []

            def fake_urlopen(request, timeout):
                calls.append((request, timeout))
                return FakeResponse(body)

            with patch.object(module, "HAPP_CACHE_DIR", cache_dir), \
                 patch.object(module, "HAPP_CACHE_DB", cache_db), \
                 patch.object(module, "urlopen", side_effect=fake_urlopen, create=True):
                subscriptions = module.happ_subscriptions()
                subscriptions_again = module.happ_subscriptions()

        self.assertEqual(len(subscriptions), 1)
        self.assertEqual(subscriptions_again, subscriptions)
        self.assertEqual(subscriptions[0]["label"], "Edge VPN")
        self.assertEqual([item["label"] for item in subscriptions[0]["locations"]], ["NL test"])
        self.assertEqual(len(calls), 1)
        request, timeout = calls[0]
        self.assertEqual(request.full_url, "https://provider.example/sub/token")
        self.assertEqual(request.get_header("User-agent"), "Happ/4.11.0/macos catalyst/test")
        self.assertEqual(request.get_header("X-hwid"), "test-hwid")
        self.assertLessEqual(timeout, 10)

    def test_does_not_refetch_non_subscription_cache_entries(self):
        config = {"remarks": "must not appear", "outbounds": [{}]}
        body = json.dumps([config]).encode("utf-8")
        request_object = plistlib.dumps({
            "User-Agent": "Happ/4.11.0/macos catalyst/test",
            "X-HWID": "test-hwid",
        })
        response_object = plistlib.dumps({"Content-Type": "application/json"})

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "fsCachedData"
            cache_dir.mkdir()
            cache_db = Path(temp_dir) / "Cache.db"
            connection = sqlite3.connect(cache_db)
            connection.executescript("""
                CREATE TABLE cfurl_cache_response(entry_ID INTEGER PRIMARY KEY, request_key TEXT, time_stamp TEXT);
                CREATE TABLE cfurl_cache_receiver_data(entry_ID INTEGER PRIMARY KEY, isDataOnFS INTEGER, receiver_data BLOB);
                CREATE TABLE cfurl_cache_blob_data(entry_ID INTEGER PRIMARY KEY, response_object BLOB, request_object BLOB);
            """)
            connection.execute("INSERT INTO cfurl_cache_response VALUES (?, ?, ?)", (1, "https://provider.example/api", "2026-08-31 09:00:00"))
            connection.execute("INSERT INTO cfurl_cache_receiver_data VALUES (?, ?, ?)", (1, 1, b"MISSING"))
            connection.execute("INSERT INTO cfurl_cache_blob_data VALUES (?, ?, ?)", (1, response_object, request_object))
            connection.commit()
            connection.close()

            with patch.object(module, "HAPP_CACHE_DIR", cache_dir), \
                 patch.object(module, "HAPP_CACHE_DB", cache_db), \
                 patch.object(module, "urlopen", return_value=FakeResponse(body), create=True) as urlopen_mock:
                subscriptions = module.happ_subscriptions()

        self.assertEqual(subscriptions, [])
        urlopen_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
