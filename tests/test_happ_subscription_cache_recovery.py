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
    def setUp(self):
        module.HAPP_SUBSCRIPTION_REFRESH_CACHE.clear()

    def make_cache(self, root, entries):
        cache_dir = root / "fsCachedData"
        cache_dir.mkdir()
        cache_db = root / "Cache.db"
        with sqlite3.connect(cache_db) as connection:
            connection.executescript("""
                CREATE TABLE cfurl_cache_response(entry_ID INTEGER PRIMARY KEY, request_key TEXT, time_stamp TEXT);
                CREATE TABLE cfurl_cache_receiver_data(entry_ID INTEGER PRIMARY KEY, isDataOnFS INTEGER, receiver_data BLOB);
                CREATE TABLE cfurl_cache_blob_data(entry_ID INTEGER PRIMARY KEY, response_object BLOB, request_object BLOB);
            """)
            for entry_id, body in enumerate(entries, 1):
                connection.execute("INSERT INTO cfurl_cache_response VALUES (?, ?, ?)",
                                   (entry_id, f"https://provider.example/sub/{entry_id}", str(entry_id)))
                if body is not None:
                    connection.execute("INSERT INTO cfurl_cache_receiver_data VALUES (?, 0, ?)", (entry_id, body))
                connection.execute("INSERT INTO cfurl_cache_blob_data VALUES (?, ?, ?)",
                                   (entry_id, plistlib.dumps({"profile-title": f"VPN {entry_id}"}),
                                    plistlib.dumps({"User-Agent": "Happ/test"})))
        return cache_dir, cache_db

    def test_includes_subscription_without_receiver_row_and_orphan_file(self):
        cached = json.dumps([{"remarks": "Cached", "outbounds": [{}]}]).encode()
        recovered = json.dumps([{"remarks": "Recovered", "outbounds": [{}]}]).encode()
        orphan = json.dumps([{"remarks": "Orphan", "outbounds": [{}]}]).encode()
        with tempfile.TemporaryDirectory() as temp:
            cache_dir, cache_db = self.make_cache(Path(temp), [cached, None])
            (cache_dir / "orphan").write_bytes(orphan)
            (cache_dir / "duplicate").write_bytes(cached)
            with patch.object(module, "HAPP_CACHE_DIR", cache_dir), \
                 patch.object(module, "HAPP_CACHE_DB", cache_db), \
                 patch.object(module, "urlopen", return_value=FakeResponse(recovered)):
                subscriptions = module.happ_subscriptions()
        self.assertEqual(len(subscriptions), 3)
        self.assertEqual({loc["label"] for sub in subscriptions for loc in sub["locations"]},
                         {"Cached", "Recovered", "Orphan"})

    def test_force_refresh_replaces_existing_body_and_bypasses_memory_cache(self):
        old = json.dumps([{"remarks": "Old", "outbounds": [{}]}]).encode()
        fresh = json.dumps([{"remarks": name, "outbounds": [{}]} for name in ("New", "Extra")]).encode()
        with tempfile.TemporaryDirectory() as temp:
            cache_dir, cache_db = self.make_cache(Path(temp), [old])
            with patch.object(module, "HAPP_CACHE_DIR", cache_dir), \
                 patch.object(module, "HAPP_CACHE_DB", cache_db), \
                 patch.object(module, "urlopen", side_effect=[FakeResponse(old), FakeResponse(fresh)]) as fetch:
                module._happ_refresh_subscription_body("https://provider.example/sub/1", plistlib.dumps({"User-Agent": "Happ/test"}))
                subscriptions = module.happ_subscriptions(force_refresh=True)
                self.assertEqual(module.happ_subscriptions(), subscriptions)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual([loc["label"] for loc in subscriptions[0]["locations"]], ["New", "Extra"])

    def test_refresh_failure_keeps_cached_locations_and_empty_subscription(self):
        old = json.dumps([{"remarks": "Old", "outbounds": [{}]}]).encode()
        with tempfile.TemporaryDirectory() as temp:
            cache_dir, cache_db = self.make_cache(Path(temp), [old, None])
            with patch.object(module, "HAPP_CACHE_DIR", cache_dir), \
                 patch.object(module, "HAPP_CACHE_DB", cache_db), \
                 patch.object(module, "urlopen", side_effect=OSError("offline")):
                subscriptions = module.happ_subscriptions(force_refresh=True)
        self.assertEqual(len(subscriptions), 2)
        self.assertEqual(subscriptions[0]["locations"], [])
        self.assertEqual(subscriptions[1]["locations"][0]["label"], "Old")

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
