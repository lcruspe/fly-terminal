#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import os
import tempfile


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


path = Path("session-control.py")
text = path.read_text(encoding="utf-8")
if "def open_document_download(file_name):" not in text:
    text = replace_once(text, "import shlex\n", "import shlex\nimport stat\n", "stat import")

    old_helper = r'''def resolve_document_download(file_name):
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
    new_helper = r'''def open_document_download(file_name):
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
'''
    text = replace_once(text, old_helper, new_helper, "download helper")

    old_method = r'''    def _handle_document_download(self):
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
    new_method = r'''    def _handle_document_download(self):
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
'''
    text = replace_once(text, old_method, new_method, "download method")
    text = text.replace("    return source, name, \"\", \"\"\n\ndef operation_failure_message", "    return source, name, \"\", \"\"\n\n\ndef operation_failure_message", 1)
    path.write_text(text, encoding="utf-8")

# Keep security guarantees documented next to the API contract.
docs = Path("TOOLS.md")
doc_text = docs.read_text(encoding="utf-8")
needle = "При скачивании символические ссылки запрещены, а разрешённый путь после `resolve()` обязан оставаться непосредственно внутри разрешённого каталога `Documents`."
replacement = "При скачивании файл открывается относительно дескриптора каталога `Documents` с запретом перехода по финальной символической ссылке (`O_NOFOLLOW`), после чего `fstat()` подтверждает, что открыт обычный файл. Это исключает подмену файла на symlink между проверкой и открытием."
if needle in doc_text:
    docs.write_text(doc_text.replace(needle, replacement, 1), encoding="utf-8")

# Focused smoke tests for the file sandbox; they run before the workflow commits.
spec = importlib.util.spec_from_file_location("fly_session_control", "session-control.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as temp_dir:
    temp_root = Path(temp_dir)
    module.DOCUMENTS_DIR = temp_root / "Documents"
    root, error = module.documents_root()
    assert not error and root == module.DOCUMENTS_DIR.resolve()

    for invalid in ("../escape", "sub/file", "sub\\file", ".", ".."):
        assert module.normalize_document_file_name(invalid) == "", invalid

    first, first_fd = module.reserve_document_file(root, "report.txt")
    os.write(first_fd, b"first")
    os.close(first_fd)
    second, second_fd = module.reserve_document_file(root, "report.txt")
    os.close(second_fd)
    assert first.name == "report.txt"
    assert second.name == "report (2).txt"

    outside = temp_root / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    symlink = root / "link.txt"
    symlink.symlink_to(outside)
    files, error_code, _ = module.list_document_files()
    assert not error_code
    assert "link.txt" not in {item["name"] for item in files}
    source, _, error_code, _ = module.open_document_download("link.txt")
    assert source is None and error_code == "file_access_denied"

    source, safe_name, error_code, _ = module.open_document_download("report.txt")
    assert not error_code and safe_name == "report.txt"
    with source:
        assert source.read() == b"first"
