#!/usr/bin/env python3
from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


# Backend
path = Path("session-control.py")
text = path.read_text(encoding="utf-8")
if 'DOCUMENTS_DIR = Path.home() / "Documents"' not in text:
    text = replace_once(
        text,
        'from pathlib import Path\n',
        'from pathlib import Path\nfrom urllib.parse import parse_qs, quote, urlsplit\n',
        "backend import",
    )
    text = replace_once(
        text,
        'UPLOAD_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")\n',
        'UPLOAD_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")\nDOCUMENTS_DIR = Path.home() / "Documents"\n',
        "documents constant",
    )
    text = replace_once(
        text,
        '    "happ_location_switch_failed": "Не удалось переключить локацию Happ.",\n}',
        '''    "happ_location_switch_failed": "Не удалось переключить локацию Happ.",
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
}''',
        "error messages",
    )

    helper_anchor = '\ndef operation_failure_message(operation, step):\n'
    helpers = r'''

def documents_root():
    """Return the resolved VM Documents directory, creating it when needed."""
    try:
        DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
        return DOCUMENTS_DIR.resolve(strict=True), ""
    except OSError as exc:
        return None, str(exc)


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


def resolve_document_download(file_name):
    name = normalize_document_file_name(file_name)
    if not name:
        return None, "file_name_invalid", ""

    root, root_error = documents_root()
    if root_error:
        return None, "documents_unavailable", root_error

    candidate = root / name
    try:
        if candidate.is_symlink():
            return None, "file_access_denied", "symlink"
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        return None, "file_not_found", ""
    except (OSError, RuntimeError) as exc:
        return None, "file_access_denied", str(exc)

    if resolved.parent != root or not resolved.is_file():
        return None, "file_access_denied", "outside_documents_or_not_regular_file"
    return resolved, "", ""
'''
    text = replace_once(text, helper_anchor, helpers + helper_anchor, "backend helpers")

    get_anchor = '        if self.path == "/api/browser/config":\n'
    get_routes = '''        if self.path == "/api/files/list":
            self._handle_documents_list()
            return

        if urlsplit(self.path).path == "/api/files/download":
            self._handle_document_download()
            return

'''
    text = replace_once(text, get_anchor, get_routes + get_anchor, "GET routes")

    post_anchor = '        elif self.path == "/api/session/upload-image":\n'
    post_routes = '''        elif self.path == "/api/files/upload":
            self._handle_document_upload()
'''
    text = replace_once(text, post_anchor, post_routes + post_anchor, "POST route")

    method_anchor = '    def _handle_upload_image(self):\n'
    methods = r'''    def _handle_documents_list(self):
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
            },
        )

    def _handle_document_download(self):
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        file_name = (query.get("name") or [""])[0]
        target_path, error_code, technical_details = resolve_document_download(file_name)
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

        try:
            source = target_path.open("rb")
        except OSError as exc:
            send_json(self, 500, {"ok": False, "error": "file_read_failed", "details": str(exc)})
            return

        with source:
            try:
                stat = os.fstat(source.fileno())
            except OSError as exc:
                send_json(self, 500, {"ok": False, "error": "file_read_failed", "details": str(exc)})
                return

            mime_type = mimetypes.guess_type(target_path.name)[0] or "application/octet-stream"
            suffix = target_path.suffix
            safe_suffix = suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,12}", suffix or "") else ""
            fallback_name = f"download{safe_suffix}"
            encoded_name = quote(target_path.name, safe="")
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Disposition", f"attachment; filename=\"{fallback_name}\"; filename*=UTF-8''{encoded_name}")
            self.send_header("Content-Length", str(stat.st_size))
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

'''
    text = replace_once(text, method_anchor, methods + method_anchor, "backend methods")
    text = text.replace(
        'handler.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")',
        'handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")',
        1,
    )
    path.write_text(text, encoding="utf-8")


# Frontend
path = Path("index.html")
text = path.read_text(encoding="utf-8")
if 'id="documentsUploadInput"' not in text:
    css_anchor = '''    .tools-menu select {
      min-width: 0;
    }
'''
    css_insert = '''    .tools-menu select {
      min-width: 0;
    }

    .file-upload-input {
      background: var(--select-bg);
      border: 1px solid var(--border);
      border-radius: var(--control-radius);
      color: var(--ink);
      font: 600 12px/1.2 "Avenir Next", "Segoe UI", sans-serif;
      min-width: 0;
      padding: 8px;
      width: 100%;
    }

    .file-upload-input::file-selector-button {
      background: var(--button-bg);
      border: 1px solid var(--border);
      border-radius: 7px;
      color: var(--button-ink);
      cursor: pointer;
      font: inherit;
      margin-right: 8px;
      padding: 6px 8px;
    }

    .file-tools-actions {
      display: grid;
      gap: 6px;
      grid-template-columns: minmax(0, 1fr) auto;
    }

    .settings-action .file-tools-actions button {
      min-height: 34px;
      width: auto;
    }

    .document-file-list {
      display: grid;
      gap: 5px;
      max-height: 190px;
      overflow-y: auto;
    }

    .document-file-empty {
      color: var(--muted);
      font-size: 11px;
      padding: 6px 2px;
    }

    .document-file-row {
      align-items: center;
      background: var(--control);
      border: 1px solid var(--border);
      border-radius: 8px;
      display: grid;
      gap: 7px;
      grid-template-columns: minmax(0, 1fr) auto;
      padding: 6px 7px;
    }

    .document-file-info {
      min-width: 0;
    }

    .document-file-name {
      display: block;
      font-size: 12px;
      font-weight: 700;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .document-file-meta {
      color: var(--muted);
      display: block;
      font-size: 10px;
      margin-top: 3px;
    }

    .settings-action .document-file-download {
      min-height: 30px;
      padding: 6px 8px;
      width: auto;
    }
'''
    text = replace_once(text, css_anchor, css_insert, "file tools CSS")

    html_anchor = '''              <div class="settings-group settings-action">
                <span class="settings-label">Chromium</span>
'''
    html_insert = '''              <div class="settings-group settings-action">
                <span class="settings-label">Файлы Documents</span>
                <input class="file-upload-input" type="file" id="documentsUploadInput" multiple aria-label="Файлы для загрузки в Documents" />
                <div class="file-tools-actions">
                  <button type="button" id="documentsUploadBtn" title="Загрузить выбранные файлы в Documents виртуальной машины">Загрузить</button>
                  <button type="button" id="documentsRefreshBtn" title="Обновить список файлов">Обновить</button>
                </div>
                <div class="settings-action-status" id="documentsStatus">Загрузка списка...</div>
                <div class="document-file-list" id="documentsFileList" aria-live="polite"></div>
              </div>
              <div class="settings-group settings-action">
                <span class="settings-label">Chromium</span>
'''
    text = replace_once(text, html_anchor, html_insert, "file tools HTML")

    decl_anchor = '    const recoverStackBtn = document.getElementById("recoverStack");\n'
    decl_insert = '''    const documentsUploadInput = document.getElementById("documentsUploadInput");
    const documentsUploadBtn = document.getElementById("documentsUploadBtn");
    const documentsRefreshBtn = document.getElementById("documentsRefreshBtn");
    const documentsStatus = document.getElementById("documentsStatus");
    const documentsFileList = document.getElementById("documentsFileList");
    let documentsMaxUploadBytes = null;
    const recoverStackBtn = document.getElementById("recoverStack");
'''
    text = replace_once(text, decl_anchor, decl_insert, "file tools declarations")

    fn_anchor = '    function setRecoveryStatus(tone, message) {\n'
    functions = r'''    function setDocumentsStatus(tone, message) {
      if (!documentsStatus) return;
      documentsStatus.className = `settings-action-status ${tone || ""}`.trim();
      documentsStatus.textContent = message;
    }

    function formatFileBytes(bytes) {
      const value = Number(bytes) || 0;
      if (value < 1024) return `${value} Б`;
      if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} КБ`;
      return `${(value / (1024 * 1024)).toFixed(value < 10 * 1024 * 1024 ? 1 : 0)} МБ`;
    }

    function formatFileModified(value) {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return "";
      return date.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
    }

    function documentDownloadUrl(fileName) {
      const url = new URL("/api/files/download", window.location.href);
      url.username = "";
      url.password = "";
      url.searchParams.set("name", fileName);
      return url.toString();
    }

    function renderDocumentFiles(files) {
      if (!documentsFileList) return;
      documentsFileList.replaceChildren();
      if (!Array.isArray(files) || files.length === 0) {
        const empty = document.createElement("div");
        empty.className = "document-file-empty";
        empty.textContent = "Папка Documents пуста";
        documentsFileList.appendChild(empty);
        return;
      }

      files.forEach((file) => {
        const row = document.createElement("div");
        row.className = "document-file-row";

        const info = document.createElement("div");
        info.className = "document-file-info";
        const name = document.createElement("span");
        name.className = "document-file-name";
        name.textContent = file.name;
        name.title = file.name;
        const meta = document.createElement("span");
        meta.className = "document-file-meta";
        meta.textContent = [formatFileBytes(file.size), formatFileModified(file.modifiedAt)].filter(Boolean).join(" · ");
        info.append(name, meta);

        const download = document.createElement("a");
        download.className = "button document-file-download";
        download.textContent = "Скачать";
        download.title = `Скачать ${file.name}`;
        download.href = documentDownloadUrl(file.name);
        download.download = file.name;
        download.onclick = () => setDocumentsStatus("ok", `Скачивание: ${file.name}`);

        row.append(info, download);
        documentsFileList.appendChild(row);
      });
    }

    async function loadDocumentFiles({ announce = true } = {}) {
      if (!documentsFileList) return;
      if (announce) setDocumentsStatus("warn", "Обновляю список файлов...");
      try {
        const response = await localApiFetch("/api/files/list");
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.ok) {
          throw new Error(payload.message || payload.details || payload.summary || "Не удалось получить список файлов");
        }
        documentsMaxUploadBytes = Number(payload.maxUploadBytes) || null;
        renderDocumentFiles(payload.files);
        if (announce) {
          const count = Array.isArray(payload.files) ? payload.files.length : 0;
          const limit = documentsMaxUploadBytes ? ` · лимит ${formatFileBytes(documentsMaxUploadBytes)}` : "";
          setDocumentsStatus("ok", `Documents: ${count} файл${count === 1 ? "" : "ов"}${limit}`);
        }
      } catch (error) {
        renderDocumentFiles([]);
        if (announce) setDocumentsStatus("danger", error.message || "Не удалось получить список файлов");
      }
    }

    function fileToBase64(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error(`Не удалось прочитать ${file.name}`));
        reader.onload = () => {
          const result = String(reader.result || "");
          const comma = result.indexOf(",");
          resolve(comma >= 0 ? result.slice(comma + 1) : "");
        };
        reader.readAsDataURL(file);
      });
    }

    async function uploadDocumentFiles() {
      if (!documentsUploadInput || !documentsUploadBtn) return;
      const files = Array.from(documentsUploadInput.files || []);
      if (!files.length) {
        setDocumentsStatus("warn", "Выберите один или несколько файлов");
        return;
      }

      documentsUploadBtn.disabled = true;
      if (documentsRefreshBtn) documentsRefreshBtn.disabled = true;
      const saved = [];
      try {
        for (let index = 0; index < files.length; index += 1) {
          const file = files[index];
          if (documentsMaxUploadBytes && file.size > documentsMaxUploadBytes) {
            throw new Error(`${file.name}: размер превышает ${formatFileBytes(documentsMaxUploadBytes)}`);
          }
          setDocumentsStatus("warn", `Загружаю ${index + 1}/${files.length}: ${file.name}`);
          const data = await fileToBase64(file);
          const response = await localApiFetch("/api/files/upload", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              fileName: file.name,
              mimeType: file.type || "application/octet-stream",
              data
            })
          });
          const payload = await response.json().catch(() => ({}));
          if (!response.ok || !payload.ok) {
            throw new Error(payload.message || payload.details || payload.summary || `Не удалось загрузить ${file.name}`);
          }
          saved.push(payload);
        }
        documentsUploadInput.value = "";
        await loadDocumentFiles({ announce: false });
        const renamed = saved.filter(item => item.renamed).length;
        setDocumentsStatus(
          "ok",
          `Загружено: ${saved.length}${renamed ? ` · ${renamed} переименовано из-за совпадения имён` : ""}`
        );
      } catch (error) {
        await loadDocumentFiles({ announce: false });
        setDocumentsStatus("danger", error.message || "Не удалось загрузить файл");
      } finally {
        documentsUploadBtn.disabled = false;
        if (documentsRefreshBtn) documentsRefreshBtn.disabled = false;
      }
    }

'''
    text = replace_once(text, fn_anchor, functions + fn_anchor, "file tools functions")

    listener_anchor = '''    bindFloatingMenus();
    bindResponsiveToolbar();
    if (recoverStackBtn) {
'''
    listener_insert = '''    bindFloatingMenus();
    bindResponsiveToolbar();
    if (documentsUploadBtn) documentsUploadBtn.onclick = uploadDocumentFiles;
    if (documentsRefreshBtn) documentsRefreshBtn.onclick = () => loadDocumentFiles();
    if (documentsFileList) loadDocumentFiles();
    if (recoverStackBtn) {
'''
    text = replace_once(text, listener_anchor, listener_insert, "file tools listeners")
    path.write_text(text, encoding="utf-8")


# Documentation
path = Path("TOOLS.md")
text = path.read_text(encoding="utf-8")
if "## Файлы Documents" not in text:
    text = replace_once(
        text,
        '- **Обновить Fly Terminal** — `git fetch` + `git pull --ff-only`, перезапуск системных служб и ожидание готовности портов.\n',
        '- **Обновить Fly Terminal** — `git fetch` + `git pull --ff-only`, перезапуск системных служб и ожидание готовности портов.\n- **Файлы Documents** — загрузка произвольных файлов в `~/Documents` виртуальной машины, просмотр списка и скачивание файлов через браузер.\n',
        "tools list docs",
    )
    text += r'''

## Файлы Documents

Файловый обмен реализован как штатный инструмент раздела **Tools** и обслуживается `session-control.py`. Рабочая область инструмента — только `Path.home() / "Documents"` виртуальной машины; текущий каталог tmux-сессии для этой функции не используется.

### API

- `GET /api/files/list` — список обычных файлов верхнего уровня `Documents` с именем, размером и временем изменения, а также текущим лимитом загрузки `maxUploadBytes`.
- `POST /api/files/upload` — загрузка произвольного файла. Тело JSON содержит `fileName`, `mimeType` и base64-поле `data`. Максимальный размер самого файла задаётся существующей переменной `FLY_TERMINAL_MAX_UPLOAD_BYTES` (по умолчанию 25 МБ).
- `GET /api/files/download?name=...` — потоковое скачивание файла. Ответ содержит определённый по расширению `Content-Type`, `Content-Length` и `Content-Disposition` с `filename*` в UTF-8.

### Безопасность путей и совпадения имён

API принимает только одно имя файла без компонентов пути. `/`, `\\`, управляющие символы, `.`/`..` и чрезмерно длинные имена отклоняются. Список не показывает символические ссылки. При скачивании символические ссылки запрещены, а разрешённый путь после `resolve()` обязан оставаться непосредственно внутри разрешённого каталога `Documents`.

Загрузка резервирует файл атомарно через создание с `O_EXCL`, поэтому существующий файл никогда не перезаписывается молча. При совпадении имени создаётся вариант `имя (2).ext`, затем `имя (3).ext` и т. д.; API сообщает UI поле `renamed`.

Пользовательские ошибки файлового инструмента проходят через общий `TOOL_ERROR_MESSAGES`; низкоуровневая диагностика сохраняется в `technicalDetails` и не выводится в интерфейсе.
'''
    path.write_text(text, encoding="utf-8")
