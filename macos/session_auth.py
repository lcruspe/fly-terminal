#!/usr/bin/env python3
"""Revocable, fixed-lifetime session store. Passwords are verified by Caddy."""
from __future__ import annotations

from contextlib import contextmanager
from email.utils import formatdate
from functools import lru_cache
from hashlib import sha256
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import quote, urlsplit

DURATION = 30 * 24 * 60 * 60
COOKIE_NAME = "fly_session"
HOME = Path.home()
DB_PATH = Path(os.environ.get("FLY_SESSION_DB", str(HOME / ".config/fly-terminal-mac/sessions.sqlite3")))
ASSETS = Path(__file__).resolve().parent / "gateway"
ADMIN_USER = os.environ.get("TERMINAL_USER", "")
SPRUT_USER = (os.environ.get("FLY_SPRUTHUB_AUTH_USER", "")
              if os.environ.get("FLY_SPRUTHUB_ENABLED", "0") == "1" else "")
INTERNAL_SECRET = os.environ.get("FLY_AUTH_SECRET", "")


def permitted_user(user):
    return bool(user and (user == ADMIN_USER or (SPRUT_USER and user == SPRUT_USER)))


def cookie_token(headers):
    try:
        jar = SimpleCookie()
        jar.load(headers.get("Cookie", ""))
        item = jar.get(COOKIE_NAME)
        token = item.value if item else ""
        if 32 <= len(token) <= 128 and all(c.isalnum() or c in "-_" for c in token):
            return token
    except Exception:
        pass
    return ""


class SessionStore:
    """Persist only SHA256 digests of unpredictable random session tokens."""

    def __init__(self, path=DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
        os.chmod(self.path, 0o600)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions ("
                       "token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, "
                       "issued INTEGER NOT NULL, expires INTEGER NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, username, now=None):
        if not permitted_user(username):
            raise ValueError("unknown user")
        now = int(time.time() if now is None else now)
        token = secrets.token_urlsafe(48)
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE expires <= ?", (now,))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                       (sha256(token.encode("ascii")).hexdigest(), username, now, now + DURATION))
        return token, now + DURATION

    def get(self, token, now=None):
        if not token:
            return None
        now = int(time.time() if now is None else now)
        with self._connect() as db:
            row = db.execute(
                "SELECT username, expires FROM sessions WHERE token_hash = ? AND expires > ?",
                (sha256(token.encode("ascii")).hexdigest(), now)).fetchone()
        return (row[0], row[1]) if row and permitted_user(row[0]) else None

    def revoke(self, token):
        if token:
            with self._connect() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?",
                           (sha256(token.encode("ascii")).hexdigest(),))

    def revoke_all(self):
        with self._connect() as db:
            db.execute("DELETE FROM sessions")



@lru_cache(maxsize=1)
def default_store():
    return SessionStore()


def session_for_request(headers, store=None):
    return (store or default_store()).get(cookie_token(headers))


def cookie_header(token, expiry):
    return (f"{COOKIE_NAME}={token}; Path=/; Max-Age={DURATION}; "
            f"Expires={formatdate(expiry, usegmt=True)}; Secure; HttpOnly; SameSite=Lax")


def expired_cookie():
    return (f"{COOKIE_NAME}=; Path=/; Max-Age=0; "
            "Expires=Thu, 01 Jan 1970 00:00:00 GMT; Secure; HttpOnly; SameSite=Lax")


def same_origin(headers):
    origin = urlsplit(headers.get("Origin", ""))
    host = headers.get("Host", "")
    return (origin.scheme in ("https", "http") and origin.netloc == host
            and bool(host) and not host.startswith("//"))


def safe_next(raw):
    if (not raw.startswith("/") or raw.startswith("//") or "\\" in raw
            or any(ord(c) < 32 for c in raw)):
        return "/"
    return raw[:2048]


class Handler(BaseHTTPRequestHandler):
    store = None

    def log_message(self, fmt, *args):
        # Never log the URL, cookie, login, request body, or Basic credentials.
        logging.info("session-auth %s %s", self.command, getattr(self, "_status", "?"))

    def respond(self, status, body=b"", typ="application/json; charset=utf-8", headers=()):
        self._status = status
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"))
        for key, value in headers:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def result(self, status, value, headers=()):
        self.respond(status, json.dumps(value, ensure_ascii=False).encode(), headers=headers)

    def verified_caddy(self):
        return bool(INTERNAL_SECRET and hmac.compare_digest(
            self.headers.get("X-Fly-Auth-Secret", ""), INTERNAL_SECRET))

    def check(self, role):
        if not self.verified_caddy():
            self.result(403, {"ok": False})
            return
        session = session_for_request(self.headers, self.store)
        if not session:
            destination = safe_next(self.headers.get("X-Forwarded-Uri", "/"))
            location = "/auth/login?next=" + quote(destination, safe="")
            wants_html = ("text/html" in self.headers.get("Accept", "")
                          and self.headers.get("X-Forwarded-Method", "GET") == "GET"
                          and self.headers.get("Upgrade", "").lower() != "websocket")
            if wants_html:
                self.respond(302, headers=(("Location", location),))
            else:
                self.result(401, {"ok": False, "error": "Authentication required"})
            return
        username, _ = session
        if role == "admin" and username != ADMIN_USER:
            self.result(403, {"ok": False, "error": "Forbidden"})
            return
        self.respond(200, headers=(("X-Fly-Auth-User", username),))

    def do_HEAD(self):
        # Link previewers and network monitors use HEAD before navigation.
        # respond() suppresses the body while preserving GET response headers.
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/auth/check/"):
            role = path.rsplit("/", 1)[-1]
            if role not in ("admin", "any"):
                self.result(404, {"ok": False})
            else:
                self.check(role)
        elif path in ("/auth/login", "/auth/login.js", "/auth/login.css", "/auth/session-ui.js"):
            filename, mime = {
                "/auth/login": ("login.html", "text/html; charset=utf-8"),
                "/auth/login.js": ("login.js", "application/javascript; charset=utf-8"),
                "/auth/login.css": ("login.css", "text/css; charset=utf-8"),
                "/auth/session-ui.js": ("session-ui.js", "application/javascript; charset=utf-8"),
            }[path]
            self.respond(200, (ASSETS / filename).read_bytes(), mime)
        elif path == "/auth/session":
            session = session_for_request(self.headers, self.store)
            if not session:
                self.result(401, {"ok": False})
            else:
                username, expiry = session
                self.result(200, {"ok": True, "user": username,
                                  "is_admin": username == ADMIN_USER,
                                  "expires_at": expiry})
        else:
            self.result(404, {"ok": False})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/auth/issue", "/auth/logout", "/auth/revoke-all"):
            self.result(404, {"ok": False})
            return
        if not same_origin(self.headers) or self.headers.get("Content-Length", "0") not in ("", "0"):
            self.result(403, {"ok": False, "error": "Origin or body rejected"})
            return
        if path == "/auth/issue":
            if not self.verified_caddy():
                self.result(403, {"ok": False})
                return
            username = self.headers.get("X-Fly-Verified-User", "")
            if not permitted_user(username):
                self.result(403, {"ok": False})
                return
            token, expiry = self.store.create(username)
            self.result(200, {"ok": True, "is_admin": username == ADMIN_USER,
                              "expires_at": expiry},
                        headers=(("Set-Cookie", cookie_header(token, expiry)),))
            return
        token = cookie_token(self.headers)
        session = self.store.get(token)
        if not session:
            self.result(401, {"ok": False})
            return
        if path == "/auth/revoke-all":
            if session[0] != ADMIN_USER:
                self.result(403, {"ok": False})
                return
            self.store.revoke_all()
        else:
            self.store.revoke(token)
        self.result(200, {"ok": True}, headers=(("Set-Cookie", expired_cookie()),))


def serve():
    if not INTERNAL_SECRET or not ADMIN_USER:
        raise SystemExit("FLY_AUTH_SECRET and TERMINAL_USER are required")
    Handler.store = SessionStore()
    port = int(os.environ.get("FLY_SESSION_AUTH_PORT", "7685"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("session-auth listening on localhost port %s", port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
