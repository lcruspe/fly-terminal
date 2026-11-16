"""Session store, authorization boundaries, and HTTP semantics."""
import http.client
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "macos"))
import session_auth as auth


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = auth.ADMIN_USER, auth.SPRUT_USER, auth.INTERNAL_SECRET
        auth.ADMIN_USER, auth.SPRUT_USER, auth.INTERNAL_SECRET = "admin-test", "sprut-test", "internal-test-secret"
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = auth.SessionStore(Path(cls.tmp.name) / "sessions.sqlite3")
        auth.Handler.store = cls.store
        cls.server = auth.ThreadingHTTPServer(("127.0.0.1", 0), auth.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()
        auth.ADMIN_USER, auth.SPRUT_USER, auth.INTERNAL_SECRET = cls.previous

    def setUp(self):
        self.store.revoke_all()

    def request(self, path, method="GET", headers=None, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def origin(self, **additional):
        return {"Host": f"127.0.0.1:{self.server.server_port}",
                "Origin": f"http://127.0.0.1:{self.server.server_port}", **additional}

    def test_fixed_expiration_not_renewed(self):
        token, expiry = self.store.create("admin-test", now=1000)
        self.assertEqual(expiry, 1000 + auth.DURATION)
        self.assertEqual(self.store.get(token, now=expiry - 1), ("admin-test", expiry))
        self.assertIsNone(self.store.get(token, now=expiry))
        self.assertEqual(self.store.get(token, now=1001), ("admin-test", expiry))

    def test_only_token_digest_persisted(self):
        token, _ = self.store.create("admin-test")
        with self.store._connect() as db:
            digest, username = db.execute("SELECT token_hash, username FROM sessions").fetchone()
        self.assertEqual(len(digest), 64)
        self.assertNotEqual(digest, token)
        self.assertEqual(username, "admin-test")
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)

    def test_cookie_flags_and_port_independence(self):
        token, expiry = self.store.create("sprut-test")
        header = auth.cookie_header(token, expiry)
        for required in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=2592000"):
            self.assertIn(required, header)
        self.assertNotIn("Domain=", header)
        self.assertEqual(auth.cookie_token({"Cookie": "other=ok; fly_session=" + token}), token)

    def test_login_requires_verified_caddy_and_same_origin(self):
        headers = self.origin(**{"X-Fly-Verified-User": "admin-test"})
        self.assertEqual(self.request("/auth/issue", "POST", headers)[0], 403)
        headers["X-Fly-Auth-Secret"] = "internal-test-secret"
        headers["Origin"] = "https://evil.example"
        self.assertEqual(self.request("/auth/issue", "POST", headers)[0], 403)
        headers["Origin"] = self.origin()["Origin"]
        status, response_headers, _ = self.request("/auth/issue", "POST", headers)
        self.assertEqual(status, 200)
        self.assertIn("fly_session=", response_headers["Set-Cookie"])
        self.assertIn("Max-Age=2592000", response_headers["Set-Cookie"])

    def test_admin_scope_rejects_sprut_and_spoofed_headers(self):
        token, _ = self.store.create("sprut-test")
        headers = {"Cookie": "fly_session=" + token, "X-Fly-Auth-Secret": "internal-test-secret",
                   "X-Fly-Auth-User": "admin-test"}
        self.assertEqual(self.request("/auth/check/admin", headers=headers)[0], 403)
        status, response_headers, _ = self.request("/auth/check/any", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(response_headers["X-Fly-Auth-User"], "sprut-test")
        headers["X-Fly-Auth-Secret"] = "bad"
        self.assertEqual(self.request("/auth/check/any", headers=headers)[0], 403)

    def test_no_cookie_redirects_documents_not_api_or_ws(self):
        headers = {"X-Fly-Auth-Secret": "internal-test-secret",
                   "Accept": "text/html", "X-Forwarded-Uri": "/terminal/?x=1",
                   "X-Forwarded-Method": "GET"}
        status, response_headers, _ = self.request("/auth/check/admin", headers=headers)
        self.assertEqual(status, 302)
        self.assertEqual(response_headers["Location"], "/auth/login?next=%2Fterminal%2F%3Fx%3D1")
        for extra in ({"Accept": "application/json"}, {"Upgrade": "websocket"}):
            self.assertEqual(self.request("/auth/check/admin", headers={**headers, **extra})[0], 401)

    def test_logout_single_and_admin_revoke_everyone(self):
        first, _ = self.store.create("admin-test")
        second, _ = self.store.create("sprut-test")
        headers = self.origin(**{"Cookie": "fly_session=" + second})
        self.assertEqual(self.request("/auth/revoke-all", "POST", headers)[0], 403)
        self.assertEqual(self.request("/auth/logout", "POST", headers)[0], 200)
        self.assertIsNone(self.store.get(second))
        self.assertIsNotNone(self.store.get(first))
        self.assertEqual(self.request("/auth/revoke-all", "POST",
                                      self.origin(**{"Cookie": "fly_session=" + first}))[0], 200)
        self.assertIsNone(self.store.get(first))

    def test_login_assets_and_redirect_safety(self):
        status, _, body = self.request("/auth/login")
        self.assertEqual(status, 200)
        self.assertIn(b'autocomplete="current-password"', body)
        status, headers, body = self.request("/auth/login", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertIn("Content-Length", headers)
        self.assertEqual(auth.safe_next("//another.host"), "/")
        self.assertEqual(auth.safe_next("/terminal/?x=1"), "/terminal/?x=1")


if __name__ == "__main__":
    unittest.main()
