#!/usr/bin/env python3
import json
import os
import re
import base64
import hashlib
import mimetypes
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SESSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")
CODEX_ANSWER_END_RE = re.compile(r"^\s*─+\s+Worked for\b")
CODEX_ANSWER_START_RE = re.compile(r"^\s*─{8,}\s*$")
MAX_UPLOAD_BYTES = int(os.environ.get("FLY_TERMINAL_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_LAST_ANSWER_CHARS = int(os.environ.get("FLY_TERMINAL_LAST_ANSWER_MAX_CHARS", str(1024 * 1024)))
UPLOAD_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")
DESKTOP_FIELD_CODE_RE = re.compile(r"%[A-Za-z]")
APP_DESKTOP_DIRS = (
    "/config/Desktop",
    "/config/.local/share/applications",
    "/usr/local/share/applications",
    "/usr/share/applications",
)
REPO_ROOT = Path(__file__).resolve().parent
RECOVERY_STATUS_FILE = Path(os.environ.get(
    "FLY_TERMINAL_RECOVERY_STATUS_FILE",
    str(Path.home() / ".local/share/fly-terminal/recovery-status.json"),
)).expanduser()
RECOVERY_SCRIPT = REPO_ROOT / "tools" / "recover_stack.py"
UPDATE_STATUS_FILE = Path(os.environ.get(
    "FLY_TERMINAL_UPDATE_STATUS_FILE",
    str(Path.home() / ".local/share/fly-terminal/update-status.json"),
)).expanduser()
UPDATE_SCRIPT = REPO_ROOT / "tools" / "update_stack.py"
HAPP_VPN_SERVICE = os.environ.get("FLY_TERMINAL_HAPP_SERVICE", "Happ Plus")
HAPP_RECONNECT_LOCK = threading.Lock()
HAPP_PREFERENCES = Path.home() / "Library/Group Containers/group.su.ffg.happ.plus/Library/Preferences/group.su.ffg.happ.plus.plist"
HAPP_CACHE_DIR = Path.home() / "Library/Containers/su.ffg.happ.plus/Data/Library/Caches/su.ffg.happ.plus/fsCachedData"


def happ_current_location():
    try:
        result = subprocess.run(
            ["plutil", "-extract", "connectedConfigJson", "raw", "-o", "-", str(HAPP_PREFERENCES)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=5,
        )
        config = json.loads(result.stdout) if result.returncode == 0 else {}
        return str(config.get("remarks") or "").strip()
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return ""


def happ_locations():
    """Read real server configurations from Happ's subscription cache."""
    candidates = []
    try:
        cache_files = sorted(HAPP_CACHE_DIR.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return []
    for cache_file in cache_files:
        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        parsed = []
        for config in payload:
            if not isinstance(config, dict) or not isinstance(config.get("outbounds"), list):
                continue
            label = str(config.get("remarks") or "").strip()
            if not label:
                continue
            encoded = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            parsed.append({"id": hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24], "label": label, "config": config})
        if parsed:
            candidates.extend(parsed)
            break
    unique = {}
    for location in candidates:
        unique.setdefault(location["label"], location)
    return list(unique.values())


def apply_happ_location(location):
    config_json = json.dumps(location["config"], ensure_ascii=False, separators=(",", ":"))
    result = subprocess.run(
        ["plutil", "-replace", "connectedConfigJson", "-string", config_json, str(HAPP_PREFERENCES)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    subprocess.run(["killall", "Tunnel"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=10)
    deadline = time.monotonic() + 20
    last_state = "Unknown"
    last_error = ""
    while time.monotonic() < deadline:
        last_state, last_error = happ_vpn_status()
        if last_state == "Connected" and happ_current_location() == location["label"]:
            return True, ""
        time.sleep(0.4)
    return False, last_error or f"Happ stayed at {happ_current_location() or 'an unknown location'} ({last_state})"


def happ_vpn_status():
    try:
        result = subprocess.run(
            ["scutil", "--nc", "status", HAPP_VPN_SERVICE],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "Unavailable", str(exc)

    output = (result.stdout or result.stderr).strip()
    state = output.splitlines()[0].strip() if output else "Unknown"
    if result.returncode != 0:
        return "Unavailable", output or f"scutil exited with code {result.returncode}"
    return state, ""


def wait_for_happ_vpn(states, timeout):
    deadline = time.monotonic() + timeout
    last_state = "Unknown"
    last_error = ""
    while time.monotonic() < deadline:
        last_state, last_error = happ_vpn_status()
        if last_state in states:
            return last_state, last_error
        time.sleep(0.4)
    return last_state, last_error


def run_happ_vpn_command(command):
    try:
        result = subprocess.run(
            ["scutil", "--nc", command, HAPP_VPN_SERVICE],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    details = (result.stderr or result.stdout).strip()
    return result.returncode == 0, details


def browser_container_name():
    return os.environ.get("FLY_BROWSER_CONTAINER_NAME", "fly-terminal-browser")


def docker_exec(args, **kwargs):
    return subprocess.run(
        ["docker", "exec", browser_container_name(), *args],
        stdout=kwargs.pop("stdout", subprocess.PIPE),
        stderr=kwargs.pop("stderr", subprocess.PIPE),
        text=kwargs.pop("text", True),
        check=False,
        **kwargs,
    )


def parse_desktop_entry(content):
    in_entry = False
    data = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_entry = line == "[Desktop Entry]"
            continue
        if not in_entry or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if "[" in key:
            continue
        data.setdefault(key, value.strip())
    return data


def clean_desktop_exec(exec_value):
    return DESKTOP_FIELD_CODE_RE.sub("", exec_value.replace("%%", "%")).strip()


def discover_browser_apps():
    quoted_dirs = " ".join(shlex.quote(path) for path in APP_DESKTOP_DIRS)
    find_result = docker_exec(
        ["sh", "-lc", f"find {quoted_dirs} -maxdepth 1 -type f -name '*.desktop' -print 2>/dev/null | sort"]
    )
    if find_result.returncode != 0:
        return [], find_result.stderr.strip() or "docker_exec_failed"

    apps = []
    seen = set()
    for path in find_result.stdout.splitlines():
        path = path.strip()
        if not path:
            continue
        cat_result = docker_exec(["sh", "-lc", f"cat {shlex.quote(path)} 2>/dev/null"])
        if cat_result.returncode != 0:
            continue
        entry = parse_desktop_entry(cat_result.stdout)
        if entry.get("Type", "Application") != "Application" or entry.get("Hidden", "").lower() == "true":
            continue
        name = entry.get("Name", "").strip()
        exec_value = entry.get("Exec", "").strip()
        if not name or not exec_value:
            continue
        cleaned_exec = clean_desktop_exec(exec_value)
        if not cleaned_exec:
            continue
        dedupe_key = (name.lower(), cleaned_exec)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        app_id = hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]
        apps.append(
            {
                "id": app_id,
                "name": name,
                "exec": cleaned_exec,
                "icon": entry.get("Icon", "").strip(),
                "categories": [part for part in entry.get("Categories", "").split(";") if part],
                "noDisplay": entry.get("NoDisplay", "").lower() == "true",
                "path": path,
            }
        )

    apps.sort(key=lambda app: (app["noDisplay"], app["name"].lower()))
    return apps, None


def launch_browser_app(app):
    try:
        command = shlex.split(app["exec"])
    except ValueError as exc:
        return False, f"invalid_exec: {exc}"
    if not command:
        return False, "empty_exec"

    existing_windows = visible_browser_windows()
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-u",
            "abc",
            "-d",
            "-e",
            "DISPLAY=:1",
            "-e",
            "HOME=/config",
            browser_container_name(),
            *command,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, result.stderr.strip() or "docker_exec_failed"
    focus_browser_app_window(app, existing_windows)
    return True, ""


def xdotool(args):
    return subprocess.run(
        [
            "docker",
            "exec",
            "-u",
            "abc",
            "-e",
            "DISPLAY=:1",
            "-e",
            "HOME=/config",
            browser_container_name(),
            "xdotool",
            *args,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )


def visible_browser_windows():
    result = xdotool(["search", "--onlyvisible", "--name", ".*"])
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()}


def activate_browser_window(window_id):
    if not window_id:
        return False
    result = xdotool(["windowactivate", "--sync", window_id])
    return result.returncode == 0


def focus_browser_app_window(app, existing_windows):
    for _ in range(12):
        current_windows = visible_browser_windows()
        new_windows = [window_id for window_id in current_windows if window_id not in existing_windows]
        if new_windows and activate_browser_window(new_windows[-1]):
            return True
        time.sleep(0.25)

    patterns = [app["name"]]
    try:
        command_name = Path(shlex.split(app["exec"])[0]).name
        if command_name:
            patterns.append(command_name)
    except ValueError:
        pass

    for pattern in patterns:
        result = xdotool(["search", "--onlyvisible", "--name", pattern])
        for window_id in reversed([line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]):
            if activate_browser_window(window_id):
                return True
    return False


def send_json(handler, status_code, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
    handler.end_headers()
    if body:
        handler.wfile.write(body)


def extract_last_codex_answer(captured_text):
    lines = captured_text.splitlines()
    end_index = next(
        (index for index in range(len(lines) - 1, -1, -1) if CODEX_ANSWER_END_RE.match(lines[index])),
        None,
    )
    if end_index is None:
        return ""

    start_index = next(
        (index for index in range(end_index - 1, -1, -1) if CODEX_ANSWER_START_RE.match(lines[index])),
        None,
    )
    if start_index is None:
        return ""

    answer_lines = lines[start_index + 1:end_index]
    while answer_lines and not answer_lines[0].strip():
        answer_lines.pop(0)
    while answer_lines and not answer_lines[-1].strip():
        answer_lines.pop()
    if not answer_lines:
        return ""

    answer_lines[0] = re.sub(r"^\s*•\s?", "", answer_lines[0], count=1)
    answer_lines = [line[2:] if line.startswith("  ") else line for line in answer_lines]
    return "\n".join(answer_lines).strip()


def pid_is_running(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def read_recovery_status():
    if not RECOVERY_STATUS_FILE.exists():
        return {
            "ok": True,
            "state": "idle",
            "summary": "Восстановление еще не запускалось",
            "entries": [],
        }
    try:
        status = json.loads(RECOVERY_STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "ok": False,
            "state": "unknown",
            "summary": "Не удалось прочитать статус восстановления",
            "entries": [],
        }

    if status.get("state") == "running" and not pid_is_running(status.get("pid")):
        status["state"] = "failed"
        status["ok"] = False
        status["summary"] = "Процесс восстановления не найден"
    return status


def read_update_status():
    if not UPDATE_STATUS_FILE.exists():
        return {"ok": True, "state": "idle", "summary": "Обновление еще не запускалось", "entries": []}
    try:
        status = json.loads(UPDATE_STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "state": "unknown", "summary": "Не удалось прочитать статус обновления", "entries": []}
    if status.get("state") == "running" and not pid_is_running(status.get("pid")):
        status["state"] = "failed"
        status["ok"] = False
        status["summary"] = "Процесс обновления не найден"
    return status


class SessionControlHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_json(self, 200, {})

    def do_GET(self):
        if self.path == "/api/sessions/list":
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            sessions = []
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("fly-terminal-"):
                        sessions.append(line.replace("fly-terminal-", "", 1))
            send_json(self, 200, {"ok": True, "sessions": sessions})
            return

        if self.path == "/api/browser/config":
            enabled = os.environ.get("FLY_BROWSER_ENABLED", "0") == "1"
            browser_url = os.environ.get("FLY_BROWSER_URL", "/browser/")
            send_json(
                self,
                200,
                {
                    "ok": True,
                    "enabled": enabled,
                    "url": browser_url if enabled else "",
                },
            )
            return

        if self.path == "/api/apps/list":
            apps, error = discover_browser_apps()
            if error:
                send_json(self, 503, {"ok": False, "error": error, "apps": []})
            else:
                send_json(self, 200, {"ok": True, "apps": apps})
            return

        if self.path == "/api/system/recover/status":
            send_json(self, 200, read_recovery_status())
            return

        if self.path == "/api/system/update/status":
            send_json(self, 200, read_update_status())
            return

        if self.path == "/api/vpn/happ/status":
            state, error = happ_vpn_status()
            send_json(
                self,
                200 if not error else 503,
                {"ok": not error, "service": HAPP_VPN_SERVICE, "state": state, "location": happ_current_location(), "error": error},
            )
            return

        if self.path == "/api/vpn/happ/locations":
            locations = happ_locations()
            current = happ_current_location()
            send_json(self, 200, {
                "ok": True,
                "current": current,
                "locations": [{"id": item["id"], "label": item["label"]} for item in locations],
                "configured": bool(locations),
            })
            return

        send_json(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        if self.path == "/api/session/terminate":
            self._handle_terminate()
        elif self.path == "/api/session/info":
            self._handle_info()
        elif self.path == "/api/session/last-answer":
            self._handle_last_answer()
        elif self.path == "/api/session/upload-image":
            self._handle_upload_image()
        elif self.path == "/api/apps/launch":
            self._handle_launch_app()
        elif self.path == "/api/system/recover":
            self._handle_recover()
        elif self.path == "/api/system/update":
            self._handle_update()
        elif self.path == "/api/vpn/happ/reconnect":
            self._handle_happ_reconnect()
        elif self.path == "/api/vpn/happ/location":
            self._handle_happ_location()
        else:
            send_json(self, 404, {"ok": False, "error": "not_found"})

    def _read_json_body(self, max_bytes=4096):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        if content_length > max_bytes:
            return None, "payload_too_large"

        raw_body = self.rfile.read(content_length)
        try:
            return json.loads(raw_body or b"{}"), None
        except json.JSONDecodeError:
            return None, "invalid_json"

    def _handle_info(self):
        payload, error = self._read_json_body()
        if error:
            send_json(self, 400, {"ok": False, "error": error})
            return

        session_id = str(payload.get("sessionId", ""))
        if not SESSION_RE.fullmatch(session_id):
            send_json(self, 400, {"ok": False, "error": "invalid_session_id"})
            return

        tmux_target = f"fly-terminal-{session_id}"
        # Get CWD of the active pane
        result = subprocess.run(
            ["tmux", "list-panes", "-t", tmux_target, "-F", "#{pane_current_path}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            send_json(self, 404, {"ok": False, "error": "session_not_found"})
            return

        cwd = result.stdout.strip().splitlines()[0]
        send_json(self, 200, {"ok": True, "sessionId": session_id, "cwd": cwd})

    def _handle_last_answer(self):
        payload, error = self._read_json_body()
        if error:
            send_json(self, 400, {"ok": False, "error": error})
            return

        session_id = str(payload.get("sessionId", ""))
        if not SESSION_RE.fullmatch(session_id):
            send_json(self, 400, {"ok": False, "error": "invalid_session_id"})
            return

        tmux_target = f"fly-terminal-{session_id}"
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-p", "-J", "-S", "-", "-t", tmux_target],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            send_json(self, 500, {"ok": False, "error": "capture_failed", "details": str(exc)})
            return

        if result.returncode != 0:
            send_json(self, 404, {"ok": False, "error": "session_not_found"})
            return

        answer = extract_last_codex_answer(result.stdout)
        if not answer:
            send_json(self, 404, {"ok": False, "error": "answer_not_found"})
            return
        if len(answer) > MAX_LAST_ANSWER_CHARS:
            send_json(self, 413, {"ok": False, "error": "answer_too_large"})
            return

        send_json(
            self,
            200,
            {"ok": True, "sessionId": session_id, "answer": answer, "characters": len(answer)},
        )

    def _handle_upload_image(self):
        max_body = int(MAX_UPLOAD_BYTES * 1.4) + 4096
        payload, error = self._read_json_body(max_body)
        if error:
            status = 413 if error == "payload_too_large" else 400
            send_json(self, status, {"ok": False, "error": error})
            return

        session_id = str(payload.get("sessionId", ""))
        if not SESSION_RE.fullmatch(session_id):
            send_json(self, 400, {"ok": False, "error": "invalid_session_id"})
            return

        mime_type = str(payload.get("mimeType", "application/octet-stream")).split(";", 1)[0]
        if not mime_type.startswith("image/"):
            send_json(self, 400, {"ok": False, "error": "not_an_image"})
            return

        data_b64 = str(payload.get("data", ""))
        try:
            content = base64.b64decode(data_b64, validate=True)
        except (ValueError, TypeError):
            send_json(self, 400, {"ok": False, "error": "invalid_image_data"})
            return

        if not content:
            send_json(self, 400, {"ok": False, "error": "empty_image"})
            return
        if len(content) > MAX_UPLOAD_BYTES:
            send_json(self, 413, {"ok": False, "error": "image_too_large"})
            return

        tmux_target = f"fly-terminal-{session_id}"
        cwd_result = subprocess.run(
            ["tmux", "list-panes", "-t", tmux_target, "-F", "#{pane_current_path}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if cwd_result.returncode != 0:
            send_json(self, 404, {"ok": False, "error": "session_not_found"})
            return

        suggested_name = str(payload.get("fileName", "clipboard-image")).strip()
        safe_stem = UPLOAD_NAME_RE.sub("_", Path(suggested_name).stem).strip(" ._") or "clipboard-image"
        suffix = Path(suggested_name).suffix.lower()
        if not suffix:
            suffix = mimetypes.guess_extension(mime_type) or ".png"
        if suffix == ".jpe":
            suffix = ".jpg"

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        file_name = f"{safe_stem}-{timestamp}{suffix}"
        cwd = Path(cwd_result.stdout.strip().splitlines()[0]).expanduser()
        fallback_root = Path(os.environ.get(
            "FLY_TERMINAL_UPLOAD_DIR",
            str(Path.home() / "Downloads" / "Fly Terminal Uploads"),
        )).expanduser()
        fallback_dir = fallback_root / session_id

        target_dir = cwd if cwd.is_dir() and os.access(cwd, os.W_OK) else fallback_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / file_name
        target_path.write_bytes(content)

        paste_text = shlex.quote(str(target_path))
        send_result = subprocess.run(
            ["tmux", "send-keys", "-t", tmux_target, "-l", paste_text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if send_result.returncode != 0:
            send_json(
                self,
                500,
                {"ok": False, "error": "send_failed", "details": send_result.stderr.strip()},
            )
            return

        send_json(
            self,
            200,
            {
                "ok": True,
                "sessionId": session_id,
                "path": str(target_path),
                "inserted": paste_text,
                "bytes": len(content),
            },
        )

    def _handle_launch_app(self):
        payload, error = self._read_json_body()
        if error:
            send_json(self, 400, {"ok": False, "error": error})
            return

        app_id = str(payload.get("appId", ""))
        apps, discover_error = discover_browser_apps()
        if discover_error:
            send_json(self, 503, {"ok": False, "error": discover_error})
            return

        app = next((candidate for candidate in apps if candidate["id"] == app_id), None)
        if not app:
            send_json(self, 404, {"ok": False, "error": "app_not_found"})
            return

        ok, launch_error = launch_browser_app(app)
        if not ok:
            send_json(self, 500, {"ok": False, "error": "launch_failed", "details": launch_error})
            return

        send_json(self, 200, {"ok": True, "app": {"id": app["id"], "name": app["name"]}})

    def _handle_recover(self):
        current_status = read_recovery_status()
        if current_status.get("state") == "running":
            send_json(self, 409, {"ok": False, "error": "recovery_already_running", "status": current_status})
            return

        if not RECOVERY_SCRIPT.exists():
            send_json(self, 500, {"ok": False, "error": "recovery_script_missing"})
            return

        RECOVERY_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        started_status = {
            "ok": True,
            "state": "starting",
            "summary": "Восстановление запускается",
            "step": "starting",
            "pid": None,
            "updatedAt": datetime.now().isoformat(),
            "entries": [],
        }
        RECOVERY_STATUS_FILE.write_text(json.dumps(started_status, ensure_ascii=False, indent=2), encoding="utf-8")

        log_path = RECOVERY_STATUS_FILE.with_suffix(".log")
        log_file = log_path.open("a", encoding="utf-8")
        env = os.environ.copy()
        env["FLY_TERMINAL_RECOVERY_STATUS_FILE"] = str(RECOVERY_STATUS_FILE)
        try:
            process = subprocess.Popen(
                [sys.executable, str(RECOVERY_SCRIPT), "--status-file", str(RECOVERY_STATUS_FILE)],
                cwd=str(REPO_ROOT),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            send_json(self, 500, {"ok": False, "error": "recovery_start_failed", "details": str(exc)})
            return
        finally:
            log_file.close()

        send_json(
            self,
            202,
            {
                "ok": True,
                "state": "running",
                "pid": process.pid,
                "summary": "Восстановление запущено",
            },
        )

    def _handle_update(self):
        current_status = read_update_status()
        if current_status.get("state") in {"running", "starting"}:
            send_json(self, 409, {"ok": False, "error": "update_already_running", "status": current_status})
            return
        if not UPDATE_SCRIPT.exists():
            send_json(self, 500, {"ok": False, "error": "update_script_missing"})
            return

        UPDATE_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        started_status = {
            "ok": True,
            "state": "starting",
            "summary": "Обновление запускается",
            "step": "starting",
            "pid": None,
            "updatedAt": datetime.now().isoformat(),
            "entries": [],
        }
        UPDATE_STATUS_FILE.write_text(json.dumps(started_status, ensure_ascii=False, indent=2), encoding="utf-8")
        log_path = UPDATE_STATUS_FILE.with_suffix(".log")
        log_file = log_path.open("a", encoding="utf-8")
        env = os.environ.copy()
        env["FLY_TERMINAL_UPDATE_STATUS_FILE"] = str(UPDATE_STATUS_FILE)
        try:
            process = subprocess.Popen(
                [sys.executable, str(UPDATE_SCRIPT), "--status-file", str(UPDATE_STATUS_FILE)],
                cwd=str(REPO_ROOT), env=env, stdout=log_file, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            send_json(self, 500, {"ok": False, "error": "update_start_failed", "details": str(exc)})
            return
        finally:
            log_file.close()
        send_json(self, 202, {"ok": True, "state": "running", "pid": process.pid, "summary": "Обновление запущено"})

    def _handle_happ_reconnect(self):
        if not HAPP_RECONNECT_LOCK.acquire(blocking=False):
            send_json(self, 409, {"ok": False, "error": "reconnect_already_running"})
            return

        try:
            initial_state, status_error = happ_vpn_status()
            if status_error:
                send_json(
                    self,
                    503,
                    {"ok": False, "error": "happ_service_unavailable", "details": status_error},
                )
                return

            if initial_state not in {"Disconnected", "Invalid"}:
                stopped, stop_error = run_happ_vpn_command("stop")
                if not stopped:
                    send_json(
                        self,
                        500,
                        {"ok": False, "error": "happ_disconnect_failed", "details": stop_error},
                    )
                    return
                stopped_state, _ = wait_for_happ_vpn({"Disconnected"}, 10)
                if stopped_state != "Disconnected":
                    send_json(
                        self,
                        504,
                        {"ok": False, "error": "happ_disconnect_timeout", "state": stopped_state},
                    )
                    return

            started, start_error = run_happ_vpn_command("start")
            if not started:
                send_json(
                    self,
                    500,
                    {"ok": False, "error": "happ_connect_failed", "details": start_error},
                )
                return

            final_state, final_error = wait_for_happ_vpn({"Connected"}, 20)
            if final_state != "Connected":
                send_json(
                    self,
                    504,
                    {
                        "ok": False,
                        "error": "happ_connect_timeout",
                        "state": final_state,
                        "details": final_error,
                    },
                )
                return

            send_json(
                self,
                200,
                {
                    "ok": True,
                    "service": HAPP_VPN_SERVICE,
                    "state": final_state,
                    "previousState": initial_state,
                },
            )
        finally:
            HAPP_RECONNECT_LOCK.release()

    def _handle_happ_location(self):
        payload, error = self._read_json_body()
        if error:
            send_json(self, 400, {"ok": False, "error": error})
            return
        location_id = str(payload.get("locationId") or "")
        location = next((item for item in happ_locations() if item["id"] == location_id), None)
        if not location:
            send_json(self, 404, {"ok": False, "error": "happ_location_not_found"})
            return
        if not HAPP_RECONNECT_LOCK.acquire(blocking=False):
            send_json(self, 409, {"ok": False, "error": "happ_action_already_running"})
            return
        try:
            switched, switch_error = apply_happ_location(location)
            final_state, final_error = happ_vpn_status()
            if not switched:
                send_json(self, 504, {"ok": False, "error": "happ_location_switch_failed", "state": final_state, "details": switch_error or final_error})
                return
            send_json(self, 200, {"ok": True, "service": HAPP_VPN_SERVICE, "state": final_state, "location": happ_current_location() or location["label"]})
        except (OSError, subprocess.TimeoutExpired) as exc:
            send_json(self, 500, {"ok": False, "error": "happ_location_switch_failed", "details": str(exc)})
        finally:
            HAPP_RECONNECT_LOCK.release()

    def _handle_terminate(self):
        payload, error = self._read_json_body()
        if error:
            send_json(self, 400, {"ok": False, "error": error})
            return

        session_id = str(payload.get("sessionId", ""))
        if not SESSION_RE.fullmatch(session_id):
            send_json(self, 400, {"ok": False, "error": "invalid_session_id"})
            return

        tmux_target = f"fly-terminal-{session_id}"
        exists = subprocess.run(
            ["tmux", "has-session", "-t", tmux_target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0

        if exists:
            result = subprocess.run(
                ["tmux", "kill-session", "-t", tmux_target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                send_json(
                    self,
                    500,
                    {"ok": False, "error": "kill_failed", "details": result.stderr.strip()},
                )
                return

        send_json(self, 200, {"ok": True, "terminated": exists, "sessionId": session_id})

    def log_message(self, format, *args):
        return


def main():
    port = int(os.environ.get("FLY_TERMINAL_CONTROL_PORT", "7683"))
    server = ThreadingHTTPServer(("127.0.0.1", port), SessionControlHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
