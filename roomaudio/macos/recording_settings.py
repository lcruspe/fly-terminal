"""Persistent, authenticated RoomAudio capture-mode state."""
from pathlib import Path
import json
import os
import threading
import time

PATH=Path(__file__).resolve().parent/"capture_settings.json"
VALID={"continuous","voice","off"}
LOCK=threading.Lock()
STATE={"active":None,"last_seen":None,"speech_recent":False,"speech_last":None}

def mode():
    with LOCK:
        try:
            data=json.loads(PATH.read_text(encoding="utf-8"))
            result=data.get("mode","continuous")
            return result if result in VALID else "off"
        except FileNotFoundError:
            return "continuous"
        except (ValueError,OSError):
            return "off"

def set_mode(value):
    if value not in VALID:
        raise ValueError("Invalid capture mode")
    with LOCK:
        temp=PATH.with_name(PATH.name+".tmp")
        try:
            with temp.open("w",encoding="utf-8") as f:
                json.dump({"mode":value,"updated_at":time.time()},f)
                f.flush()
                os.fsync(f.fileno())
            temp.chmod(0o600)
            os.replace(temp,PATH)
        finally:
            temp.unlink(missing_ok=True)
    return value

def heartbeat(active,speech=False):
    if active not in VALID|{"starting","error"}:
        active="error"
    with LOCK:
        STATE["active"]=active
        STATE["last_seen"]=time.time()
        STATE["speech_recent"]=bool(speech)
        if speech:
            STATE["speech_last"]=time.time()

def status():
    result=mode()
    with LOCK:
        seen=STATE["last_seen"]
        return {"mode":result,
                "client_connected":bool(seen and time.time()-seen<15),
                "active_mode":STATE["active"] if seen and time.time()-seen<15 else None,
                "speech_recent":bool(STATE["speech_recent"] and seen and time.time()-seen<15),
                "speech_last":STATE["speech_last"],
                "client_last_seen":seen}
