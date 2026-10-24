#!/usr/bin/env python3
"""Admin-only gateway service controls. The terminal has deliberately no actions."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

HOME = Path.home()
DOMAIN = f"gui/{os.getuid()}"
CSRF = secrets.token_urlsafe(32)
GROUPS = {
    "native": ("ai.kruspe.fly-terminal.native-browser", "ai.kruspe.fly-terminal.native-browser-streamer", "ai.kruspe.fly-terminal.native-browser-webrtc"),
    "roomaudio": ("com.kruspe.roomaudio",),
    "yt": ("com.kruspe.yttranscriber",),
    "spruthub": ("ai.kruspe.fly-terminal.spruthub",),
}
ACTIONS = {key: ("start", "stop", "restart") for key in (*GROUPS, "fallback")}
ACTIONS["openwrt"] = ("vpn-connect", "vpn-disconnect")
LOCKS = {key: threading.Lock() for key in ACTIONS}


def run(args, timeout=35, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if check and result.returncode:
        logging.warning("Command failed: %s (code %s)", args[0], result.returncode)
        raise RuntimeError("Команда не выполнена. Проверьте доступность сервиса и журнал gateway-control.")
    return result


def loaded(label):
    return run(["/bin/launchctl", "print", f"{DOMAIN}/{label}"], check=False).returncode == 0


def agent(label, action):
    plist = HOME / "Library/LaunchAgents" / f"{label}.plist"
    if not plist.is_file():
        raise RuntimeError("Служба не установлена на этом Mac.")
    if action == "stop":
        if loaded(label):
            run(["/bin/launchctl", "bootout", f"{DOMAIN}/{label}"])
    elif loaded(label):
        run(["/bin/launchctl", "kickstart", f"{DOMAIN}/{label}"])
    else:
        run(["/bin/launchctl", "bootstrap", DOMAIN, str(plist)])


def router(command):
    host = os.environ.get("FLY_OPENWRT_SSH_HOST", "openwrt-pi")
    return run(["/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "-o", "StrictHostKeyChecking=yes", host,
                f"/usr/libexec/amnezia-vpn {command}"], timeout=65 if command == "connect" else 10)


def execute(service, action):
    if service not in ACTIONS or action not in ACTIONS[service]:
        raise ValueError("Действие недоступно. Управление остановкой терминала запрещено.")
    if service == "openwrt":
        result = router("connect" if action == "vpn-connect" else "disconnect")
        data = json.loads(result.stdout)
        if action == "vpn-connect" and not data.get("runtime", {}).get("connected"):
            raise RuntimeError("VPN не подключился.")
        return
    if service == "fallback":
        label = "ai.kruspe.fly-terminal.browser"
        container = os.environ.get("FLY_BROWSER_CONTAINER_NAME", "fly-terminal-browser")
        if action in ("stop", "restart"):
            agent(label, "stop")
            run(["docker", "stop", "--time", "10", container])
        if action in ("start", "restart"):
            run(["docker", "start", container])
            agent(label, "start")
        return
    labels = GROUPS[service]
    if action in ("stop", "restart"):
        for label in reversed(labels):
            agent(label, "stop")
    if action in ("start", "restart"):
        for label in labels:
            agent(label, "start")


def local_status():
    try:
        port = int(os.environ.get("FLY_TERMINAL_CONTROL_PORT", "7683"))
        with urlopen(f"http://127.0.0.1:{port}/api/gateway/status", timeout=5) as response:
            return json.load(response).get("services", {})
    except (OSError, ValueError):
        return {}


def router_status():
    try:
        result = router("status")
        data = json.loads(result.stdout)
        return {"reachable": True, "connected": bool(data.get("runtime", {}).get("connected")),
                "location": data.get("state", {}).get("name", "")}
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError):
        return {"reachable": False, "connected": False, "location": ""}


def status():
    with ThreadPoolExecutor(max_workers=2) as pool:
        services = pool.submit(local_status)
        openwrt = pool.submit(router_status)
        result = {"services": services.result(), "openwrt": openwrt.result()}
    result.update(ok=True, csrf=CSRF, actions=ACTIONS,
                  busy=[key for key, lock in LOCKS.items() if lock.locked()])
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Never log request bodies, credentials or arbitrary URLs.
        logging.info("HTTP %s", args[1] if len(args) > 1 else "request")

    def reply(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def authenticated(self):
        user, password = os.environ.get("TERMINAL_USER", ""), os.environ.get("TERMINAL_PASSWORD", "")
        expected = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        return bool(user and password) and hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected.encode())

    def do_GET(self):
        if not self.authenticated():
            self.reply(401, {"ok": False, "error": "Требуется учётная запись администратора."})
        elif self.path == "/gateway-control/status":
            self.reply(200, status())
        else:
            self.reply(404, {"ok": False, "error": "Не найдено"})

    def do_POST(self):
        if not self.authenticated():
            self.reply(401, {"ok": False, "error": "Требуется учётная запись администратора."})
            return
        origin = urlsplit(self.headers.get("Origin", ""))
        if (origin.scheme not in ("http", "https") or origin.netloc != self.headers.get("Host") or
                not hmac.compare_digest(self.headers.get("X-Gateway-CSRF", "").encode(), CSRF.encode()) or
                self.headers.get("Content-Type", "").split(";")[0] != "application/json"):
            self.reply(403, {"ok": False, "error": "Запрос отклонён. Обновите страницу."})
            return
        if self.path != "/gateway-control/action":
            self.reply(404, {"ok": False, "error": "Не найдено"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 1024:
                raise ValueError("Неверный размер запроса")
            data = json.loads(self.rfile.read(size))
            service, action = data.get("service"), data.get("action")
            if not isinstance(service, str) or not isinstance(action, str) or action not in ACTIONS.get(service, ()):
                raise ValueError("Действие недоступно")
            if action in ("stop", "restart", "vpn-disconnect") and data.get("confirmed") is not True:
                raise ValueError("Требуется подтверждение")
        except (ValueError, AttributeError, TypeError):
            self.reply(400, {"ok": False, "error": "Недопустимое или неподтверждённое действие."})
            return
        lock = LOCKS[service]
        if not lock.acquire(blocking=False):
            self.reply(409, {"ok": False, "error": "Для этого сервиса уже выполняется команда."})
            return
        try:
            execute(service, action)
            logging.info("Action completed: %s %s", service, action)
            self.reply(200, {"ok": True, "message": "Команда выполнена. Доступность сервиса проверяется отдельно."})
        except (RuntimeError, OSError, subprocess.SubprocessError, ValueError):
            logging.exception("Action failed: %s %s", service, action)
            self.reply(502, {"ok": False, "error": "Команда не выполнена. Проверьте сервис или повторите позже."})
        finally:
            lock.release()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("FLY_GATEWAY_CONTROL_PORT", "7684"))), Handler).serve_forever()
