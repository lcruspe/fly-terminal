#!/usr/bin/env python3
from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 anchor, found {count}")
    return text.replace(old, new, 1)


session_path = Path("session-control.py")
session = session_path.read_text(encoding="utf-8")
session = replace_once(
    session,
    "import os\nimport re\n",
    "import os\nimport posixpath\nimport re\n",
    "session import",
)
session = replace_once(
    session,
    'BROWSER_DOCUMENTS_DIR = "/config/Documents"\n',
    '''BROWSER_DOCUMENTS_DIR = "/config/Documents"\nCONTAINER_FILE_BROWSER_BLOCKED_ROOTS = ("/proc", "/sys", "/dev", "/run")\nCONTAINER_FILE_BROWSER_MAX_ENTRIES = int(os.environ.get("FLY_TERMINAL_CONTAINER_FILE_MAX_ENTRIES", "2000"))\nCONTAINER_FILE_BROWSER_TIMEOUT_SECONDS = int(os.environ.get("FLY_TERMINAL_CONTAINER_FILE_TIMEOUT_SECONDS", "15"))\n''',
    "container constants",
)
session = replace_once(
    session,
    '    "file_read_failed": "Не удалось скачать выбранный файл.",\n',
    '''    "file_read_failed": "Не удалось скачать выбранный файл.",\n    "container_unavailable": "Контейнер Chromium недоступен. Убедитесь, что браузерный контейнер запущен.",\n    "container_path_invalid": "Некорректный путь в файловой системе контейнера.",\n    "container_path_blocked": "Этот системный каталог недоступен для просмотра.",\n    "container_directory_not_found": "Каталог в контейнере больше не существует.",\n    "container_directory_access_denied": "Нет доступа к выбранному каталогу контейнера.",\n    "container_list_failed": "Не удалось получить содержимое каталога контейнера.",\n    "container_file_not_found": "Выбранный файл в контейнере больше не существует.",\n    "container_file_access_denied": "Нет доступа к выбранному файлу контейнера.",\n    "container_file_read_failed": "Не удалось скачать выбранный файл из контейнера.",\n''',
    "container error messages",
)

helper_anchor = '''def docker_exec(args, **kwargs):\n    return subprocess.run(\n        ["docker", "exec", browser_container_name(), *args],\n        stdout=kwargs.pop("stdout", subprocess.PIPE),\n        stderr=kwargs.pop("stderr", subprocess.PIPE),\n        text=kwargs.pop("text", True),\n        check=False,\n        **kwargs,\n    )\n\n\n'''
helper_block = r'''def normalize_container_browser_path(value):
    """Normalize one absolute POSIX path used only inside the Chromium container."""
    raw = str(value or "/").strip()
    if (
        not raw
        or not raw.startswith("/")
        or any(ord(char) < 32 or ord(char) == 127 for char in raw)
        or len(raw.encode("utf-8")) > 4096
    ):
        return ""
    normalized = posixpath.normpath(raw)
    return "/" + normalized.lstrip("/")


def container_browser_path_blocked(path):
    path = normalize_container_browser_path(path)
    if not path:
        return False
    return any(path == root or path.startswith(root + "/") for root in CONTAINER_FILE_BROWSER_BLOCKED_ROOTS)


CONTAINER_DIRECTORY_LIST_SCRIPT = r"""
import datetime
import json
import os
import stat
import sys

BLOCKED = ("/proc", "/sys", "/dev", "/run")
MAX_ENTRIES = int(sys.argv[2])
requested = os.path.normpath(sys.argv[1])


def blocked(path):
    return any(path == root or path.startswith(root + "/") for root in BLOCKED)


def fail(code, details=""):
    print(json.dumps({"ok": False, "error": code, "details": details}, ensure_ascii=False))
    raise SystemExit(0)


real = os.path.realpath(requested)
if requested != real:
    fail("container_directory_access_denied", "symlink_path")
if blocked(real):
    fail("container_path_blocked")

try:
    root_stat = os.lstat(requested)
except FileNotFoundError:
    fail("container_directory_not_found")
except PermissionError as exc:
    fail("container_directory_access_denied", str(exc))
except OSError as exc:
    fail("container_list_failed", str(exc))

if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
    fail("container_directory_access_denied", "not_directory")

try:
    names = os.listdir(requested)
except PermissionError as exc:
    fail("container_directory_access_denied", str(exc))
except OSError as exc:
    fail("container_list_failed", str(exc))

entries = []
for name in names:
    full = os.path.join(requested, name)
    try:
        item_stat = os.lstat(full)
    except OSError:
        continue
    if stat.S_ISLNK(item_stat.st_mode):
        continue
    if stat.S_ISDIR(item_stat.st_mode):
        real_child = os.path.realpath(full)
        if blocked(real_child) or real_child != os.path.normpath(full):
            continue
        kind = "directory"
    elif stat.S_ISREG(item_stat.st_mode):
        kind = "file"
    else:
        continue
    entries.append({
        "name": name,
        "path": full if requested != "/" else "/" + name,
        "kind": kind,
        "size": item_stat.st_size if kind == "file" else None,
        "modifiedAt": datetime.datetime.fromtimestamp(
            item_stat.st_mtime, datetime.timezone.utc
        ).isoformat(),
    })

entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold()))
truncated = len(entries) > MAX_ENTRIES
entries = entries[:MAX_ENTRIES]
parent = None if requested == "/" else (os.path.dirname(requested.rstrip("/")) or "/")
print(json.dumps({
    "ok": True,
    "path": requested,
    "parent": parent,
    "entries": entries,
    "truncated": truncated,
}, ensure_ascii=False))
"""


CONTAINER_FILE_STREAM_SCRIPT = r"""
import json
import os
import stat
import sys

BLOCKED = ("/proc", "/sys", "/dev", "/run")
requested = os.path.normpath(sys.argv[1])
out = sys.stdout.buffer


def blocked(path):
    return any(path == root or path.startswith(root + "/") for root in BLOCKED)


def fail(code, details=""):
    out.write((json.dumps({"ok": False, "error": code, "details": details}, ensure_ascii=False) + "\n").encode("utf-8"))
    out.flush()
    raise SystemExit(0)


real = os.path.realpath(requested)
if requested != real:
    fail("container_file_access_denied", "symlink_path")
if blocked(real):
    fail("container_path_blocked")

flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
try:
    fd = os.open(requested, flags)
except FileNotFoundError:
    fail("container_file_not_found")
except PermissionError as exc:
    fail("container_file_access_denied", str(exc))
except OSError as exc:
    fail("container_file_read_failed", str(exc))

try:
    file_stat = os.fstat(fd)
    if not stat.S_ISREG(file_stat.st_mode):
        fail("container_file_access_denied", "not_regular_file")
    name = os.path.basename(requested) or "download"
    out.write((json.dumps({"ok": True, "name": name, "size": file_stat.st_size}, ensure_ascii=False) + "\n").encode("utf-8"))
    out.flush()
    while True:
        chunk = os.read(fd, 64 * 1024)
        if not chunk:
            break
        out.write(chunk)
finally:
    os.close(fd)
"""


def list_browser_container_directory(path):
    safe_path = normalize_container_browser_path(path)
    if not safe_path:
        return None, "container_path_invalid", ""
    if container_browser_path_blocked(safe_path):
        return None, "container_path_blocked", ""

    try:
        result = docker_exec(
            ["python3", "-c", CONTAINER_DIRECTORY_LIST_SCRIPT, safe_path, str(CONTAINER_FILE_BROWSER_MAX_ENTRIES)],
            timeout=CONTAINER_FILE_BROWSER_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "container_unavailable", str(exc)

    try:
        payload = json.loads((result.stdout or "").strip())
    except json.JSONDecodeError:
        details = (result.stderr or result.stdout or "").strip()
        return None, "container_unavailable" if result.returncode != 0 else "container_list_failed", details

    if not isinstance(payload, dict):
        return None, "container_list_failed", "invalid_payload"
    if payload.get("ok") is not True:
        return None, str(payload.get("error") or "container_list_failed"), str(payload.get("details") or "")
    return payload, "", ""


def open_browser_container_download(path):
    safe_path = normalize_container_browser_path(path)
    if not safe_path:
        return None, None, "container_path_invalid", ""
    if container_browser_path_blocked(safe_path):
        return None, None, "container_path_blocked", ""

    try:
        process = subprocess.Popen(
            ["docker", "exec", browser_container_name(), "python3", "-c", CONTAINER_FILE_STREAM_SCRIPT, safe_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return None, None, "container_unavailable", str(exc)

    try:
        header_line = process.stdout.readline(64 * 1024) if process.stdout else b""
        if not header_line:
            stderr = process.stderr.read().decode("utf-8", "replace").strip() if process.stderr else ""
            process.wait(timeout=2)
            return None, None, "container_unavailable", stderr
        metadata = json.loads(header_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        process.terminate()
        return None, None, "container_file_read_failed", str(exc)

    if metadata.get("ok") is not True:
        error_code = str(metadata.get("error") or "container_file_read_failed")
        details = str(metadata.get("details") or "")
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
        return None, None, error_code, details
    return process, metadata, "", ""


'''
session = replace_once(session, helper_anchor, helper_anchor + helper_block, "container helpers")

session = replace_once(
    session,
    '''        if urlsplit(self.path).path == "/api/files/download":\n            self._handle_document_download()\n            return\n\n        if self.path == "/api/browser/config":\n''',
    '''        if urlsplit(self.path).path == "/api/files/download":\n            self._handle_document_download()\n            return\n\n        if urlsplit(self.path).path == "/api/container/files/list":\n            self._handle_container_files_list()\n            return\n\n        if urlsplit(self.path).path == "/api/container/files/download":\n            self._handle_container_file_download()\n            return\n\n        if self.path == "/api/browser/config":\n''',
    "container GET routes",
)

handler_anchor = '''    def _handle_upload_image(self):\n'''
handler_block = '''    def _handle_container_files_list(self):\n        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)\n        path = (query.get("path") or ["/"])[0]\n        payload, error_code, technical_details = list_browser_container_directory(path)\n        if error_code:\n            if error_code == "container_directory_not_found":\n                status = 404\n            elif error_code in {"container_path_invalid"}:\n                status = 400\n            elif error_code in {"container_path_blocked", "container_directory_access_denied"}:\n                status = 403\n            elif error_code == "container_unavailable":\n                status = 503\n            else:\n                status = 500\n            send_json(self, status, {"ok": False, "error": error_code, "details": technical_details})\n            return\n        send_json(self, 200, payload)\n\n    def _handle_container_file_download(self):\n        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)\n        path = (query.get("path") or [""])[0]\n        process, metadata, error_code, technical_details = open_browser_container_download(path)\n        if error_code:\n            if error_code == "container_file_not_found":\n                status = 404\n            elif error_code == "container_path_invalid":\n                status = 400\n            elif error_code in {"container_path_blocked", "container_file_access_denied"}:\n                status = 403\n            elif error_code == "container_unavailable":\n                status = 503\n            else:\n                status = 500\n            send_json(self, status, {"ok": False, "error": error_code, "details": technical_details})\n            return\n\n        safe_name = str(metadata.get("name") or "download")\n        file_size = int(metadata.get("size") or 0)\n        mime_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"\n        suffix = Path(safe_name).suffix\n        safe_suffix = suffix if re.fullmatch(r"\\.[A-Za-z0-9]{1,12}", suffix or "") else ""\n        fallback_name = f"download{safe_suffix}"\n        encoded_name = quote(safe_name, safe="")\n\n        self.send_response(200)\n        self.send_header("Content-Type", mime_type)\n        self.send_header("Content-Disposition", f"attachment; filename=\\"{fallback_name}\\"; filename*=UTF-8''{encoded_name}")\n        self.send_header("Content-Length", str(file_size))\n        self.send_header("Cache-Control", "no-store")\n        self.send_header("X-Content-Type-Options", "nosniff")\n        self.send_header("Access-Control-Allow-Origin", "*")\n        self.end_headers()\n\n        try:\n            while True:\n                chunk = process.stdout.read(64 * 1024) if process.stdout else b""\n                if not chunk:\n                    break\n                self.wfile.write(chunk)\n        except (BrokenPipeError, ConnectionResetError):\n            pass\n        finally:\n            if process.stdout:\n                process.stdout.close()\n            if process.poll() is None:\n                process.terminate()\n            try:\n                process.wait(timeout=2)\n            except subprocess.TimeoutExpired:\n                process.kill()\n            if process.stderr:\n                process.stderr.close()\n\n'''
session = replace_once(session, handler_anchor, handler_block + handler_anchor, "container handlers")
session_path.write_text(session, encoding="utf-8")


index_path = Path("index.html")
index = index_path.read_text(encoding="utf-8")

css_anchor = '''    .settings-action .document-file-download {\n      min-height: 30px;\n      padding: 6px 8px;\n      width: auto;\n    }\n\n'''
css_block = '''    .container-file-dialog {\n      background: var(--panel-solid);\n      border: 1px solid var(--border);\n      border-radius: 12px;\n      box-shadow: var(--shadow);\n      color: var(--ink);\n      max-height: min(78vh, 680px);\n      padding: 0;\n      width: min(680px, calc(100vw - 28px));\n    }\n\n    .container-file-dialog::backdrop {\n      background: rgba(0, 0, 0, 0.44);\n      backdrop-filter: blur(2px);\n    }\n\n    .container-file-picker {\n      display: grid;\n      grid-template-rows: auto auto minmax(180px, 1fr) auto;\n      max-height: min(78vh, 680px);\n      min-height: min(560px, 78vh);\n    }\n\n    .container-file-picker-header,\n    .container-file-picker-toolbar,\n    .container-file-picker-footer {\n      align-items: center;\n      display: flex;\n      gap: 8px;\n      padding: 10px 12px;\n    }\n\n    .container-file-picker-header {\n      border-bottom: 1px solid var(--border);\n      justify-content: space-between;\n    }\n\n    .container-file-picker-header strong {\n      font-size: 13px;\n    }\n\n    .container-file-picker-toolbar {\n      border-bottom: 1px solid var(--border);\n    }\n\n    .container-file-picker-path {\n      background: var(--control);\n      border: 1px solid var(--border);\n      border-radius: 8px;\n      flex: 1 1 auto;\n      font: 600 11px/1.3 Menlo, Monaco, monospace;\n      min-width: 0;\n      overflow-x: auto;\n      padding: 7px 9px;\n      white-space: nowrap;\n    }\n\n    .container-file-picker-entries {\n      display: grid;\n      gap: 5px;\n      overflow-y: auto;\n      padding: 8px;\n    }\n\n    .container-file-entry {\n      align-items: center;\n      background: var(--control);\n      border: 1px solid var(--border);\n      border-radius: 8px;\n      color: var(--ink);\n      display: grid;\n      gap: 8px;\n      grid-template-columns: 22px minmax(0, 1fr) auto;\n      min-height: 42px;\n      padding: 6px 8px;\n      text-align: left;\n      width: 100%;\n    }\n\n    button.container-file-entry {\n      cursor: pointer;\n    }\n\n    button.container-file-entry:hover {\n      background: var(--control-strong);\n    }\n\n    .container-file-entry-icon {\n      color: var(--muted);\n      font-size: 14px;\n      text-align: center;\n    }\n\n    .container-file-entry-info {\n      min-width: 0;\n    }\n\n    .container-file-entry-name {\n      display: block;\n      font-size: 12px;\n      font-weight: 700;\n      overflow: hidden;\n      text-overflow: ellipsis;\n      white-space: nowrap;\n    }\n\n    .container-file-entry-meta {\n      color: var(--muted);\n      display: block;\n      font-size: 10px;\n      margin-top: 2px;\n    }\n\n    .container-file-entry .button {\n      min-height: 30px;\n      padding: 6px 8px;\n      width: auto;\n    }\n\n    .container-file-picker-footer {\n      border-top: 1px solid var(--border);\n      justify-content: space-between;\n    }\n\n    .container-file-picker-footer .settings-action-status {\n      margin: 0;\n      min-width: 0;\n    }\n\n'''
index = replace_once(index, css_anchor, css_anchor + css_block, "container picker CSS")

ui_anchor = '''              <div class="settings-group settings-action">\n                <span class="settings-label">Chromium</span>\n'''
ui_block = '''              <div class="settings-group settings-action">\n                <span class="settings-label">Файлы контейнера</span>\n                <button type="button" id="containerFileBrowseBtn" title="Открыть файловую систему Chromium-контейнера и скачать выбранный файл на локальный компьютер">\n                  Выбрать файл и скачать\n                </button>\n                <div class="settings-action-status" id="containerFileStatus">Выберите файл вручную из файловой системы контейнера</div>\n              </div>\n'''
index = replace_once(index, ui_anchor, ui_block + ui_anchor, "container picker Tools block")

dialog_anchor = '''  \n  <script>\n'''
dialog_block = '''\n  <dialog class="container-file-dialog" id="containerFileDialog">\n    <div class="container-file-picker">\n      <div class="container-file-picker-header">\n        <strong>Файлы Chromium-контейнера</strong>\n        <button type="button" id="containerFileCloseBtn" title="Закрыть">✕</button>\n      </div>\n      <div class="container-file-picker-toolbar">\n        <button type="button" id="containerFileUpBtn" title="На уровень выше">↑</button>\n        <div class="container-file-picker-path" id="containerFilePath" title="Текущий путь">/</div>\n      </div>\n      <div class="container-file-picker-entries" id="containerFileEntries" aria-live="polite"></div>\n      <div class="container-file-picker-footer">\n        <div class="settings-action-status" id="containerFilePickerStatus">Выберите файл для скачивания</div>\n        <button type="button" id="containerFileCancelBtn">Закрыть</button>\n      </div>\n    </div>\n  </dialog>\n  \n  <script>\n'''
index = replace_once(index, dialog_anchor, dialog_block, "container picker dialog")

vars_anchor = '''    const documentsFileList = document.getElementById("documentsFileList");\n    let documentsMaxUploadBytes = null;\n'''
vars_block = '''    const documentsFileList = document.getElementById("documentsFileList");\n    let documentsMaxUploadBytes = null;\n    const containerFileBrowseBtn = document.getElementById("containerFileBrowseBtn");\n    const containerFileStatus = document.getElementById("containerFileStatus");\n    const containerFileDialog = document.getElementById("containerFileDialog");\n    const containerFileCloseBtn = document.getElementById("containerFileCloseBtn");\n    const containerFileCancelBtn = document.getElementById("containerFileCancelBtn");\n    const containerFileUpBtn = document.getElementById("containerFileUpBtn");\n    const containerFilePath = document.getElementById("containerFilePath");\n    const containerFileEntries = document.getElementById("containerFileEntries");\n    const containerFilePickerStatus = document.getElementById("containerFilePickerStatus");\n    let containerFileCurrentPath = "/";\n    let containerFileParentPath = null;\n'''
index = replace_once(index, vars_anchor, vars_block, "container picker variables")

js_anchor = '''    function setRecoveryStatus(tone, message) {\n'''
js_block = '''    function setContainerFileStatus(tone, message) {\n      if (!containerFileStatus) return;\n      containerFileStatus.className = `settings-action-status ${tone || ""}`.trim();\n      containerFileStatus.textContent = message;\n    }\n\n    function setContainerFilePickerStatus(tone, message) {\n      if (!containerFilePickerStatus) return;\n      containerFilePickerStatus.className = `settings-action-status ${tone || ""}`.trim();\n      containerFilePickerStatus.textContent = message;\n    }\n\n    function containerFileDownloadUrl(path) {\n      const url = new URL("/api/container/files/download", window.location.href);\n      url.username = "";\n      url.password = "";\n      url.searchParams.set("path", path);\n      return url.toString();\n    }\n\n    function renderContainerDirectory(payload) {\n      if (!containerFileEntries || !containerFilePath) return;\n      containerFileCurrentPath = payload.path || "/";\n      containerFileParentPath = payload.parent || null;\n      containerFilePath.textContent = containerFileCurrentPath;\n      containerFilePath.title = containerFileCurrentPath;\n      if (containerFileUpBtn) containerFileUpBtn.disabled = !containerFileParentPath;\n      containerFileEntries.replaceChildren();\n\n      const entries = Array.isArray(payload.entries) ? payload.entries : [];\n      if (!entries.length) {\n        const empty = document.createElement("div");\n        empty.className = "document-file-empty";\n        empty.textContent = "В этом каталоге нет доступных файлов или папок";\n        containerFileEntries.appendChild(empty);\n      }\n\n      entries.forEach((entry) => {\n        const row = document.createElement(entry.kind === "directory" ? "button" : "div");\n        row.className = "container-file-entry";\n        if (entry.kind === "directory") row.type = "button";\n\n        const icon = document.createElement("span");\n        icon.className = "container-file-entry-icon";\n        icon.textContent = entry.kind === "directory" ? "▸" : "•";\n\n        const info = document.createElement("div");\n        info.className = "container-file-entry-info";\n        const name = document.createElement("span");\n        name.className = "container-file-entry-name";\n        name.textContent = entry.name;\n        name.title = entry.name;\n        const meta = document.createElement("span");\n        meta.className = "container-file-entry-meta";\n        meta.textContent = entry.kind === "directory"\n          ? "Папка"\n          : [formatFileBytes(entry.size), formatFileModified(entry.modifiedAt)].filter(Boolean).join(" · ");\n        info.append(name, meta);\n        row.append(icon, info);\n\n        if (entry.kind === "directory") {\n          row.onclick = () => loadContainerDirectory(entry.path);\n        } else {\n          const download = document.createElement("a");\n          download.className = "button";\n          download.textContent = "Скачать";\n          download.href = containerFileDownloadUrl(entry.path);\n          download.download = entry.name;\n          download.title = `Скачать ${entry.name} на локальный компьютер`;\n          download.onclick = () => {\n            setContainerFileStatus("ok", `Скачивание из контейнера: ${entry.name}`);\n            setContainerFilePickerStatus("ok", `Скачивание: ${entry.name}`);\n          };\n          row.appendChild(download);\n        }\n        containerFileEntries.appendChild(row);\n      });\n\n      const suffix = payload.truncated ? " · список ограничен" : "";\n      setContainerFilePickerStatus("ok", `${entries.length} элементов${suffix}`);\n    }\n\n    async function loadContainerDirectory(path = "/") {\n      if (!containerFileEntries) return;\n      setContainerFilePickerStatus("warn", "Загружаю каталог...");\n      if (containerFileUpBtn) containerFileUpBtn.disabled = true;\n      try {\n        const url = new URL("/api/container/files/list", window.location.href);\n        url.searchParams.set("path", path || "/");\n        const response = await localApiFetch(`${url.pathname}${url.search}`);\n        const payload = await response.json().catch(() => ({}));\n        if (!response.ok || !payload.ok) {\n          throw new Error(payload.message || payload.details || payload.summary || "Не удалось открыть каталог контейнера");\n        }\n        renderContainerDirectory(payload);\n      } catch (error) {\n        containerFileEntries.replaceChildren();\n        const empty = document.createElement("div");\n        empty.className = "document-file-empty";\n        empty.textContent = error.message || "Не удалось открыть каталог контейнера";\n        containerFileEntries.appendChild(empty);\n        setContainerFilePickerStatus("danger", error.message || "Не удалось открыть каталог контейнера");\n      }\n    }\n\n    async function openContainerFileBrowser() {\n      if (!containerFileDialog) return;\n      if (!containerFileDialog.open) containerFileDialog.showModal();\n      setContainerFileStatus("warn", "Открыт файловый браузер контейнера");\n      await loadContainerDirectory(containerFileCurrentPath || "/");\n    }\n\n    function closeContainerFileBrowser() {\n      if (containerFileDialog?.open) containerFileDialog.close();\n    }\n\n'''
index = replace_once(index, js_anchor, js_block + js_anchor, "container picker JS")

listeners_anchor = '''    if (documentsFileList) loadDocumentFiles();\n    if (recoverStackBtn) {\n'''
listeners_block = '''    if (documentsFileList) loadDocumentFiles();\n    if (containerFileBrowseBtn) containerFileBrowseBtn.onclick = openContainerFileBrowser;\n    if (containerFileCloseBtn) containerFileCloseBtn.onclick = closeContainerFileBrowser;\n    if (containerFileCancelBtn) containerFileCancelBtn.onclick = closeContainerFileBrowser;\n    if (containerFileUpBtn) containerFileUpBtn.onclick = () => {\n      if (containerFileParentPath) loadContainerDirectory(containerFileParentPath);\n    };\n    if (containerFileDialog) {\n      containerFileDialog.addEventListener("click", (event) => {\n        if (event.target === containerFileDialog) closeContainerFileBrowser();\n      });\n    }\n    if (recoverStackBtn) {\n'''
index = replace_once(index, listeners_anchor, listeners_block, "container picker listeners")
index_path.write_text(index, encoding="utf-8")


docs_path = Path("TOOLS.md")
docs = docs_path.read_text(encoding="utf-8")
docs = replace_once(
    docs,
    '- **Файлы Documents** — загрузка произвольных файлов в `~/Documents` виртуальной машины, просмотр списка и скачивание файлов через браузер.\n',
    '- **Файлы Documents** — загрузка произвольных файлов в `~/Documents` виртуальной машины, просмотр списка и скачивание файлов через браузер.\n- **Файлы контейнера** — ручной просмотр файловой системы Chromium-контейнера и скачивание выбранного файла напрямую на локальный компьютер.\n',
    "TOOLS current tools",
)
docs += r'''

## Скачивание файлов из Chromium-контейнера

В **Tools → Файлы контейнера** кнопка **«Выбрать файл и скачать»** открывает серверный файловый браузер Chromium-контейнера (`FLY_BROWSER_CONTAINER_NAME`, по умолчанию `fly-terminal-browser`). Навигация начинается с `/`: пользователь вручную переходит по каталогам и нажимает **«Скачать»** у нужного обычного файла. Ответ `Content-Disposition: attachment` формируется внешним Fly Terminal, поэтому файл скачивается браузером на локальный компьютер пользователя; промежуточное копирование в `~/Documents` не требуется.

### API файлового браузера контейнера

- `GET /api/container/files/list?path=/...` — перечисляет обычные каталоги и файлы выбранного каталога. Каталоги идут первыми; для файлов возвращаются размер и время изменения. Максимальное число элементов задаётся `FLY_TERMINAL_CONTAINER_FILE_MAX_ENTRIES` (по умолчанию 2000).
- `GET /api/container/files/download?path=/...` — потоково передаёт один выбранный файл из Chromium-контейнера в локальный браузер. Backend запускает внутри контейнера Python-процесс, открывает файл с `O_NOFOLLOW`, проверяет через `fstat()`, что это обычный файл, сначала передаёт его метаданные, а затем тот же открытый файловый дескриптор стримится в HTTP-ответ. Это исключает TOCTOU-подмену финального файла между проверкой и чтением.

### Ограничения и безопасность

Пути принимаются только абсолютные и нормализуются как POSIX-пути. Файловый браузер не показывает символические ссылки и не разрешает переход через symlink-компоненты. Виртуальные системные деревья `/proc`, `/sys`, `/dev` и `/run` исключены: они содержат устройства и псевдофайлы, чтение которых может зависать или иметь побочные эффекты. Остальная обычная файловая система контейнера доступна для ручной навигации в пределах прав контейнера. Ошибки Docker, доступа и чтения преобразуются в человекочитаемые сообщения через общий `TOOL_ERROR_MESSAGES`.
'''
docs_path.write_text(docs, encoding="utf-8")
