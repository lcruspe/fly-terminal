#!/usr/bin/env python3
"""Public Commander Funnel smoke check without copying user credentials.

Run on Mac mini only. Create fresh short-lived test tokens in the local
session store and revoke only these tokens, leaving user sessions untouched.
"""
import base64
import http.client
import os
from pathlib import Path
import ssl
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "macos"))
from session_auth import SessionStore

HOST = "commander-hub.tail1c55c5.ts.net"
SSL = ssl.create_default_context()
TOTAL = 0


def check(message, condition):
    global TOTAL
    if not condition:
        raise AssertionError(message)
    TOTAL += 1
    print("PASS:", message)


def get(port, path, cookie=None, websocket=False):
    connection = http.client.HTTPSConnection(HOST, port, context=SSL, timeout=10)
    headers = {"Accept": "text/html"}
    if cookie:
        headers["Cookie"] = "fly_session=" + cookie
    if websocket:
        headers.update({
            "Connection": "Upgrade", "Upgrade": "websocket",
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Key": base64.b64encode(b"commander-wstest").decode(),
        })
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        status = response.status
        data = b"" if status == 101 else response.read(300)
        return status, data
    finally:
        connection.close()


def run():
    store = SessionStore()
    admin = os.environ.get("TERMINAL_USER", "")
    secondary = (os.environ.get("FLY_SPRUTHUB_AUTH_USER", "")
                 if os.environ.get("FLY_SPRUTHUB_ENABLED") == "1" else "")
    if not admin:
        raise RuntimeError("TERMINAL_USER is required")
    # Read-only checks before making a test session.
    check("public Commander Hub 443", get(443, "/")[0] == 200)
    for port in (8443, 10000):
        check(f"anonymous login on {port}", get(port, "/auth/login")[0] == 200)
        check(f"anonymous protected route on {port}", get(port, "/")[0] == 302)
    check("unauthenticated websocket rejected", get(8443, "/native-browser-stream-ws/", websocket=True)[0] == 401)

    admin_token, _ = store.create(admin)
    try:
        check("admin gateway on 8443", get(8443, "/", admin_token)[0] == 200)
        check("admin terminal via /fly/", get(8443, "/fly/", admin_token)[0] == 200)
        check("admin gateway-control", get(8443, "/gateway-control/status", admin_token)[0] == 200)
        check("admin Sprut.Hub on 10000", get(10000, "/", admin_token)[0] == 200)
        for ws_path in ("/desktop-stream-ws/", "/native-browser-stream-ws/"):
            status, detail = get(8443, ws_path, admin_token, True)
            print(f"WebSocket {ws_path}: HTTP {status}")
            check(f"authorized WebSocket upgrade {ws_path}", status == 101)
    finally:
        store.revoke(admin_token)
    check("admin test session revoked", get(10000, "/auth/session", admin_token)[0] == 401)

    if secondary:
        secondary_token, _ = store.create(secondary)
        try:
            check("Sprut user can open 10000", get(10000, "/", secondary_token)[0] == 200)
            check("Sprut user cannot open terminal", get(8443, "/fly/", secondary_token)[0] == 403)
            check("Sprut user cannot access controls", get(8443, "/gateway-control/status", secondary_token)[0] == 403)
        finally:
            store.revoke(secondary_token)

    print(f"PASS: {TOTAL} Commander Funnel public checks")


if __name__ == "__main__":
    run()
