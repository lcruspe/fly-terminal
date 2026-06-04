#!/usr/bin/env python3
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SESSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")


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

        send_json(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        if self.path == "/api/session/terminate":
            self._handle_terminate()
        elif self.path == "/api/session/info":
            self._handle_info()
        else:
            send_json(self, 404, {"ok": False, "error": "not_found"})

    def _handle_info(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        raw_body = self.rfile.read(min(content_length, 4096))
        try:
            payload = json.loads(raw_body or b"{}")
        except json.JSONDecodeError:
            send_json(self, 400, {"ok": False, "error": "invalid_json"})
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

    def _handle_terminate(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        raw_body = self.rfile.read(min(content_length, 4096))
        try:
            payload = json.loads(raw_body or b"{}")
        except json.JSONDecodeError:
            send_json(self, 400, {"ok": False, "error": "invalid_json"})
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
