#!/usr/bin/env python3
"""Safely recover the live ttyd + Tailscale Funnel path on this Mac."""

from __future__ import annotations

import argparse
import base64
import fcntl
import http.client
import json
import os
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path.home() / ".config/fly-terminal-mac/fly-terminal.env"
STATUS_FILE = Path.home() / ".local/share/fly-terminal/funnel-recovery-status.json"
LOCK_FILE = Path("/tmp/fly-terminal-funnel-recovery.lock")
TAILSCALE_SERVICE = "Tailscale"
FUNNEL_HOST = "mac-mini.tail1c55c5.ts.net"
FUNNEL_TARGET = "http://127.0.0.1:8080"
FUNNEL_PORTS = (443, 8443)
LOCAL_LABELS = (
    "ai.kruspe.fly-terminal.caddy",
    "ai.kruspe.fly-terminal.ttyd",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RecoveryError(RuntimeError):
    pass


class Recovery:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.events: list[dict[str, object]] = []
        self.started_at = now()
        self.status_file = Path(args.status_file).expanduser()
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        self.env_values = self.read_env_file()

    def emit(self, step: str, ok: bool, message: str, **details: object) -> None:
        event: dict[str, object] = {
            "time": now(),
            "step": step,
            "ok": ok,
            "message": message,
        }
        if details:
            event["details"] = details
        self.events.append(event)
        if not self.args.json:
            marker = "OK" if ok else "FAIL"
            print(f"[{marker}] {step}: {message}", flush=True)
        self.write_status("running", step)

    def write_status(self, state: str, step: str, exit_code: int | None = None) -> None:
        payload = {
            "state": state,
            "step": step,
            "startedAt": self.started_at,
            "updatedAt": now(),
            "exitCode": exit_code,
            "events": self.events[-100:],
        }
        temporary = self.status_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.status_file)

    @staticmethod
    def read_env_file() -> dict[str, str]:
        values: dict[str, str] = {}
        if not ENV_FILE.exists():
            return values
        for raw_line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'\"")
        return values

    @staticmethod
    def run_command(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )

    def auth_header(self) -> str:
        user = self.env_values.get("TERMINAL_USER", "")
        password = self.env_values.get("TERMINAL_PASSWORD", "")
        if not user or not password:
            raise RecoveryError(f"missing TERMINAL_USER or TERMINAL_PASSWORD in {ENV_FILE}")
        encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
        return f"Basic {encoded}"

    def http_status(self, path: str, authenticated: bool = True) -> int:
        connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=5)
        headers = {"Host": "127.0.0.1:8080", "Connection": "close"}
        if authenticated:
            headers["Authorization"] = self.auth_header()
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            response.read(512)
            return response.status
        finally:
            connection.close()

    def websocket_status(self, path: str) -> int:
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            "Host: 127.0.0.1:8080\r\n"
            f"Authorization: {self.auth_header()}\r\n"
            "Connection: Upgrade\r\n"
            "Upgrade: websocket\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Sec-WebSocket-Key: {key}\r\n\r\n"
        )
        with socket.create_connection(("127.0.0.1", 8080), timeout=5) as sock:
            sock.sendall(request.encode())
            first_line = sock.recv(1024).split(b"\r\n", 1)[0].decode("latin1", "replace")
        parts = first_line.split()
        return int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0

    def local_health(self) -> tuple[bool, dict[str, int]]:
        results: dict[str, int] = {}
        checks = {
            "root_unauth": lambda: self.http_status("/", authenticated=False),
            "terminal": lambda: self.http_status("/terminal/"),
            "api": lambda: self.http_status("/api/sessions/list"),
            "terminal_ws": lambda: self.websocket_status("/terminal/ws"),
        }
        expected = {"root_unauth": 401, "terminal": 200, "api": 200, "terminal_ws": 101}
        for name, check in checks.items():
            try:
                results[name] = check()
            except Exception:
                results[name] = 0
        healthy = all(results[name] == expected[name] for name in expected)
        self.emit("local-health", healthy, json.dumps(results, sort_keys=True), expected=expected)
        return healthy, results

    def restart_local_services(self) -> None:
        domain = f"gui/{os.getuid()}"
        for label in LOCAL_LABELS:
            result = self.run_command(["launchctl", "kickstart", "-k", f"{domain}/{label}"], timeout=20)
            self.emit(
                "launchctl-kickstart",
                result.returncode == 0,
                label,
                returncode=result.returncode,
                output=(result.stdout or "")[-1000:],
            )
        deadline = time.time() + 30
        while time.time() < deadline:
            healthy, _ = self.local_health()
            if healthy:
                return
            time.sleep(2)
        raise RecoveryError("local ttyd/Caddy health did not recover")

    def network_state(self) -> str:
        result = self.run_command(["/usr/sbin/scutil", "--nc", "status", TAILSCALE_SERVICE], timeout=8)
        return (result.stdout or "").splitlines()[0].strip() if result.stdout else "Unknown"

    def tailscale_online(self) -> bool:
        result = self.run_command(["tailscale", "status", "--json"], timeout=10)
        if result.returncode != 0:
            return False
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return False
        return payload.get("BackendState") == "Running" and payload.get("Self", {}).get("Online") is True

    def tailscale_backend_state(self) -> str:
        result = self.run_command(["tailscale", "status", "--json"], timeout=10)
        if result.returncode != 0:
            return "Unknown"
        try:
            return str(json.loads(result.stdout).get("BackendState", "Unknown"))
        except json.JSONDecodeError:
            return "Unknown"

    def extension_pid(self) -> str:
        result = self.run_command(
            ["pgrep", "-f", "io.tailscale.ipn.macsys.network-extension"], timeout=5
        )
        return ",".join(line.strip() for line in result.stdout.splitlines() if line.strip())

    def tailscale_up(self) -> None:
        command = ["tailscale", "up", "--timeout=30s"]
        result = self.run_command(command, timeout=40)
        if result.returncode == 0:
            return
        suggested: list[str] | None = None
        for line in result.stdout.splitlines():
            candidate = line.strip()
            if candidate.startswith("tailscale up "):
                parsed = shlex.split(candidate)
                if parsed[:2] == ["tailscale", "up"]:
                    suggested = parsed
                    break
        if suggested is None:
            raise RecoveryError(f"tailscale up failed: {result.stdout.strip()}")
        retry = self.run_command(suggested, timeout=40)
        if retry.returncode != 0:
            raise RecoveryError(f"suggested tailscale up failed: {retry.stdout.strip()}")
        self.emit("tailscale-up", True, "restored with preserved non-default settings")

    def wait_network(self, wanted: str, timeout: int) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self.network_state()
            online = self.tailscale_online()
            if state == wanted and (wanted != "Connected" or online):
                self.emit("tailscale-network", True, f"state={state} online={online}")
                return True
            time.sleep(1)
        self.emit("tailscale-network", False, f"wanted={wanted} state={self.network_state()}")
        return False

    def restart_tailscale_extension(self) -> None:
        before = self.extension_pid()
        stop = self.run_command(["/usr/sbin/scutil", "--nc", "stop", TAILSCALE_SERVICE], timeout=10)
        if stop.returncode != 0:
            raise RecoveryError(f"failed to stop Tailscale Network Extension: {stop.stdout.strip()}")
        deadline = time.time() + 20
        stopped = False
        while time.time() < deadline:
            state = self.network_state()
            backend = self.tailscale_backend_state()
            current_pid = self.extension_pid()
            if state == "Disconnected" or backend == "Stopped" or (before and current_pid != before):
                stopped = True
                self.emit(
                    "tailscale-network-stop",
                    True,
                    f"state={state} backend={backend} pid={before or '?'}->{current_pid or '?'}",
                )
                break
            time.sleep(1)
        if not stopped:
            raise RecoveryError("Tailscale Network Extension did not stop or restart")
        start = self.run_command(["/usr/sbin/scutil", "--nc", "start", TAILSCALE_SERVICE], timeout=10)
        if start.returncode != 0:
            raise RecoveryError(f"failed to start Tailscale Network Extension: {start.stdout.strip()}")
        self.tailscale_up()
        if not self.wait_network("Connected", 40):
            raise RecoveryError("Tailscale Network Extension did not reconnect")
        after = self.extension_pid()
        self.emit("tailscale-extension-restart", True, f"pid {before or '?'} -> {after or '?'}")

    def republish_funnel(self) -> None:
        for port in FUNNEL_PORTS:
            off = self.run_command(
                ["tailscale", "funnel", "--yes", f"--https={port}", "off"], timeout=20
            )
            if off.returncode != 0:
                raise RecoveryError(f"failed to disable Funnel port {port}: {off.stdout.strip()}")
            on = self.run_command(
                ["tailscale", "funnel", "--bg", "--yes", f"--https={port}", FUNNEL_TARGET],
                timeout=30,
            )
            if on.returncode != 0:
                raise RecoveryError(f"failed to publish Funnel port {port}: {on.stdout.strip()}")
        status = self.run_command(["tailscale", "funnel", "status", "--json"], timeout=10)
        configured = (
            status.returncode == 0
            and FUNNEL_HOST in status.stdout
            and FUNNEL_TARGET in status.stdout
            and all(f'"{port}"' in status.stdout for port in FUNNEL_PORTS)
        )
        self.emit(
            "funnel-republish",
            configured,
            f"{','.join(str(port) for port in FUNNEL_PORTS)} -> {FUNNEL_TARGET}",
        )
        if not configured:
            raise RecoveryError("Funnel status does not contain the expected mapping")

    @staticmethod
    def resolve_with_doh(url: str, headers: dict[str, str] | None = None) -> list[str]:
        request = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.load(response)
        if payload.get("Status") != 0:
            return []
        return sorted(
            item.get("data", "")
            for item in payload.get("Answer", [])
            if item.get("type") == 1 and item.get("data")
        )

    def wait_public_dns(self) -> bool:
        providers = {
            "google": (
                f"https://dns.google/resolve?name={FUNNEL_HOST}&type=A",
                {},
            ),
            "cloudflare": (
                f"https://cloudflare-dns.com/dns-query?name={FUNNEL_HOST}&type=A",
                {"accept": "application/dns-json"},
            ),
        }
        deadline = time.time() + self.args.dns_wait
        latest: dict[str, list[str]] = {}
        while time.time() <= deadline:
            for name, (url, headers) in providers.items():
                try:
                    latest[name] = self.resolve_with_doh(url, headers)
                except Exception:
                    latest[name] = []
            if any(latest.values()):
                self.emit("public-dns", True, json.dumps(latest, sort_keys=True))
                return True
            time.sleep(5)
        self.emit("public-dns", False, json.dumps(latest, sort_keys=True))
        return False

    def run(self) -> int:
        self.write_status("running", "starting")
        try:
            local_ok, _ = self.local_health()
            if self.args.diagnose:
                online = self.tailscale_online()
                self.emit("tailscale-online", online, str(online))
                dns_ok = self.wait_public_dns()
                code = 0 if local_ok and online and dns_ok else 2
                self.finish(code)
                return code

            if not local_ok:
                self.restart_local_services()
            if not self.args.local_only:
                self.restart_tailscale_extension()
                self.republish_funnel()
                dns_ok = self.wait_public_dns()
            else:
                dns_ok = True
            final_local_ok, _ = self.local_health()
            code = 0 if final_local_ok and dns_ok else 2
            if not self.args.local_only:
                self.emit(
                    "external-check",
                    True,
                    (
                        "manual browser check required: "
                        f"https://{FUNNEL_HOST}/ and https://{FUNNEL_HOST}:8443/"
                    ),
                )
            self.finish(code)
            return code
        except Exception as exc:
            self.emit("fatal", False, str(exc))
            self.finish(1)
            return 1

    def finish(self, code: int) -> None:
        state = "success" if code == 0 else "failed"
        self.write_status(state, "complete", code)
        if self.args.json:
            print(
                json.dumps(
                    {
                        "state": state,
                        "exitCode": code,
                        "statusFile": str(self.status_file),
                        "events": self.events,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recover ttyd/Caddy and the Tailscale Funnel path without rebooting the Mac."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--diagnose", action="store_true", help="run checks without changing services")
    mode.add_argument("--local-only", action="store_true", help="repair only Caddy and ttyd")
    parser.add_argument("--dns-wait", type=int, default=120, help="seconds to wait for a public A record")
    parser.add_argument("--json", action="store_true", help="print the final result as JSON")
    parser.add_argument("--status-file", default=str(STATUS_FILE))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    LOCK_FILE.touch(mode=0o600, exist_ok=True)
    with LOCK_FILE.open("r+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another fly-terminal Funnel recovery is already running.", file=sys.stderr)
            return 3
        return Recovery(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
