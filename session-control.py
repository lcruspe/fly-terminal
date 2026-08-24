#!/usr/bin/env python3
import json
import os
import re
import base64
import hashlib
import mimetypes
import plistlib
import sqlite3
import shlex
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit


SESSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")
CODEX_ANSWER_END_RE = re.compile(r"^\s*─+\s+Worked for\b")
CODEX_ANSWER_START_RE = re.compile(r"^\s*─{8,}\s*$")
MAX_UPLOAD_BYTES = int(os.environ.get("FLY_TERMINAL_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_LAST_ANSWER_CHARS = int(os.environ.get("FLY_TERMINAL_LAST_ANSWER_MAX_CHARS", str(1024 * 1024)))
UPLOAD_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")
DOCUMENTS_DIR = Path(os.environ.get("FLY_TERMINAL_DOCUMENTS_DIR", str(Path.home() / "Documents"))).expanduser()
BROWSER_DOCUMENTS_DIR = "/config/Documents"
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
UI_PREFERENCES_FILE = Path(os.environ.get(
    "FLY_TERMINAL_UI_PREFERENCES_FILE",
    str(Path.home() / ".local/share/fly-terminal/ui-preferences.json"),
)).expanduser()
UI_PREFERENCES_LOCK = threading.Lock()
VALID_UI_THEMES = frozenset({
    "paper", "linen", "ledger", "harbor", "sage",
    "graphite", "ink", "midnight", "nord", "forest",
})
HAPP_VPN_SERVICE = os.environ.get("FLY_TERMINAL_HAPP_SERVICE", "Happ Plus")
HAPP_RECONNECT_LOCK = threading.Lock()
HAPP_PREFERENCES = Path.home() / "Library/Group Containers/group.su.ffg.happ.plus/Library/Preferences/group.su.ffg.happ.plus.plist"
HAPP_CACHE_DIR = Path.home() / "Library/Containers/su.ffg.happ.plus/Data/Library/Caches/su.ffg.happ.plus/fsCachedData"
HAPP_CACHE_DB = HAPP_CACHE_DIR.parent / "Cache.db"

TOOL_ERROR_MESSAGES = {
    "invalid_json": "Сервер получил некорректный запрос. Обновите страницу и повторите действие.",
    "not_found": "Запрошенная функция недоступна в текущей версии Fly Terminal.",
    "recovery_already_running": "Восстановление Chromium уже выполняется.",
    "recovery_script_missing": "Не найден штатный скрипт восстановления Chromium. Обновите Fly Terminal и повторите действие.",
    "recovery_start_failed": "Не удалось запустить восстановление Chromium.",
    "update_already_running": "Обновление Fly Terminal уже выполняется.",
    "update_script_missing": "Не найден штатный скрипт обновления. Обновите установку Fly Terminal вручную и повторите действие.",
    "update_start_failed": "Не удалось запустить обновление Fly Terminal.",
    "invalid_theme": "Выбрана неизвестная тема оформления.",
    "ui_preferences_write_failed": "Не удалось сохранить тему оформления.",
    "reconnect_already_running": "Переподключение Happ уже выполняется.",
    "happ_service_unavailable": "Системная служба Happ недоступна. Убедитесь, что Happ Plus установлен и запущен.",
    "happ_disconnect_failed": "Не удалось отключить текущее VPN-соединение Happ.",
    "happ_disconnect_timeout": "Happ не успел отключить VPN-соединение за отведённое время.",
    "happ_connect_failed": "Не удалось запустить VPN-соединение Happ.",
    "happ_connect_timeout": "Happ не подключился к VPN за отведённое время.",
    "happ_location_not_found": "Выбранная локация Happ больше недоступна. Обновите список и выберите локацию заново.",
    "happ_subscription_not_found": "Выбранная подписка Happ больше недоступна. Обновите список подписок и повторите действие.",
    "happ_action_already_running": "Другая операция Happ уже выполняется. Дождитесь её завершения.",
    "happ_location_switch_failed": "Не удалось переключить локацию Happ.",
    "payload_too_large": "Размер запроса превышает допустимый лимит.",
    "documents_unavailable": "Не удалось открыть папку Documents виртуальной машины.",
    "documents_list_failed": "Не удалось получить список файлов из папки Documents.",
    "file_name_invalid": "Некорректное имя файла.",
    "file_data_invalid": "Не удалось прочитать содержимое выбранного файла.",
    "file_too_large": "Файл превышает допустимый размер загрузки.",
    "file_write_failed": "Не удалось сохранить файл в папку Documents.",
    "file_not_found": "Файл не найден в папке Documents.",
    "file_access_denied": "Доступ к выбранному файлу запрещён.",
    "file_read_failed": "Не удалось скачать выбранный файл.",
}


def _happ_config_id(config):
    encoded = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def happ_current_config():
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
        return config if isinstance(config, dict) else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}


def happ_current_location():
    return str(happ_current_config().get("remarks") or "").strip()


def _cached_value_bytes(value):
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    return b""


def _happ_cached_response_body(receiver_data, is_data_on_fs):
    raw = _cached_value_bytes(receiver_data)
    if not raw:
        return b""

    file_name = ""
    try:
        file_name = raw.decode("utf-8").strip("\x00\r\n ")
    except UnicodeDecodeError:
        pass

    should_read_file = bool(is_data_on_fs)
    if not should_read_file and file_name and len(file_name) < 256:
        candidate = HAPP_CACHE_DIR / file_name
        should_read_file = candidate.is_file()

    if should_read_file and file_name and Path(file_name).name == file_name:
        try:
            return (HAPP_CACHE_DIR / file_name).read_bytes()
        except OSError:
            return b""
    return raw


def _parse_happ_subscription_configs(raw_body):
    if not raw_body:
        return []
    try:
        payload = json.loads(raw_body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []

    if isinstance(payload, dict):
        for key in ("configs", "servers", "items"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        return []

    configs = []
    for config in payload:
        if not isinstance(config, dict) or not isinstance(config.get("outbounds"), list):
            continue
        label = str(config.get("remarks") or "").strip()
        if not label:
            continue
        configs.append(config)
    return configs


def _resolve_plist_archive(blob):
    raw = _cached_value_bytes(blob)
    if not raw:
        return None
    try:
        archive = plistlib.loads(raw)
    except (plistlib.InvalidFileException, ValueError, TypeError):
        return None
    if not isinstance(archive, dict) or not isinstance(archive.get("$objects"), list):
        return archive

    objects = archive["$objects"]

    def resolve(value, stack=frozenset()):
        if isinstance(value, plistlib.UID):
            index = value.data
            if index < 0 or index >= len(objects) or index in stack:
                return None
            return resolve(objects[index], stack | {index})
        if isinstance(value, list):
            return [resolve(item, stack) for item in value]
        if isinstance(value, dict):
            if "NS.keys" in value and "NS.objects" in value:
                keys = resolve(value["NS.keys"], stack)
                values = resolve(value["NS.objects"], stack)
                if isinstance(keys, list) and isinstance(values, list):
                    return {
                        str(key): item
                        for key, item in zip(keys, values)
                        if key is not None
                    }
            if "NS.objects" in value and set(value).issubset({"NS.objects", "$class"}):
                return resolve(value["NS.objects"], stack)
            return {
                str(key): resolve(item, stack)
                for key, item in value.items()
                if key != "$class"
            }
        return value

    return resolve(archive.get("$top", archive))


def _find_named_value(value, names):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold().replace("_", "-")
            if normalized in names and isinstance(item, (str, bytes, bytearray)):
                return item
        for item in value.values():
            found = _find_named_value(item, names)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_named_value(item, names)
            if found not in (None, ""):
                return found
    return None


def _normalize_happ_subscription_title(value):
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return ""
    title = str(value or "").strip()
    if not title:
        return ""

    if " " not in title and len(title) >= 8 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", title):
        padded = title + "=" * (-len(title) % 4)
        try:
            decoded_bytes = base64.b64decode(padded, altchars=b"-_", validate=True)
            decoded = decoded_bytes.decode("utf-8").strip()
            standard = base64.b64encode(decoded_bytes).decode("ascii").rstrip("=")
            urlsafe = base64.urlsafe_b64encode(decoded_bytes).decode("ascii").rstrip("=")
            if decoded and title.rstrip("=") in {standard, urlsafe} and all(char.isprintable() for char in decoded):
                title = decoded
        except (ValueError, UnicodeDecodeError):
            pass
    return title[:80]


def _happ_subscription_title(response_object, request_key):
    archive = _resolve_plist_archive(response_object)
    title = _normalize_happ_subscription_title(
        _find_named_value(archive, {"profile-title", "profiletitle"})
    )
    if title:
        return title

    try:
        parsed = urlsplit(str(request_key or ""))
        host = parsed.hostname or ""
    except ValueError:
        host = ""
    return host or "Подписка Happ"


def _happ_locations_from_configs(configs):
    locations = []
    seen = set()
    for config in configs:
        location_id = _happ_config_id(config)
        if location_id in seen:
            continue
        seen.add(location_id)
        locations.append({
            "id": location_id,
            "label": str(config.get("remarks") or "").strip(),
            "config": config,
        })
    return locations


def _legacy_happ_subscriptions():
    """Compatibility fallback for installations where Cache.db cannot be read."""
    try:
        cache_files = sorted(HAPP_CACHE_DIR.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError:
        return []

    subscriptions = []
    fingerprints = set()
    for cache_file in cache_files:
        try:
            configs = _parse_happ_subscription_configs(cache_file.read_bytes())
        except OSError:
            continue
        locations = _happ_locations_from_configs(configs)
        if not locations:
            continue
        fingerprint = hashlib.sha256("|".join(item["id"] for item in locations).encode("utf-8")).hexdigest()
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        subscriptions.append({
            "id": f"legacy-{fingerprint[:16]}",
            "label": "Подписка Happ",
            "locations": locations,
        })
    return subscriptions


def happ_subscriptions():
    """Return every cached Happ subscription and its locations without exposing subscription URLs."""
    if not HAPP_CACHE_DB.is_file():
        subscriptions = _legacy_happ_subscriptions()
    else:
        subscriptions = []
        seen_subscriptions = set()
        connection = None
        try:
            database_uri = f"file:{quote(str(HAPP_CACHE_DB), safe='/')}?mode=ro"
            connection = sqlite3.connect(database_uri, uri=True, timeout=1)
            receiver_columns = {
                str(row[1]).casefold(): str(row[1])
                for row in connection.execute("PRAGMA table_info(cfurl_cache_receiver_data)")
            }
            response_columns = {
                str(row[1]).casefold(): str(row[1])
                for row in connection.execute("PRAGMA table_info(cfurl_cache_response)")
            }
            if "isdataonfs" in receiver_columns:
                fs_expr = f'd."{receiver_columns["isdataonfs"]}"'
            elif "isdataonfs" in response_columns:
                fs_expr = f'r."{response_columns["isdataonfs"]}"'
            else:
                fs_expr = "0"

            rows = connection.execute(
                f"""
                SELECT r.entry_ID, r.request_key, r.time_stamp,
                       {fs_expr} AS is_data_on_fs,
                       d.receiver_data, b.response_object
                FROM cfurl_cache_response AS r
                JOIN cfurl_cache_receiver_data AS d USING (entry_ID)
                LEFT JOIN cfurl_cache_blob_data AS b USING (entry_ID)
                ORDER BY r.time_stamp DESC
                """
            )
            for entry_id, request_key, _timestamp, is_data_on_fs, receiver_data, response_object in rows:
                body = _happ_cached_response_body(receiver_data, is_data_on_fs)
                configs = _parse_happ_subscription_configs(body)
                locations = _happ_locations_from_configs(configs)
                if not locations:
                    continue

                stable_key = str(request_key or f"cache-entry:{entry_id}")
                subscription_id = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:24]
                if subscription_id in seen_subscriptions:
                    continue
                seen_subscriptions.add(subscription_id)
                subscriptions.append({
                    "id": subscription_id,
                    "label": _happ_subscription_title(response_object, request_key),
                    "locations": locations,
                })
        except (OSError, sqlite3.Error):
            subscriptions = []
        finally:
            if connection is not None:
                connection.close()

        if not subscriptions:
            subscriptions = _legacy_happ_subscriptions()

    label_counts = {}
    for subscription in subscriptions:
        base_label = subscription.get("label") or "Подписка Happ"
        count = label_counts.get(base_label, 0) + 1
        label_counts[base_label] = count
        if count > 1:
            subscription["label"] = f"{base_label} ({count})"
    return subscriptions


def happ_subscription_catalog():
    subscriptions = happ_subscriptions()
    current_config = happ_current_config()
    current_label = str(current_config.get("remarks") or "").strip()
    current_config_id = _happ_config_id(current_config) if current_config else ""
    current_subscription_id = ""
    current_location_id = ""

    if current_config_id:
        for subscription in subscriptions:
            location = next((item for item in subscription["locations"] if item["id"] == current_config_id), None)
            if location:
                current_subscription_id = subscription["id"]
                current_location_id = location["id"]
                break

    if not current_subscription_id and current_label:
        matches = [
            (subscription, location)
            for subscription in subscriptions
            for location in subscription["locations"]
            if location["label"] == current_label
        ]
        if len(matches) == 1:
            current_subscription_id = matches[0][0]["id"]
            current_location_id = matches[0][1]["id"]

    current_subscription_label = next(
        (item["label"] for item in subscriptions if item["id"] == current_subscription_id),
        "",
    )
    return {
        "subscriptions": subscriptions,
        "current": current_label,
        "currentSubscriptionId": current_subscription_id,
        "currentSubscription": current_subscription_label,
        "currentLocationId": current_location_id,
    }


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


def humanize_tool_error_payload(payload):
    if not isinstance(payload, dict) or payload.get("ok") is not False:
        return payload

    error_code = payload.get("error")
    message = TOOL_ERROR_MESSAGES.get(error_code)
    if not message:
        return payload

    result = dict(payload)
    technical_details = str(result.get("details") or "").strip()
    if technical_details and technical_details != message:
        result["technicalDetails"] = technical_details
    result["details"] = message
    result["message"] = message
    result.setdefault("summary", message)
    return result



def documents_root():
    """Return the resolved VM Documents directory, creating it when needed."""
    try:
        DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
        return DOCUMENTS_DIR.resolve(strict=True), ""
    except OSError as exc:
        return None, str(exc)


def mirror_document_to_browser(source_path):
    """Copy one uploaded document into the persistent Chromium profile volume."""
    container = browser_container_name()
    destination = f"{BROWSER_DOCUMENTS_DIR}/{source_path.name}"
    commands = (
        ["docker", "exec", "-u", "root", container, "mkdir", "-p", BROWSER_DOCUMENTS_DIR],
        ["docker", "cp", str(source_path), f"{container}:{destination}"],
        [
            "docker", "exec", "-u", "root", container,
            "sh", "-c", 'chown abc:dialout "$1" && chmod u+rw,go+r "$1"',
            "sh", destination,
        ],
    )
    try:
        for command in commands:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=15,
            )
            if result.returncode != 0:
                return False, result.stderr.strip() or f"exit_{result.returncode}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return True, ""


def normalize_document_file_name(value):
    """Accept one plain UTF-8 filename; never accept a path."""
    name = str(value or "").strip()
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or len(name.encode("utf-8")) > 240
    ):
        return ""
    return name


def list_document_files():
    root, root_error = documents_root()
    if root_error:
        return None, "documents_unavailable", root_error

    files = []
    try:
        for entry in root.iterdir():
            try:
                if entry.is_symlink() or not entry.is_file():
                    continue
                resolved = entry.resolve(strict=True)
                if resolved.parent != root:
                    continue
                stat = entry.stat()
            except (OSError, RuntimeError):
                continue
            files.append({
                "name": entry.name,
                "size": stat.st_size,
                "modifiedAt": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
            })
    except OSError as exc:
        return None, "documents_list_failed", str(exc)

    files.sort(key=lambda item: (item["modifiedAt"], item["name"].casefold()), reverse=True)
    return files, "", ""


def reserve_document_file(root, file_name):
    """Atomically reserve a non-existing filename; collisions get ' (N)' suffixes."""
    original = Path(file_name)
    suffix = original.suffix
    stem = original.name[:-len(suffix)] if suffix else original.name
    for index in range(10000):
        candidate_name = original.name if index == 0 else f"{stem} ({index + 1}){suffix}"
        candidate = root / candidate_name
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            return candidate, fd
        except FileExistsError:
            continue
    raise OSError("too_many_name_collisions")


def open_document_download(file_name):
    """Open one regular Documents file without following a final symlink."""
    name = normalize_document_file_name(file_name)
    if not name:
        return None, "", "file_name_invalid", ""

    root, root_error = documents_root()
    if root_error:
        return None, "", "documents_unavailable", root_error

    root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        root_fd = os.open(root, root_flags)
    except OSError as exc:
        return None, "", "documents_unavailable", str(exc)

    try:
        file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            file_fd = os.open(name, file_flags, dir_fd=root_fd)
        except FileNotFoundError:
            return None, "", "file_not_found", ""
        except OSError as exc:
            return None, "", "file_access_denied", str(exc)
    finally:
        os.close(root_fd)

    try:
        file_stat = os.fstat(file_fd)
        if not stat.S_ISREG(file_stat.st_mode):
            os.close(file_fd)
            return None, "", "file_access_denied", "not_regular_file"
        source = os.fdopen(file_fd, "rb")
    except OSError as exc:
        try:
            os.close(file_fd)
        except OSError:
            pass
        return None, "", "file_read_failed", str(exc)

    return source, name, "", ""


def operation_failure_message(operation, step):
    step = str(step or "")
    if operation == "recovery":
        if step in {"docker-info", "docker-system-df"}:
            return "Docker недоступен. Проверьте, что Colima и Docker запущены."
        if step.startswith("colima-"):
            return "Не удалось перезапустить Colima. Проверьте состояние виртуальной машины Docker."
        if step == "launch-browser":
            return "Не удалось запустить Chromium. Проверьте Docker и контейнер браузера."
        if step.startswith("launchctl-bootstrap-"):
            return "Не удалось загрузить одну из системных служб Fly Terminal."
        if step == "wait-for-ports":
            return "Не все компоненты Fly Terminal запустились за отведённое время."
        if step == "http-browser":
            return "Chromium запущен, но его веб-интерфейс недоступен."
        if step == "ws-browser":
            return "Chromium запущен, но WebSocket-соединение браузера недоступно."
        if step == "ws-terminal":
            return "Терминальный WebSocket не восстановился."
        if step.startswith("launchctl-"):
            return "Не удалось проверить состояние одной из системных служб Fly Terminal."
        if step == "docker-ps-browser":
            return "Не удалось проверить состояние контейнера Chromium."
        if step == "disk-space":
            return "Не удалось проверить свободное место на диске."
        return "Восстановление Chromium завершилось с ошибкой. Подробности сохранены в журнале."

    if operation == "update":
        if step == "git-status":
            return "Обновление остановлено: есть локальные изменения или не удалось проверить состояние репозитория."
        if step == "git-fetch":
            return "Не удалось получить обновления из origin/main. Проверьте доступ к GitHub."
        if step == "git-pull":
            return "Не удалось применить обновление из origin/main. Проверьте состояние локальной ветки."
        if step.startswith("restart-"):
            return "Не удалось перезапустить одну из системных служб Fly Terminal."
        if step.startswith("check-port-"):
            return "После обновления один из компонентов Fly Terminal не запустился за отведённое время."
        return "Обновление Fly Terminal остановлено из-за ошибки. Подробности сохранены в журнале."

    return "Операция завершилась с ошибкой."


def humanize_operation_status(status, operation):
    if not isinstance(status, dict):
        return status

    result = dict(status)
    entries = []
    for entry in status.get("entries") or []:
        if not isinstance(entry, dict):
            entries.append(entry)
            continue
        normalized = dict(entry)
        if normalized.get("ok") is False:
            technical_message = str(normalized.get("message") or "").strip()
            if technical_message:
                normalized["technicalMessage"] = technical_message
            normalized["message"] = operation_failure_message(operation, normalized.get("step"))
        entries.append(normalized)
    result["entries"] = entries

    if result.get("state") == "failed":
        latest_failure = next(
            (entry for entry in reversed(entries) if isinstance(entry, dict) and entry.get("ok") is False),
            None,
        )
        if latest_failure:
            result["summary"] = latest_failure.get("message") or result.get("summary")
    return result


def send_json(handler, status_code, payload):
    payload = humanize_tool_error_payload(payload)
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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
    return humanize_operation_status(status, "recovery")


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
    return humanize_operation_status(status, "update")


def read_ui_preferences():
    with UI_PREFERENCES_LOCK:
        if not UI_PREFERENCES_FILE.exists():
            return {"ok": True, "theme": None}
        try:
            payload = json.loads(UI_PREFERENCES_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"ok": True, "theme": None}

    theme = str(payload.get("theme") or "").strip()
    if theme not in VALID_UI_THEMES:
        theme = ""
    return {"ok": True, "theme": theme or None}


def write_ui_preferences(theme):
    payload = {
        "theme": theme,
        "updatedAt": datetime.now().isoformat(),
    }
    UI_PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = UI_PREFERENCES_FILE.with_name(f"{UI_PREFERENCES_FILE.name}.tmp")
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with UI_PREFERENCES_LOCK:
        temp_path.write_text(serialized, encoding="utf-8")
        os.replace(temp_path, UI_PREFERENCES_FILE)


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

        if self.path == "/api/ui/preferences":
            send_json(self, 200, read_ui_preferences())
            return

        if self.path == "/api/files/list":
            self._handle_documents_list()
            return

        if urlsplit(self.path).path == "/api/files/download":
            self._handle_document_download()
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
            payload = {
                "ok": not error,
                "service": HAPP_VPN_SERVICE,
                "state": state,
                "location": happ_current_location(),
            }
            if error:
                payload.update({"error": "happ_service_unavailable", "details": error})
            send_json(self, 200 if not error else 503, payload)
            return

        if self.path in {"/api/vpn/happ/locations", "/api/vpn/happ/subscriptions"}:
            catalog = happ_subscription_catalog()
            public_subscriptions = [
                {
                    "id": subscription["id"],
                    "label": subscription["label"],
                    "locations": [
                        {"id": location["id"], "label": location["label"]}
                        for location in subscription["locations"]
                    ],
                }
                for subscription in catalog["subscriptions"]
            ]
            send_json(self, 200, {
                "ok": True,
                "current": catalog["current"],
                "currentSubscriptionId": catalog["currentSubscriptionId"],
                "currentSubscription": catalog["currentSubscription"],
                "currentLocationId": catalog["currentLocationId"],
                "subscriptions": public_subscriptions,
                "configured": bool(public_subscriptions),
            })
            return

        send_json(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        if self.path == "/api/ui/preferences":
            self._handle_ui_preferences()
        elif self.path == "/api/session/terminate":
            self._handle_terminate()
        elif self.path == "/api/session/info":
            self._handle_info()
        elif self.path == "/api/session/last-answer":
            self._handle_last_answer()
        elif self.path == "/api/files/upload":
            self._handle_document_upload()
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

    def _handle_ui_preferences(self):
        payload, error = self._read_json_body()
        if error:
            send_json(self, 400, {"ok": False, "error": error})
            return

        theme = str(payload.get("theme") or "").strip()
        if theme not in VALID_UI_THEMES:
            send_json(self, 400, {"ok": False, "error": "invalid_theme"})
            return

        try:
            write_ui_preferences(theme)
        except OSError as exc:
            send_json(self, 500, {"ok": False, "error": "ui_preferences_write_failed", "details": str(exc)})
            return

        send_json(self, 200, {"ok": True, "theme": theme})

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

    def _handle_documents_list(self):
        files, error_code, technical_details = list_document_files()
        if error_code:
            send_json(
                self,
                500,
                {"ok": False, "error": error_code, "details": technical_details},
            )
            return
        send_json(
            self,
            200,
            {
                "ok": True,
                "directory": "Documents",
                "maxUploadBytes": MAX_UPLOAD_BYTES,
                "files": files,
            },
        )

    def _handle_document_upload(self):
        max_body = int(MAX_UPLOAD_BYTES * 1.4) + 65536
        payload, error = self._read_json_body(max_body)
        if error:
            status = 413 if error == "payload_too_large" else 400
            send_json(self, status, {"ok": False, "error": error})
            return

        file_name = normalize_document_file_name(payload.get("fileName"))
        if not file_name:
            send_json(self, 400, {"ok": False, "error": "file_name_invalid"})
            return

        data_b64 = payload.get("data")
        if not isinstance(data_b64, str):
            send_json(self, 400, {"ok": False, "error": "file_data_invalid"})
            return
        try:
            content = base64.b64decode(data_b64, validate=True)
        except (ValueError, TypeError):
            send_json(self, 400, {"ok": False, "error": "file_data_invalid"})
            return
        if len(content) > MAX_UPLOAD_BYTES:
            send_json(self, 413, {"ok": False, "error": "file_too_large"})
            return

        root, root_error = documents_root()
        if root_error:
            send_json(self, 500, {"ok": False, "error": "documents_unavailable", "details": root_error})
            return

        target_path = None
        fd = None
        try:
            target_path, fd = reserve_document_file(root, file_name)
            with os.fdopen(fd, "wb") as target_file:
                fd = None
                target_file.write(content)
                target_file.flush()
                os.fsync(target_file.fileno())
        except OSError as exc:
            if fd is not None:
                os.close(fd)
            if target_path is not None:
                try:
                    target_path.unlink(missing_ok=True)
                except OSError:
                    pass
            send_json(self, 500, {"ok": False, "error": "file_write_failed", "details": str(exc)})
            return

        saved_name = target_path.name
        browser_mirrored, browser_mirror_error = mirror_document_to_browser(target_path)
        send_json(
            self,
            201,
            {
                "ok": True,
                "name": saved_name,
                "originalName": file_name,
                "renamed": saved_name != file_name,
                "bytes": len(content),
                "directory": "Documents",
                "browserMirrored": browser_mirrored,
                "browserMirrorError": browser_mirror_error,
            },
        )

    def _handle_document_download(self):
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        file_name = (query.get("name") or [""])[0]
        source, safe_name, error_code, technical_details = open_document_download(file_name)
        if error_code:
            if error_code == "file_not_found":
                status = 404
            elif error_code == "file_name_invalid":
                status = 400
            elif error_code == "file_access_denied":
                status = 403
            else:
                status = 500
            send_json(
                self,
                status,
                {"ok": False, "error": error_code, "details": technical_details},
            )
            return

        with source:
            try:
                file_stat = os.fstat(source.fileno())
            except OSError as exc:
                send_json(self, 500, {"ok": False, "error": "file_read_failed", "details": str(exc)})
                return

            mime_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
            suffix = Path(safe_name).suffix
            safe_suffix = suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,12}", suffix or "") else ""
            fallback_name = f"download{safe_suffix}"
            encoded_name = quote(safe_name, safe="")
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Disposition", f"attachment; filename=\"{fallback_name}\"; filename*=UTF-8''{encoded_name}")
            self.send_header("Content-Length", str(file_stat.st_size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                while True:
                    chunk = source.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

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

        subscription_id = str(payload.get("subscriptionId") or "")
        location_id = str(payload.get("locationId") or "")
        catalog = happ_subscription_catalog()
        subscriptions = catalog["subscriptions"]

        subscription = None
        if subscription_id:
            subscription = next((item for item in subscriptions if item["id"] == subscription_id), None)
            if not subscription:
                send_json(self, 404, {"ok": False, "error": "happ_subscription_not_found"})
                return
            candidates = subscription["locations"]
        else:
            candidates = [location for item in subscriptions for location in item["locations"]]

        location = next((item for item in candidates if item["id"] == location_id), None)
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
            send_json(self, 200, {
                "ok": True,
                "service": HAPP_VPN_SERVICE,
                "state": final_state,
                "subscriptionId": subscription["id"] if subscription else "",
                "subscription": subscription["label"] if subscription else "",
                "location": happ_current_location() or location["label"],
            })
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
