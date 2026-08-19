#!/usr/bin/env python3
"""Update the checkout from origin/main and restart the macOS stack."""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS_FILE = Path.home() / ".local/share/fly-terminal/update-status.json"
LABELS = (
    "ai.kruspe.fly-terminal.caddy",
    "ai.kruspe.fly-terminal.ttyd",
    "ai.kruspe.fly-terminal.browser",
)


def now():
    return datetime.now(timezone.utc).isoformat()


class Updater:
    def __init__(self, status_file):
        self.status_file = Path(status_file).expanduser()
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        self.entries = []
        self.ok = True

    def write(self, state, summary, step=""):
        payload = {
            "ok": self.ok,
            "state": state,
            "summary": summary,
            "step": step,
            "pid": os.getpid(),
            "updatedAt": now(),
            "entries": self.entries[-80:],
        }
        tmp = self.status_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.status_file)

    def run(self, step, command, timeout=60, check=True):
        self.write("running", step, step)
        try:
            result = subprocess.run(
                command, cwd=REPO_ROOT, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout if isinstance(exc.stdout, str) else ""
            self.ok = False
            self.entries.append({"time": now(), "step": step, "ok": False, "message": f"timeout after {timeout}s", "output": output[-4000:]})
            self.write("failed", f"Ошибка: {step}", step)
            if check:
                raise
            return False
        output = result.stdout or ""
        success = result.returncode == 0
        self.entries.append({"time": now(), "step": step, "ok": success, "message": f"exit {result.returncode}: {' '.join(command)}", "output": output[-4000:]})
        if not success:
            self.ok = False
            self.write("failed", f"Ошибка: {step}", step)
            if check:
                raise RuntimeError(f"{step} failed")
        else:
            self.write("running", step, step)
        return success

    def restart_stack(self):
        uid = subprocess.check_output(["id", "-u"], text=True).strip()
        domain = f"gui/{uid}"
        for label in LABELS:
            self.run(f"restart-{label}", ["launchctl", "kickstart", "-k", f"{domain}/{label}"], timeout=30)
        # The ttyd agent owns session-control; give launchd a moment to respawn it.
        time.sleep(2)
        for port in (8080, 7682, 7683):
            self.run(f"check-port-{port}", ["sh", "-c", f"lsof -nP -iTCP:{port} -sTCP:LISTEN"], timeout=10)

    def execute(self):
        self.write("running", "Проверяю локальные изменения", "preflight")
        self.run("git-status", ["git", "diff", "--quiet", "HEAD"], timeout=10)
        self.run("git-fetch", ["git", "fetch", "origin", "main"], timeout=90)
        self.run("git-pull", ["git", "pull", "--ff-only", "origin", "main"], timeout=90)
        self.restart_stack()
        self.write("success", "Обновление и перезапуск стека завершены", "complete")
        return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", default=os.environ.get("FLY_TERMINAL_UPDATE_STATUS_FILE", str(DEFAULT_STATUS_FILE)))
    args = parser.parse_args()
    updater = Updater(args.status_file)
    try:
        return updater.execute()
    except Exception as exc:
        updater.ok = False
        updater.entries.append({"time": now(), "step": "fatal", "ok": False, "message": str(exc)})
        updater.write("failed", "Обновление остановлено с ошибкой", "fatal")
        return 1


if __name__ == "__main__":
    sys.exit(main())
