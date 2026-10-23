"""Persistent, authenticated RoomAudio capture-mode state."""
from pathlib import Path
import json
import os
import secrets
import threading
import time

PATH=Path(__file__).resolve().parent/"capture_settings.json"
VALID={"continuous","voice","off"}
LOCK=threading.Lock()
STATE={"active":None,"last_seen":None,"speech_recent":False,"speech_last":None,"recovery_ack":None}

def _read():
    try:
        data=json.loads(PATH.read_text(encoding="utf-8"))
        return data if isinstance(data,dict) else {"mode":"off"}
    except FileNotFoundError:
        return {"mode":"continuous"}
    except (ValueError,OSError):
        return {"mode":"off"}

def _write(data):
    temp=PATH.with_name(PATH.name+".tmp")
    try:
        with temp.open("w",encoding="utf-8") as f:
            json.dump(data,f)
            f.flush()
            os.fsync(f.fileno())
        temp.chmod(0o600)
        os.replace(temp,PATH)
    finally:
        temp.unlink(missing_ok=True)

def mode():
    with LOCK:
        result=_read().get("mode","off")
        return result if result in VALID else "off"

def set_mode(value):
    if value not in VALID:
        raise ValueError("Invalid capture mode")
    with LOCK:
        data=_read()
        data.update(mode=value,updated_at=time.time())
        _write(data)
    return value

def request_recovery():
    """Queue a capture-tree restart without changing the selected recording mode."""
    with LOCK:
        data=_read()
        if time.time()-data.get("recovery_requested_at",0)<15:
            return data["recovery_id"],False
        token=secrets.token_hex(16)
        data.update(recovery_id=token,recovery_requested_at=time.time())
        _write(data)
        return token,True

def heartbeat(active,speech=False,recovery_ack=None):
    if active not in VALID|{"starting","error"}:
        active="error"
    with LOCK:
        STATE["active"]=active
        STATE["last_seen"]=time.time()
        STATE["speech_recent"]=bool(speech)
        STATE["recovery_ack"]=recovery_ack
        if speech:
            STATE["speech_last"]=time.time()

def status():
    result=mode()
    with LOCK:
        saved=_read()
        seen=STATE["last_seen"]
        return {"mode":result,
                "client_connected":bool(seen and time.time()-seen<15),
                "active_mode":STATE["active"] if seen and time.time()-seen<15 else None,
                "speech_recent":bool(STATE["speech_recent"] and seen and time.time()-seen<15),
                "speech_last":STATE["speech_last"],
                "client_last_seen":seen,
                "recovery_id":saved.get("recovery_id"),
                "recovery_requested_at":saved.get("recovery_requested_at"),
                "recovery_ack":STATE["recovery_ack"] if seen and time.time()-seen<15 else None}
