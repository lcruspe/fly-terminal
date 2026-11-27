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
from session_auth import session_for_request
import subprocess
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

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


class ServiceTransitionError(RuntimeError):
    """An expected transition failed; the message is safe for the admin UI."""


def wait_until(predicate, timeout, message):
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ServiceTransitionError(message)
        time.sleep(min(0.25, remaining))


def agent(label, action):
    plist = HOME / "Library/LaunchAgents" / f"{label}.plist"
    if not plist.is_file():
        raise RuntimeError("Служба не установлена на этом Mac.")
    if action == "stop":
        if loaded(label):
            run(["/bin/launchctl", "bootout", f"{DOMAIN}/{label}"])
            # bootout returns before the process exits and launchd removes it.
            # kickstart during that interval can succeed without restarting it.
            wait_until(lambda: not loaded(label), 25,
                       f"Служба {label} не завершила остановку. Запуск не выполнен.")
    else:
        if loaded(label):
            run(["/bin/launchctl", "kickstart", f"{DOMAIN}/{label}"])
        else:
            run(["/bin/launchctl", "bootstrap", DOMAIN, str(plist)])
        wait_until(lambda: loaded(label), 5, f"Служба {label} не зарегистрировалась в launchd.")


def router(command):
    host = os.environ.get("FLY_OPENWRT_SSH_HOST", "openwrt-pi")
    explicit_config = os.environ.get("FLY_OPENWRT_SSH_CONFIG")
    config = (Path(explicit_config).expanduser() if explicit_config else
              HOME / ".config/fly-terminal-mac/openwrt-ssh.conf")
    args = ["/usr/bin/ssh"]
    if config.is_file():
        # OpenWrt must not depend on unrelated Includes (e.g. Colima on a removable disk).
        args.extend(["-F", str(config)])
    elif explicit_config:
        raise RuntimeError("Выделенный SSH-конфиг OpenWrt не найден.")
    args.extend(["-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "-o", "StrictHostKeyChecking=yes",
                 host, f"/usr/libexec/amnezia-vpn {command}"])
    return run(args, timeout=65 if command == "connect" else 10)


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
            wait_service_ready(service)
        return
    labels = GROUPS[service]
    if action in ("stop", "restart"):
        for label in reversed(labels):
            agent(label, "stop")
    if action in ("start", "restart"):
        for label in labels:
            agent(label, "start")
        wait_service_ready(service)


def local_status():
    try:
        port = int(os.environ.get("FLY_TERMINAL_CONTROL_PORT", "7683"))
        with urlopen(f"http://127.0.0.1:{port}/api/gateway/status", timeout=5) as response:
            return json.load(response).get("services", {})
    except (OSError, ValueError):
        return {}


def service_ready(service):
    if service == "yt":
        try:
            port = int(os.environ.get("FLY_YT_TRANSCRIBER_PORT", "8787"))
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                data = json.load(response)
                return data.get("ok") is True and data.get("service") == "yt-transcript-local"
        except (OSError, ValueError, TypeError, AttributeError):
            return False
    return local_status().get(service) == "up"


def wait_service_ready(service):
    wait_until(lambda: service_ready(service), 30,
               "Команда запуска выполнена, но сервис не подтвердил готовность. Проверьте журнал сервиса.")


def roomaudio_status():
    """Read only the local RoomAudio health; never expose its credentials."""
    try:
        config_path = HOME / "Library/Application Support/RoomAudio/config.json"
        config = json.loads(config_path.read_text())
        token = base64.b64encode(f"{config['username']}:{config['password']}".encode()).decode()
        port = int(config.get("port", 8766))
        request = Request(f"http://127.0.0.1:{port}/api/status",
                          headers={"Authorization": "Basic " + token})
        with urlopen(request, timeout=4) as response:
            data = json.load(response)
        online = data.get("source_online")
        source = "up" if online is True else "down" if online is False else "unknown"
        return {"roomaudio": "up", "roomaudio_source": source}
    except (OSError, ValueError, KeyError, TypeError):
        return {"roomaudio_source": "unknown"}


def router_status():
    try:
        result = router("status")
        data = json.loads(result.stdout)
        return {"reachable": True, "connected": bool(data.get("runtime", {}).get("connected")),
                "location": data.get("state", {}).get("name", "")}
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
        logging.warning("OpenWrt status check failed: %s", type(error).__name__)
        return {"reachable": False, "connected": False, "location": ""}


def status():
    with ThreadPoolExecutor(max_workers=3) as pool:
        services = pool.submit(local_status)
        openwrt = pool.submit(router_status)
        roomaudio = pool.submit(roomaudio_status)
        result = {"services": services.result(), "openwrt": openwrt.result()}
    result["services"].update(roomaudio.result())
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
        if bool(user and password) and hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected.encode()):
            return True
        # The gateway already checked the cookie; repeat verification here to
        # protect the control API even against direct loopback access.
        session = session_for_request(self.headers)
        return bool(session and session[0] == user)

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
            message = ("Сервис запущен. Проверка доступности пройдена."
                       if service != "openwrt" and action in ("start", "restart")
                       else "Команда выполнена.")
            self.reply(200, {"ok": True, "message": message})
        except ServiceTransitionError as error:
            logging.warning("Action incomplete: %s %s: %s", service, action, error)
            self.reply(502, {"ok": False, "error": str(error)})
        except (RuntimeError, OSError, subprocess.SubprocessError, ValueError):
            logging.exception("Action failed: %s %s", service, action)
            self.reply(502, {"ok": False, "error": "Команда не выполнена. Проверьте сервис или повторите позже."})
        finally:
            lock.release()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("FLY_GATEWAY_CONTROL_PORT", "7684"))), Handler).serve_forever()
