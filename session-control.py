#!/usr/bin/env python3
import json
import os
import re
import base64
import mimetypes
import shlex
import subprocess
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SESSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_UPLOAD_BYTES = int(os.environ.get("FLY_TERMINAL_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
UPLOAD_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


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

        send_json(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        if self.path == "/api/session/terminate":
            self._handle_terminate()
        elif self.path == "/api/session/info":
            self._handle_info()
        elif self.path == "/api/session/upload-image":
            self._handle_upload_image()
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
