#!/usr/bin/env python3
import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS_FILE = Path.home() / ".local/share/fly-terminal/recovery-status.json"
LABELS = (
    "ai.kruspe.fly-terminal.caddy",
    "ai.kruspe.fly-terminal.ttyd",
    "ai.kruspe.fly-terminal.browser",
)
PLISTS = tuple(Path.home() / "Library/LaunchAgents" / f"{label}.plist" for label in LABELS)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class Recovery:
    def __init__(self, status_file):
        self.status_file = Path(status_file).expanduser()
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        self.entries = []
        self.ok = True
        self.current_step = "starting"

    def write_status(self, state, summary):
        payload = {
            "ok": self.ok,
            "state": state,
            "summary": summary,
            "step": self.current_step,
            "pid": os.getpid(),
            "updatedAt": utc_now(),
            "entries": self.entries[-80:],
        }
        tmp = self.status_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.status_file)

    def add_entry(self, step, ok, message, output=""):
        entry = {
            "time": utc_now(),
            "step": step,
            "ok": bool(ok),
            "message": message,
        }
        if output:
            entry["output"] = output.strip()[-4000:]
        self.entries.append(entry)
        if not ok:
            self.ok = False
        self.current_step = step
        self.write_status("running", message)

    def run(self, step, cmd, timeout=60, check=False, env=None):
        self.current_step = step
        self.write_status("running", step)
        try:
            result = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                check=False,
            )
            output = result.stdout or ""
            ok = result.returncode == 0
            if check and not ok:
                self.add_entry(step, False, f"failed: {' '.join(cmd)}", output)
                raise RuntimeError(f"{step} failed")
            self.add_entry(step, ok, f"exit {result.returncode}: {' '.join(cmd)}", output)
            return ok, output
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            self.add_entry(step, False, f"timeout after {timeout}s: {' '.join(cmd)}", output)
            if check:
                raise
            return False, output

    def read_env_file(self):
        env_path = Path.home() / ".config/fly-terminal-mac/fly-terminal.env"
        values = {}
        if not env_path.exists():
            return values
        for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'\"")
        return values

    def ensure_colima(self):
        docker_ok, docker_out = self.run("docker-info", ["docker", "info"], timeout=12)
        df_ok, df_out = self.run("docker-system-df", ["docker", "system", "df"], timeout=20)
        combined = f"{docker_out}\n{df_out}".lower()
        needs_restart = (not docker_ok or not df_ok) and (
            "input/output error" in combined
            or "no such file or directory" in combined
            or "cannot connect" in combined
            or "failed to connect" in combined
            or "empty value" in combined
        )
        if needs_restart:
            self.ok = True
            self.run("colima-stop", ["colima", "stop"], timeout=120)
            self.run("colima-start", ["colima", "start"], timeout=180, check=True)
            self.run("docker-info-after-colima", ["docker", "info"], timeout=20, check=True)

    def launch_browser(self):
        self.run("launch-browser", ["zsh", str(REPO_ROOT / "macos/launch-browser.sh")], timeout=180, check=True)

    def launchctl_domain(self):
        uid = subprocess.check_output(["id", "-u"], text=True).strip()
        return f"gui/{uid}"

    def ensure_launchagents_loaded(self):
        domain = self.launchctl_domain()
        for label, plist in zip(LABELS, PLISTS):
            previous_ok = self.ok
            ok, output = self.run(f"launchctl-print-{label}", ["launchctl", "print", f"{domain}/{label}"], timeout=8)
            if ok:
                continue
            self.ok = previous_ok
            if not plist.exists():
                self.add_entry(f"launchctl-bootstrap-{label}", False, f"missing plist: {plist}")
                continue
            self.run(f"launchctl-bootstrap-{label}", ["launchctl", "bootstrap", domain, str(plist)], timeout=20)

    def wait_for_ports(self):
        targets = {
            8080: "caddy",
            7682: "ttyd",
            7683: "session-control",
            7690: "browser-upstream",
        }
        deadline = time.time() + 45
        seen = set()
        while time.time() < deadline:
            for port, name in targets.items():
                if port in seen:
                    continue
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=1):
                        seen.add(port)
                        self.add_entry(f"port-{port}", True, f"{name} is listening on {port}")
                except OSError:
                    pass
            if len(seen) == len(targets):
                return
            time.sleep(1)
        missing = [f"{name}:{port}" for port, name in targets.items() if port not in seen]
        self.add_entry("wait-for-ports", False, f"ports not ready: {', '.join(missing)}")

    def http_status(self, path, auth_header):
        request = (
            f"GET {path} HTTP/1.1\r\n"
            "Host: 127.0.0.1:8080\r\n"
            f"Authorization: {auth_header}\r\n"
            "Connection: close\r\n\r\n"
        )
        with socket.create_connection(("127.0.0.1", 8080), timeout=5) as sock:
            sock.sendall(request.encode("utf-8"))
            response = sock.recv(1024).decode("latin1", "replace")
        return response.splitlines()[0] if response else ""

    def websocket_status(self, path, auth_header):
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            "Host: 127.0.0.1:8080\r\n"
            f"Authorization: {auth_header}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        with socket.create_connection(("127.0.0.1", 8080), timeout=5) as sock:
            sock.sendall(request.encode("utf-8"))
            response = sock.recv(2048).decode("latin1", "replace")
        return response.splitlines()[0] if response else ""

    def smoke(self):
        env_values = self.read_env_file()
        user = env_values.get("TERMINAL_USER", "admin")
        password = env_values.get("TERMINAL_PASSWORD", "")
        auth_header = "Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")

        checks = [
            ("http-browser", lambda: self.http_status("/browser/", auth_header), "200"),
            ("ws-browser", lambda: self.websocket_status("/browser/websockets", auth_header), "101"),
            ("ws-terminal", lambda: self.websocket_status("/terminal/ws", auth_header), "101"),
        ]
        for step, fn, expected in checks:
            last_status = ""
            last_error = ""
            for _ in range(30):
                try:
                    last_status = fn()
                    if expected in last_status:
                        self.add_entry(step, True, last_status)
                        break
                except Exception as exc:
                    last_error = str(exc)
                time.sleep(1)
            else:
                self.add_entry(step, False, last_status or last_error or "empty response")

        self.run("launchctl-caddy-state", ["launchctl", "print", f"{self.launchctl_domain()}/{LABELS[0]}"], timeout=8)
        self.run("launchctl-ttyd-state", ["launchctl", "print", f"{self.launchctl_domain()}/{LABELS[1]}"], timeout=8)
        self.run("docker-ps-browser", ["docker", "ps", "--filter", "name=fly-terminal-browser"], timeout=12)
        self.run("disk-space", ["df", "-h", str(Path.home()), str(Path.home() / ".colima")], timeout=8)

    def run_recovery(self):
        self.write_status("running", "Восстановление запущено")
        try:
            self.ensure_colima()
            self.launch_browser()
            self.ensure_launchagents_loaded()
            self.wait_for_ports()
            self.launch_browser()
            self.smoke()
        except Exception as exc:
            self.add_entry("fatal", False, str(exc))

        state = "success" if self.ok else "failed"
        summary = "Восстановление завершено" if self.ok else "Восстановление завершилось с ошибками"
        self.write_status(state, summary)
        return 0 if self.ok else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", default=os.environ.get("FLY_TERMINAL_RECOVERY_STATUS_FILE", str(DEFAULT_STATUS_FILE)))
    args = parser.parse_args()
    recovery = Recovery(args.status_file)
    return recovery.run_recovery()


if __name__ == "__main__":
    sys.exit(main())
