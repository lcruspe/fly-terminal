#!/usr/bin/env python3
"""Validate the real Oracle HTTPS relay without leaking credentials or touching user sessions.

Requires TERMINAL_USER and TERMINAL_PASSWORD in the environment.
Creates and logs out ONLY its own fresh admin session.
"""
import base64
import http.client
import json
import os
import ssl
from urllib.parse import urlsplit

HOSTNAME = "129-158-49-130.sslip.io"
BASES = (f"https://{HOSTNAME}", f"https://{HOSTNAME}:8443",
         f"https://{HOSTNAME}:10000")
USERNAME = os.environ["TERMINAL_USER"]
PASSWORD = os.environ["TERMINAL_PASSWORD"]
COUNT = 0


def request(url, path, method="GET", headers=None, body=None):
    parsed = urlsplit(url)
    conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=12,
                                       context=ssl.create_default_context())
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    result = resp.status, dict(resp.getheaders()), resp.read()
    conn.close()
    return result


def check(label, predicate):
    global COUNT
    if not predicate:
        raise AssertionError(label)
    COUNT += 1


def main():
    base = BASES[0]
    auth = base64.b64encode((USERNAME + ":" + PASSWORD).encode()).decode()
    status, headers, body = request(base, "/auth/issue", "POST", {
        "Origin": base,
        "Authorization": "Basic " + auth,
        "Content-Length": "0",
    })
    check("admin login with real password", status == 200)
    cookie = headers.get("Set-Cookie", "").split(";", 1)[0]
    check("session cookie with expiry", cookie.startswith("fly_session=")
          and "Max-Age=2592000" in headers.get("Set-Cookie", ""))

    try:
        for url in BASES:
            status, _, body = request(url, "/auth/session", headers={"Cookie": cookie})
            check(f"cookie valid on {url}", status == 200 and json.loads(body)["is_admin"])
            status, _, _ = request(url, "/", headers={"Cookie": cookie, "Accept": "text/html"})
            check(f"authenticated homepage on {url}", status not in (302, 401, 403))

        status, _, body = request(base, "/gateway-control/status", headers={"Cookie": cookie})
        check("admin gateway controls", status == 200 and json.loads(body)["ok"])

        ws_key = base64.b64encode(b"live-auth-smoke!").decode()
        status, _, _ = request(BASES[1], "/desktop-stream-ws/", headers={
            "Cookie": cookie, "Connection": "Upgrade", "Upgrade": "websocket",
            "Sec-WebSocket-Key": ws_key, "Sec-WebSocket-Version": "13",
        })
        check("live Oracle WebSocket handshake", status == 101)
    finally:
        status, _, _ = request(base, "/auth/logout", "POST", {
            "Cookie": cookie, "Origin": base, "Content-Length": "0",
        })
        check("logout of smoke-test session", status == 200)
    for url in BASES:
        status, _, _ = request(url, "/auth/session", headers={"Cookie": cookie})
        check("revocation effective on " + url, status == 401)
    print(f"PASS: {COUNT} live Oracle HTTPS authentication checks")


if __name__ == "__main__":
    main()
