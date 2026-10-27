"""Persisted RoomAudio capture control and Moscow-time weekly schedule."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os
import re
import secrets
import threading
import time

PATH = Path(__file__).resolve().parent / "capture_settings.json"
VALID = {"continuous", "voice", "off"}
SCHEDULE_MODES = {"continuous", "voice"}
TIMEZONE = "Europe/Moscow"
ZONE = ZoneInfo(TIMEZONE)
WEEK = 7 * 24 * 60
MAX_RULES = 14
LOCK = threading.Lock()
STATE = {"active": None, "last_seen": None, "speech_recent": False,
         "speech_last": None, "recovery_ack": None}


def _read():
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"mode": "off"}
    except FileNotFoundError:
        return {"mode": "continuous"}
    except (ValueError, OSError):
        return {"mode": "off"}


def _write(data):
    temp = PATH.with_name(PATH.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        temp.chmod(0o600)
        os.replace(temp, PATH)
    finally:
        temp.unlink(missing_ok=True)


def _minutes(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("Time must be HH:MM")
    return int(value[:2]) * 60 + int(value[3:])


def _ranges(rules):
    """Normalize active windows on a circular week; support midnight rollover."""
    result = []
    for rule in rules:
        start, end = _minutes(rule["start"]), _minutes(rule["end"])
        duration = (end - start) % (24 * 60)
        for day in rule["days"]:
            base = day * 1440 + start
            result.append((base, base + duration))
    return result


def _covered(minute, windows):
    return any((start <= minute < end or start <= minute + WEEK < end)
               for start, end in windows)


def _schedule_state(data, now=None):
    enabled = data.get("schedule_enabled") is True
    rules = data.get("schedule_rules", [])
    schedule_mode = data.get("schedule_mode", "voice")
    manual = data.get("mode", "off")
    if manual not in VALID:
        manual = "off"
    if not enabled or not isinstance(rules, list) or not rules:
        return manual, {"enabled": False, "rules": rules if isinstance(rules, list) else [],
                        "mode": schedule_mode, "timezone": TIMEZONE,
                        "active": False, "next_transition_at": None,
                        "next_mode": None}
    now = time.time() if now is None else now
    local = datetime.fromtimestamp(now, ZONE)
    minute = local.weekday() * 1440 + local.hour * 60 + local.minute
    windows = _ranges(rules)
    active = _covered(minute, windows)
    effective = schedule_mode if active else "off"
    # A transition is meaningful only when the active state changes,
    # not when overlapping/successive entries share a boundary.
    boundaries = set()
    for start, end in windows:
        boundaries.add(start % WEEK)
        boundaries.add(end % WEEK)
    next_at, next_mode = None, None
    for boundary in sorted(boundaries, key=lambda b: (b - minute) % WEEK or WEEK):
        if _covered(boundary, windows) == active:
            continue
        delta = (boundary - minute) % WEEK or WEEK
        candidate = datetime.fromtimestamp(now, ZONE).replace(second=0, microsecond=0)
        from datetime import timedelta
        next_at = (candidate + timedelta(minutes=delta)).timestamp()
        next_mode = schedule_mode if not active else "off"
        break
    return effective, {"enabled": True, "rules": rules, "mode": schedule_mode,
                       "timezone": TIMEZONE, "active": active,
                       "next_transition_at": next_at, "next_mode": next_mode}


def validate_schedule(payload):
    if not isinstance(payload, dict) or set(payload) != {"enabled", "mode", "rules"}:
        raise ValueError("Invalid schedule object")
    enabled, schedule_mode, rules = payload["enabled"], payload["mode"], payload["rules"]
    if not isinstance(enabled, bool) or schedule_mode not in SCHEDULE_MODES:
        raise ValueError("Invalid schedule options")
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise ValueError("Too many schedule intervals")
    if enabled and not rules:
        raise ValueError("Select at least one interval")
    clean = []
    covered = bytearray(WEEK)
    for item in rules:
        if not isinstance(item, dict) or set(item) != {"days", "start", "end"}:
            raise ValueError("Invalid interval")
        days = item["days"]
        if (not isinstance(days, list) or not days or len(days) > 7 or
                any(type(day) is not int or day < 0 or day > 6 for day in days) or
                len(days) != len(set(days))):
            raise ValueError("Select unique weekdays")
        start, end = _minutes(item["start"]), _minutes(item["end"])
        if start == end:
            raise ValueError("Start and end must differ")
        normalized = {"days": sorted(days), "start": item["start"], "end": item["end"]}
        for left, right in _ranges([normalized]):
            for offset in range(left, right):
                index = offset % WEEK
                if covered[index]:
                    raise ValueError("Intervals must not overlap")
                covered[index] = 1
        clean.append(normalized)
    return enabled, schedule_mode, clean


def set_schedule(payload):
    enabled, schedule_mode, rules = validate_schedule(payload)
    with LOCK:
        data = _read()
        data.update(schedule_enabled=enabled, schedule_mode=schedule_mode,
                    schedule_rules=rules, schedule_updated_at=time.time())
        _write(data)


def mode():
    with LOCK:
        return _schedule_state(_read())[0]


def set_mode(value):
    if value not in VALID:
        raise ValueError("Invalid capture mode")
    with LOCK:
        data = _read()
        # Explicit selection always takes priority and suspends automation.
        data.update(mode=value, schedule_enabled=False, updated_at=time.time())
        _write(data)
    return value


def request_recovery():
    """Queue capture restart without changing automatic/manual selection."""
    with LOCK:
        data = _read()
        if time.time() - data.get("recovery_requested_at", 0) < 15:
            return data["recovery_id"], False
        token = secrets.token_hex(16)
        data.update(recovery_id=token, recovery_requested_at=time.time())
        _write(data)
        return token, True


def heartbeat(active, speech=False, recovery_ack=None):
    if active not in VALID | {"starting", "error"}:
        active = "error"
    with LOCK:
        STATE["active"] = active
        STATE["last_seen"] = time.time()
        STATE["speech_recent"] = bool(speech)
        STATE["recovery_ack"] = recovery_ack
        if speech:
            STATE["speech_last"] = time.time()


def status():
    with LOCK:
        saved = _read()
        effective, schedule = _schedule_state(saved)
        seen = STATE["last_seen"]
        connected = bool(seen and time.time() - seen < 15)
        return {"mode": effective,
                "manual_mode": saved.get("mode", "off"),
                "schedule": schedule,
                "client_connected": connected,
                "active_mode": STATE["active"] if connected else None,
                "speech_recent": bool(STATE["speech_recent"] and connected),
                "speech_last": STATE["speech_last"],
                "client_last_seen": seen,
                "recovery_id": saved.get("recovery_id"),
                "recovery_requested_at": saved.get("recovery_requested_at"),
                "recovery_ack": STATE["recovery_ack"] if connected else None}
