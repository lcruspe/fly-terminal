"""Local Caddy integration smoke test; invoked with isolated ports by the shell runner."""
import base64
import http.client
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "macos"))
import session_auth as auth

HOST = "127.0.0.1"
ADMIN = os.environ["TERMINAL_USER"]
PASSWORD = os.environ["TERMINAL_PASSWORD"]
SPRUT = os.environ.get("FLY_SPRUTHUB_AUTH_USER", "")
PORTS = [int(os.environ[name]) for name in ("CADDY_PORT", "CADDY_TERMINAL_PORT", "CADDY_SPRUTHUB_PORT")]
PASSED = []


def request(port, path, method="GET", headers=None, body=None):
    connection = http.client.HTTPConnection(HOST, port, timeout=8)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def expect(label, condition):
    if not condition:
        raise AssertionError(label)
    PASSED.append(label)


def signed_in(port, user, password):
    basic = base64.b64encode(f"{user}:{password}".encode()).decode()
    status, headers, _ = request(port, "/auth/issue", "POST", {
        "Origin": f"http://127.0.0.1:{port}",
        "Authorization": f"Basic {basic}",
        "Content-Length": "0",
    })
    expect(f"valid Caddy credentials accepted on {port}", status == 200)
    return headers["Set-Cookie"].split(";", 1)[0]


def ready():
    for _ in range(60):
        try:
            if request(PORTS[0], "/auth/login")[0] == 200:
                return
        except (ConnectionError, OSError):
            pass
        time.sleep(0.1)
    raise RuntimeError("staging Caddy not ready")


ready()
for port in PORTS:
    status, _, body = request(port, "/auth/login")
    expect(f"login page on {port}", status == 200 and b"current-password" in body)
    expect(f"no unauthenticated API on {port}",
           request(port, "/auth/session")[0] == 401)
    status, headers, _ = request(port, "/", headers={"Accept": "text/html"})
    expect(f"anonymous navigation redirected on {port}",
           status == 302 and headers.get("Location", "").startswith("/auth/login"))
    status, _, _ = request(port, "/", headers={"Authorization": "Basic bogus"})
    expect(f"legacy Basic header does not bypass revoked sessions on {port}", status == 401 or status == 302)
    expect(f"no forged auth identity on {port}",
           request(port, "/", headers={"X-Fly-Auth-User": ADMIN, "Accept": "text/html"})[0] == 302)

bad_auth = "Basic " + base64.b64encode(b"invalid-user:wrong-password").decode()
bad_status, bad_headers, _ = request(PORTS[0], "/auth/issue", "POST", {
    "Authorization": bad_auth, "Origin": f"http://127.0.0.1:{PORTS[0]}"})
expect("bad credentials denied", bad_status == 401)
expect("failed form login does not trigger native Basic Auth prompt",
       "Www-Authenticate" not in bad_headers and "WWW-Authenticate" not in bad_headers)
cookie = signed_in(PORTS[0], ADMIN, PASSWORD)
expect("fixed lifetime cookie flags", all(p in cookie for p in ("fly_session=",)))
for port in PORTS:
    status, _, _ = request(port, "/auth/session", headers={"Cookie": cookie})
    expect(f"session shared across ports: {port}", status == 200)
    status, _, _ = request(port, "/", headers={"Cookie": cookie, "Accept": "text/html"})
    expect(f"authenticated access {port}", status not in (302, 401, 403))

status, _, body = request(PORTS[0], "/gateway-control/status", headers={"Cookie": cookie})
expect("gateway control accepts admin cookie", status == 200)
if status == 200:
    csrf = json.loads(body)["csrf"]
    port = PORTS[0]
    status, _, _ = request(port, "/gateway-control/action", "POST",
                          {"Cookie": cookie, "Origin": f"http://127.0.0.1:{port}",
                           "Content-Type": "application/json", "X-Gateway-CSRF": csrf},
                          b'{"service":"caddy","action":"stop","confirmed":true}')
    expect("gateway cannot stop itself", status == 400)

status, _, _ = request(PORTS[1], "/desktop-stream-ws/", headers={
    "Cookie": cookie, "Connection": "Upgrade", "Upgrade": "websocket",
    "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": base64.b64encode(b"smoke-test-12345").decode(),
})
expect("authenticated WebSocket passes gateway auth", status not in (302, 401, 403))
print(f"WebSocket handshake status: {status}")
expect("anonymous WebSocket is rejected", request(PORTS[1], "/desktop-stream-ws/", headers={
    "Connection": "Upgrade", "Upgrade": "websocket", "Sec-WebSocket-Version": "13",
    "Sec-WebSocket-Key": base64.b64encode(b"smoke-test-12345").decode(),
})[0] == 401)

if SPRUT and os.environ.get("FLY_SPRUTHUB_ENABLED") == "1":
    sprut_token, _ = auth.SessionStore().create(SPRUT)
    sprut_cookie = "fly_session=" + sprut_token
    portal_status, _, portal_body = request(PORTS[0], "/", headers={"Cookie": sprut_cookie})
    expect("Sprut user sees restricted portal",
           portal_status == 200 and b"data-dashboard" not in portal_body
           and "Для этой учётной записи".encode() in portal_body)
    expect("Sprut user cannot use terminal", request(PORTS[1], "/", headers={"Cookie": sprut_cookie})[0] == 403)
    expect("Sprut user cannot use gateway controls",
           request(PORTS[0], "/gateway-control/status", headers={"Cookie": sprut_cookie})[0] == 403)
    expect("Sprut user can use Sprut port",
           request(PORTS[2], "/", headers={"Cookie": sprut_cookie})[0] not in (401, 403, 302))
    port = PORTS[0]
    expect("Sprut user cannot revoke all",
           request(port, "/auth/revoke-all", "POST",
                   {"Cookie": sprut_cookie, "Origin": f"http://127.0.0.1:{port}"})[0] == 403)

port = PORTS[0]
status, _, _ = request(port, "/auth/revoke-all", "POST", {
    "Cookie": cookie, "Origin": f"http://127.0.0.1:{port}"
})
expect("admin can revoke all", status == 200)
expect("YT bootstrap remains gated by a session",
       request(PORTS[0], "/yt-login", headers={"Accept": "text/html"})[0] == 302)
expect("unprotected mail integration preserved",
       request(PORTS[0], "/livez")[0] not in (302, 401))
for p in PORTS:
    expect(f"revocation immediate on {p}",
           request(p, "/auth/session", headers={"Cookie": cookie})[0] == 401)

print(f"PASS: {len(PASSED)} staging authorization/proxy checks")
