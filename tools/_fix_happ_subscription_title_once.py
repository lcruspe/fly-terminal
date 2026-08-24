#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import subprocess


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


path = Path("session-control.py")
text = path.read_text(encoding="utf-8")
old = '''def _normalize_happ_subscription_title(value):
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
'''
new = '''def _normalize_happ_subscription_title(value):
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return ""
    title = str(value or "").strip()
    if not title:
        return ""

    encoded_title = title
    explicit_base64 = False
    if title.casefold().startswith("base64:"):
        encoded_title = title.split(":", 1)[1].strip()
        explicit_base64 = True

    if encoded_title and " " not in encoded_title and len(encoded_title) >= 4 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", encoded_title):
        padded = encoded_title + "=" * (-len(encoded_title) % 4)
        try:
            decoded_bytes = base64.b64decode(padded, altchars=b"-_", validate=True)
            decoded = decoded_bytes.decode("utf-8").strip()
            standard = base64.b64encode(decoded_bytes).decode("ascii").rstrip("=")
            urlsafe = base64.urlsafe_b64encode(decoded_bytes).decode("ascii").rstrip("=")
            canonical_match = encoded_title.rstrip("=") in {standard, urlsafe}
            if decoded and canonical_match and all(char.isprintable() for char in decoded):
                title = decoded
            elif explicit_base64:
                return ""
        except (ValueError, UnicodeDecodeError):
            if explicit_base64:
                return ""
    elif explicit_base64:
        return ""
    return title[:80]
'''
text = replace_once(text, old, new, "Happ title normalizer")
path.write_text(text, encoding="utf-8")

docs = Path("TOOLS.md")
text = docs.read_text(encoding="utf-8")
old_docs = "Название подписки извлекается из HTTP-метаданных `profile-title` в `response_object` (включая base64-вариант, поддерживаемый Happ)."
new_docs = "Название подписки извлекается из HTTP-метаданных `profile-title` в `response_object`. Поддерживаются как чистые Base64-значения, так и фактический формат Happ `base64:<payload>`; в UI всегда передаётся декодированное человекочитаемое название."
text = replace_once(text, old_docs, new_docs, "TOOLS.md Happ title docs")
docs.write_text(text, encoding="utf-8")

subprocess.run(["python", "-m", "py_compile", "session-control.py"], check=True)
spec = importlib.util.spec_from_file_location("session_control", "session-control.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module._normalize_happ_subscription_title("base64:RWRnZSBWUE4=") == "Edge VPN"
assert module._normalize_happ_subscription_title("BASE64:RWRnZSBWUE4=") == "Edge VPN"
assert module._normalize_happ_subscription_title("RWRnZSBWUE4=") == "Edge VPN"
assert module._normalize_happ_subscription_title("My VPN") == "My VPN"
assert module._normalize_happ_subscription_title("base64:not-valid-%%%") == ""
subprocess.run(["git", "diff", "--check"], check=True)
