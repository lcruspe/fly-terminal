#!/usr/bin/env python3
"""Select external-only RoomAudio workspace: writable MacSSD data, then WD.

Mount checks are mandatory. Never create /Volumes/<disk> as a shadow
directory on the Mac system drive when removable storage is disconnected.
"""
import os
from pathlib import Path
import shutil
import tempfile

SSD_DATA = Path("/Volumes/MacSSD\u00a0— данные")
WD = Path("/Volumes/WD")
SSD_WORK = Path("RoomAudio-work")
WD_WORK = Path("RoomAudio-work")
VOLUMES = ((SSD_DATA, SSD_WORK), (WD, WD_WORK))


def active_roots():
    for mount, relative in VOLUMES:
        if os.path.ismount(str(mount)) and mount.is_dir():
            yield mount / relative


def _ensure_private(directory):
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:
        pass  # Windows-formatted WD does not support POSIX chmod.
    return directory


def work_dir(kind):
    if kind not in ("tmp", "reports/audio", "transcripts"):
        raise ValueError("Invalid RoomAudio work directory")
    failures = []
    for root in active_roots():
        try:
            target = _ensure_private(root / kind)
            # os.access is unreliable for some external filesystems: try a write.
            fd, probe = tempfile.mkstemp(prefix=".roomaudio-probe-", dir=str(target))
            os.close(fd)
            os.unlink(probe)
            return target
        except OSError as exc:
            failures.append(str(exc))
    raise RuntimeError("Neither writable external MacSSD nor WD is mounted: " +
                       "; ".join(failures))


def available_report_dirs():
    for root in active_roots():
        directory = root / "reports" / "audio"
        if directory.is_dir():
            yield directory


def report_file(name):
    """Search both disks: old reports remain accessible when SSD is detached."""
    for directory in available_report_dirs():
        candidate = directory / name
        try:
            if candidate.is_file() and candidate.resolve().parent == directory.resolve():
                return candidate
        except OSError:
            continue
    return None


def mirror_report(source):
    """Maintain a private WD copy for SSD detach; never write under an unmounted WD."""
    wdroot = WD / WD_WORK
    if not os.path.ismount(str(WD)) or source.parent == wdroot / "reports/audio":
        return False
    destdir = _ensure_private(wdroot / "reports" / "audio")
    dest = destdir / source.name
    fd, tmp = tempfile.mkstemp(prefix=".roomaudio-copy-", dir=str(destdir))
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, out, length=1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, dest)
        return True
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)