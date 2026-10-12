#!/usr/bin/env python3
"""Update the checkout from origin/main and restart the macOS stack."""
import argparse
import json
import os
import subprocess
import sys
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS_FILE = Path.home() / ".local/share/fly-terminal/update-status.json"
LABELS = (
    "ai.kruspe.fly-terminal.caddy",
    "ai.kruspe.fly-terminal.ttyd",
    "ai.kruspe.fly-terminal.browser",
)
SAFE_GENERATED_BASENAMES = {".DS_Store"}
DEPLOYMENT_FILES = {"macos/Caddyfile", "macos/gateway/admin.html"}


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

    def _tracked_changes(self):
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=no"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError("Не удалось проверить локальные изменения")
        changes = []
        for raw_line in (result.stdout or "").splitlines():
            if not raw_line.strip():
                continue
            path = raw_line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1].strip()
            if path.startswith('"') and path.endswith('"'):
                path = path[1:-1]
            changes.append(path)
        return changes

    def _clean_safe_generated_changes(self):
        changes = self._tracked_changes()
        safe = [path for path in changes if Path(path).name in SAFE_GENERATED_BASENAMES]
        for path in safe:
            result = subprocess.run(
                ["git", "restore", "--worktree", "--staged", "--", path],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=10,
            )
            # If upstream has already removed the file, restore can legitimately fail
            # after fetch. Removing the local generated file is safe in that case.
            if result.returncode != 0:
                try:
                    target = REPO_ROOT / path
                    if target.name in SAFE_GENERATED_BASENAMES and target.exists():
                        target.unlink()
                except OSError:
                    pass
        # git pull --ff-only preserves local edits and refuses to overwrite files
        # changed upstream. Let Git check conflicts instead of blocking every
        # update merely because the local deployment has custom configuration.

    def restart_stack(self):
        uid = subprocess.check_output(["id", "-u"], text=True).strip()
        domain = f"gui/{uid}"
        for label in LABELS:
            self.run(f"restart-{label}", ["launchctl", "kickstart", "-k", f"{domain}/{label}"], timeout=30)
        for port in (8080, 8081, 7682, 7683):
            deadline = time.monotonic() + 30
            while True:
                probe = subprocess.run(
                    ["sh", "-c", f"lsof -nP -iTCP:{port} -sTCP:LISTEN"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False, timeout=10,
                )
                if probe.returncode == 0:
                    self.entries.append({"time": now(), "step": f"check-port-{port}", "ok": True, "message": f"port {port} is listening", "output": (probe.stdout or "")[-4000:]})
                    self.write("running", f"Порт {port} готов", f"check-port-{port}")
                    break
                if time.monotonic() >= deadline:
                    self.ok = False
                    self.entries.append({"time": now(), "step": f"check-port-{port}", "ok": False, "message": f"port {port} did not become ready"})
                    self.write("failed", f"Порт {port} не готов", f"check-port-{port}")
                    raise RuntimeError(f"port {port} did not become ready")
                time.sleep(1)

    def pull_preserving_deployment(self):
        """Merge local deployment overrides, retaining a durable Git backup."""
        changed = set(self._tracked_changes())
        upstream = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD", "origin/main"],
            cwd=REPO_ROOT, text=True,
        ).splitlines()
        paths = sorted(changed.intersection(upstream).intersection(DEPLOYMENT_FILES))
        if not paths:
            self.run("git-pull", ["git", "pull", "--ff-only", "origin", "main"], timeout=90)
            return

        # Check before stashing: an actual content conflict must leave the live
        # configuration untouched, rather than insert Git conflict markers.
        staged = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only"], cwd=REPO_ROOT, text=True,
        ).splitlines()
        with tempfile.TemporaryDirectory(prefix="fly-update-merge-") as directory:
            for path in paths:
                local = REPO_ROOT / path
                if path in staged or not local.is_file() or local.is_symlink():
                    self.preflight_failure(f"Требуется ручное сохранение локальных изменений: {path}")
                blobs = []
                for index, revision in enumerate((None, "HEAD", "origin/main")):
                    target = Path(directory) / str(index)
                    if revision is None:
                        target.write_bytes(local.read_bytes())
                    else:
                        result = subprocess.run(
                            ["git", "show", f"{revision}:{path}"], cwd=REPO_ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                        )
                        if result.returncode:
                            self.preflight_failure(f"Не удалось совместить локальные настройки: {path}")
                        target.write_bytes(result.stdout)
                    blobs.append(str(target))
                result = subprocess.run(
                    ["git", "merge-file", "-p", *blobs], cwd=REPO_ROOT,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                )
                if result.returncode:
                    self.preflight_failure(f"Конфликт локальных настроек с обновлением: {path}. Настройки сохранены; требуется ручное объединение.")

        self.run("backup-config", ["git", "stash", "push", "-m", f"Fly Terminal deployment backup {now()}", "--", *paths])
        backup = subprocess.check_output(["git", "rev-parse", "stash@{0}"], cwd=REPO_ROOT, text=True).strip()
        try:
            self.run("git-pull", ["git", "pull", "--ff-only", "origin", "main"], timeout=90)
        finally:
            # Restore even if pull fails. Keep the stash as a recoverable backup.
            restored = subprocess.run(
                ["git", "stash", "apply", backup], cwd=REPO_ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False, timeout=30,
            )
            self.entries.append({"time": now(), "step": "restore-config", "ok": restored.returncode == 0,
                                 "message": f"deployment backup: {backup}", "output": restored.stdout[-4000:]})
            if restored.returncode:
                # Never leave conflict markers in files used by running services.
                self.run("restore-config", ["git", "restore", f"--source={backup}", "--worktree", "--", *paths])
                self.run("restore-index", ["git", "reset", "HEAD", "--", *paths])
                self.preflight_failure(f"Не удалось восстановить настройки после обновления. Исходные файлы восстановлены; резервная копия Git: {backup}")

    def preflight_failure(self, message):
        self.ok = False
        self.entries.append({"time": now(), "step": "preflight", "ok": False, "message": message})
        self.write("failed", message, "preflight")
        raise RuntimeError(message)

    def execute(self):
        # Fetch first: this lets the updater know the latest upstream state before
        # deciding whether a local generated macOS artifact is safe to discard.
        self.run("git-fetch", ["git", "fetch", "origin", "main"], timeout=90)
        self.write("running", "Проверяю локальные изменения", "preflight")
        self._clean_safe_generated_changes()
        self.pull_preserving_deployment()
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
        # Preserve the actual failing step instead of hiding it behind "fatal".
        try:
            current = json.loads(updater.status_file.read_text(encoding="utf-8"))
        except Exception:
            current = {}
        if current.get("state") == "failed":
            updater.write("failed", current.get("summary") or str(exc), current.get("step") or "fatal")
        else:
            updater.entries.append({"time": now(), "step": "fatal", "ok": False, "message": str(exc)})
            updater.write("failed", "Обновление остановлено с ошибкой", "fatal")
        return 1


if __name__ == "__main__":
    sys.exit(main())
