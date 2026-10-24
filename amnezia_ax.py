"""Native AmneziaVPN Accessibility bridge. No VPN secrets or config are read."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

SOURCE = Path(__file__).resolve().parent / "macos/amnezia-ax.swift"
BINARY = Path.home() / "Library/Caches/FlyTerminal/amnezia-ax"
BUILD_LOCK = threading.Lock()
ERROR_CODES = frozenset({
    "amnezia_screen_locked", "amnezia_accessibility_denied", "amnezia_not_running",
    "amnezia_window_unavailable", "amnezia_profiles_unavailable",
    "amnezia_profile_not_found", "amnezia_select_failed", "amnezia_disconnect_failed",
    "amnezia_disconnect_timeout", "amnezia_connect_failed", "amnezia_connect_timeout",
    "amnezia_state_unavailable", "amnezia_selection_unconfirmed",
    "amnezia_invalid_action", "amnezia_ax_unavailable",
})


class AmneziaAXError(Exception):
    """Public error code, without raw native stderr or VPN configuration."""


def executable():
    if sys.platform != "darwin" or not SOURCE.is_file():
        raise AmneziaAXError("amnezia_ax_unavailable")
    with BUILD_LOCK:
        if not BINARY.is_file() or BINARY.stat().st_mtime < SOURCE.stat().st_mtime:
            BINARY.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd, path = tempfile.mkstemp(prefix="amnezia-ax-", dir=BINARY.parent)
            os.close(fd)
            temp = Path(path)
            try:
                proc = subprocess.run(
                    ["/usr/bin/swiftc", str(SOURCE), "-o", str(temp)],
                    capture_output=True, text=True, timeout=90, check=False,
                )
                if proc.returncode:
                    raise AmneziaAXError("amnezia_ax_build_failed")
                os.chmod(temp, 0o700)
                os.replace(temp, BINARY)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise AmneziaAXError("amnezia_ax_build_failed") from exc
            finally:
                temp.unlink(missing_ok=True)
    return str(BINARY)


def command(action, *arguments):
    if action not in {"list", "select", "status"}:
        raise AmneziaAXError("amnezia_invalid_action")
    try:
        proc = subprocess.run(
            [executable(), action, *arguments], capture_output=True, text=True,
            timeout=70 if action == "select" else 15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AmneziaAXError("amnezia_ax_unavailable") from exc
    if proc.returncode:
        for code in ERROR_CODES:
            if code in proc.stderr:
                raise AmneziaAXError(code)
        raise AmneziaAXError("amnezia_ax_unavailable")
    try:
        catalog = json.loads(proc.stdout)
        if not isinstance(catalog, dict) or not isinstance(catalog.get("profiles"), list):
            raise ValueError("invalid native payload")
        return catalog
    except (ValueError, TypeError) as exc:
        raise AmneziaAXError("amnezia_ax_unavailable") from exc
