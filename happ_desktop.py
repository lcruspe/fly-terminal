"""Read Happ Desktop's local catalogue without modifying its database or VPN.

The private format below was verified against macOS Desktop 4.5.4. Authentication
must succeed before parsing any plaintext; future formats fail explicitly.
Only names and opaque IDs leave this module. Subscription credentials and server
configs are never written to disk or returned to the public API.
"""
import base64
import functools
import hashlib
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import struct
import subprocess
import tempfile
import threading
from urllib.parse import quote
from xml.parsers.expat import ExpatError


DATABASE = Path.home() / "Library/Preferences/Happ/subs.db"
PREFERENCES = Path.home() / "Library/Preferences/com.happ.plist"
APPLICATION = Path("/Applications/Happ.app")
SOURCE = Path(__file__).parent / "macos/happ-desktop-decrypt.swift"
HELPER = Path.home() / "Library/Caches/FlyTerminal/happ-desktop-decrypt"
BUILD_LOCK = threading.Lock()
MAX_BYTES = 64 * 1024 * 1024


class HappDesktopError(Exception):
    """Stable public error codes; never include private database contents."""


def available():
    return DATABASE.is_file()


def _arm64_image(binary):
    if binary[:4] == b"\xca\xfe\xba\xbe":
        count = struct.unpack_from(">I", binary, 4)[0]
        if count > 32:
            raise ValueError("Invalid architecture count")
        for index in range(count):
            cpu, _, offset, size, _ = struct.unpack_from(">5I", binary, 8 + index * 20)
            if cpu == 0x100000C and offset + size <= len(binary):
                return binary[offset:offset + size]
        raise ValueError("No arm64 image")
    if binary[:4] == b"\xcf\xfa\xed\xfe" and struct.unpack_from("<I", binary, 4)[0] == 0x100000C:
        return binary
    raise ValueError("Unsupported Mach-O")


def _symbol_bytes(binary, requested):
    """Resolve data symbols, independent of file offsets and load addresses."""
    image = _arm64_image(binary)
    count, command_size = struct.unpack_from("<II", image, 16)
    if count > 1024 or 32 + command_size > len(image):
        raise ValueError("Invalid load commands")
    segments, symtab = [], None
    position = 32
    for _ in range(count):
        command, size = struct.unpack_from("<II", image, position)
        if size < 8 or position + size > 32 + command_size:
            raise ValueError("Invalid command size")
        if command == 0x19:
            segments.append(struct.unpack_from("<QQQQ", image, position + 24))
        elif command == 2:
            symtab = struct.unpack_from("<4I", image, position + 8)
        position += size
    if symtab is None:
        raise ValueError("No symbol table")
    offset, count, strings_offset, strings_size = symtab
    if offset + count * 16 > len(image) or strings_offset + strings_size > len(image):
        raise ValueError("Invalid symbol table")
    strings = image[strings_offset:strings_offset + strings_size]
    result = {}
    for index in range(count):
        string_index, _, _, _, address = struct.unpack_from("<IBBHQ", image, offset + index * 16)
        name = strings[string_index:strings.find(b"\0", string_index)]
        if name not in requested:
            continue
        length = requested[name]
        for vm_address, _, file_offset, file_size in segments:
            if vm_address <= address and address + length <= vm_address + file_size:
                start = file_offset + address - vm_address
                if start + length <= len(image):
                    result[name] = image[start:start + length]
                    break
    if set(result) != set(requested):
        raise ValueError("Missing crypto symbols")
    return result


@functools.lru_cache(maxsize=2)
def _crypto_parameters(app_path, binary_mtime, binary_size, info_mtime):
    # Metadata participates in the cache key so replacing Happ invalidates it.
    app = Path(app_path)
    metadata = subprocess.run(["/usr/bin/plutil", "-convert", "xml1", "-o", "-", str(app / "Contents/Info.plist")],
                              capture_output=True, timeout=5, check=False)
    if metadata.returncode:
        raise HappDesktopError("happ_desktop_unsupported_version")
    info = plistlib.loads(metadata.stdout)
    if not isinstance(info, dict):
        raise HappDesktopError("happ_desktop_unsupported_version")
    if info.get("CFBundleIdentifier") != "com.happ.www" or info.get("CFBundleShortVersionString") != "4.5.4":
        raise HappDesktopError("happ_desktop_unsupported_version")
    symbols = _symbol_bytes((app / "Contents/MacOS/Happ").read_bytes(), {
        b"__ZN9AES128GCM6kKey01E": 16,
        b"__ZN9AES128GCM3kIVE": 12,
    })
    # XOR masks used by Desktop 4.5.4's constant decoding functions. The actual
    # key/nonce are extracted from the installed app, never checked into git.
    key_mask = bytes.fromhex("5b7e1dc8cefef2a063062530f686faa8")
    nonce_mask = bytes.fromhex("80531dc8cefef2a0b82b2530")
    key = bytes(a ^ b for a, b in zip(symbols[b"__ZN9AES128GCM6kKey01E"], key_mask))
    nonce = bytes(a ^ b for a, b in zip(symbols[b"__ZN9AES128GCM3kIVE"], nonce_mask))
    return key, nonce


def _helper():
    with BUILD_LOCK:
        if not HELPER.is_file() or HELPER.stat().st_mtime_ns < SOURCE.stat().st_mtime_ns:
            HELPER.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix="happ-desktop-", dir=HELPER.parent)
            os.close(fd)
            temporary = Path(name)
            try:
                result = subprocess.run(["/usr/bin/swiftc", str(SOURCE), "-o", str(temporary)],
                                        capture_output=True, timeout=90, check=False)
                if result.returncode:
                    raise HappDesktopError("happ_desktop_reader_build_failed")
                os.replace(temporary, HELPER)
            finally:
                temporary.unlink(missing_ok=True)
    return HELPER


def _read_payload():
    try:
        binary = (APPLICATION / "Contents/MacOS/Happ").stat()
        info = (APPLICATION / "Contents/Info.plist").stat()
        key, nonce = _crypto_parameters(str(APPLICATION), binary.st_mtime_ns, binary.st_size, info.st_mtime_ns)
        uri = f"file:{quote(str(DATABASE), safe='/')}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            row = connection.execute("SELECT data, tag FROM subscriptions WHERE version = 1").fetchone()
        finally:
            connection.close()
        if row is None:
            raise HappDesktopError("happ_desktop_database_invalid")
        blob, tag = row
        if len(blob) > MAX_BYTES or len(tag) > 128:
            raise HappDesktopError("happ_desktop_database_invalid")
        request = {"key": base64.b64encode(key).decode(), "nonce": base64.b64encode(nonce).decode(),
                   "data": blob.decode("ascii") if isinstance(blob, bytes) else blob, "tag": tag}
        result = subprocess.run([str(_helper())], input=json.dumps(request).encode("ascii"),
                                capture_output=True, timeout=20, check=False)
        if result.returncode:
            raise HappDesktopError("happ_desktop_decryption_failed")
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict) or not isinstance(payload.get("map"), dict):
            raise HappDesktopError("happ_desktop_database_invalid")
        return payload
    except HappDesktopError:
        raise
    except (OSError, ValueError, TypeError, KeyError, ExpatError, struct.error, sqlite3.Error, subprocess.TimeoutExpired):
        raise HappDesktopError("happ_desktop_read_failed") from None


def _ordered_entries(mapping, order):
    # Preserve Happ's order, including entries absent from an older order list.
    if not isinstance(mapping, dict) or not isinstance(order, list):
        raise HappDesktopError("happ_desktop_database_invalid")
    seen = set()
    for key in [*(str(item) for item in order), *mapping]:
        if key not in seen and key in mapping:
            seen.add(key)
            yield key, mapping[key]


def _opaque_id(*parts):
    return "desktop-" + hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:24]


def catalog():
    payload = _read_payload()
    try:
        preferences = plistlib.loads(PREFERENCES.read_bytes())
    except (OSError, ValueError, ExpatError):
        preferences = {}
    if not isinstance(preferences, dict):
        preferences = {}
    selected_sub = str(preferences.get("Preferences.lastSubscription", ""))
    selected_server = str(preferences.get("Preferences.lastServer", ""))
    selected_guid = preferences.get("Preferences.lastServerGuid", "")
    result = {"subscriptions": [], "current": "", "currentSubscription": "",
              "currentSubscriptionId": "", "currentLocationId": "", "source": "happ-desktop",
              "canSwitch": False, "canReconnect": False, "selectionLabel": "Выбрано в Happ",
              "notice": "Для подключения выберите сервер в Happ Desktop."}
    for sub_key, subscription in _ordered_entries(payload["map"], payload.get("order", [])):
        if not isinstance(subscription, dict):
            raise HappDesktopError("happ_desktop_database_invalid")
        sub = {"id": _opaque_id(sub_key), "label": str(subscription.get("name") or "Подписка Happ"), "locations": []}
        for server_key, server in _ordered_entries(subscription.get("serverMap", {}), subscription.get("serverOrder", [])):
            if not isinstance(server, dict):
                raise HappDesktopError("happ_desktop_database_invalid")
            guid = server.get("guid") or server_key
            location = {"id": _opaque_id(sub_key, guid), "label": str(server.get("name") or "Локация Happ")}
            sub["locations"].append(location)
            if sub_key == selected_sub and (guid == selected_guid if selected_guid else server_key == selected_server):
                result.update(current=location["label"], currentSubscription=sub["label"],
                              currentSubscriptionId=sub["id"], currentLocationId=location["id"])
        result["subscriptions"].append(sub)
    return result
