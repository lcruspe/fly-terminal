"""Two-phase, reversible removal of MP3 fragments without detected speech.

No background deletion. 1) scan candidates, 2) explicit confirmed move to trash.
A conservative WebRTC VAD and an amplitude gate must agree on no voice.
"""
from __future__ import annotations
from pathlib import Path
from contextlib import closing
import datetime as dt
import json
import os
import re
import shutil
import secrets
import sqlite3
import subprocess
import threading
import time
from urllib.parse import parse_qs
import archive_api

LOCK=threading.RLock()
JOBS={}
BUSY=False
NAME=re.compile(r"^\d{8}T\d{6}\.mp3$")
BATCH_ID=re.compile(r"^[0-9]{8}T[0-9]{6}-[a-f0-9]{12}$")
APP=Path(__file__).resolve().parent
VAD_PY=APP/".vad-venv/bin/python"
VAD=APP/"vad_inspect.py"
CACHE=APP/"archive-analysis.sqlite3"
PREVIEW_LIFETIME=3600

def analysis_db():
    db=sqlite3.connect(CACHE,timeout=12)
    db.execute("""CREATE TABLE IF NOT EXISTS examined(
        file TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER,
        result_json TEXT NOT NULL, inspected_at REAL NOT NULL)""")
    return db

def all_records(root, scope, begin, end):
    if scope=="all":
        dirs=sorted((d for d in root.iterdir() if d.is_dir() and
                    archive_api.DAY.fullmatch(d.name)),key=lambda p:p.name)
    else:
        dirs=[root/key for key in archive_api.dates_between(begin,end)]
    files=[]
    cutoff=time.time()-120  # Do not race the newest fragment or the uploader.
    for folder in dirs:
        if not folder.is_dir():continue
        for path in folder.glob("*.mp3"):
            if not NAME.fullmatch(path.name) or path.is_symlink():continue
            try:
                when=archive_api.stamp_parse(path.stem)
                stat=path.stat()
                if (scope=="period" and not begin<=when<end) or stat.st_mtime>cutoff:
                    continue
                if stat.st_size<200: continue  # broken/in-progress files are not "no voice"
                files.append((when,path,stat))
            except (ValueError,OSError):
                continue
    return sorted(files,key=lambda x:x[0])

def protected_speech_files():
    db=APP/"speech.sqlite3"
    if not db.is_file():return set()
    try:
        with closing(sqlite3.connect(f"file:{db}?mode=ro",uri=True,timeout=10)) as conn:
            return {name for name,ranges in conn.execute("SELECT filename,ranges FROM speech")
                    if len(json.loads(ranges))>0}
    except (sqlite3.Error, ValueError, OSError):
        # Unreadable positive markers are not evidence of absence.
        return None

def check_one(path,stat,db):
    cached=db.execute("SELECT result_json FROM examined WHERE file=? AND size=? AND mtime_ns=?",
                      (str(path),stat.st_size,stat.st_mtime_ns)).fetchone()
    if cached:return json.loads(cached[0])
    try:
        result=subprocess.run([str(VAD_PY),str(VAD),str(path)],capture_output=True,
                              text=True,timeout=38,check=True)
        report=json.loads(result.stdout)
        if report.get("status") not in {"no_voice","voice","uncertain","error"}:
            raise RuntimeError("Classifier returned unknown status")
    except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired,
            json.JSONDecodeError,RuntimeError) as exc:
        report={"status":"error","reason":str(exc)[:180]}
    db.execute("INSERT OR REPLACE INTO examined VALUES(?,?,?,?,?)",
               (str(path),stat.st_size,stat.st_mtime_ns,json.dumps(report),time.time()))
    db.commit()
    return report

def run_scan(jid,root):
    global BUSY
    with LOCK:job=JOBS[jid]
    try:
        if not VAD_PY.is_file():
            raise RuntimeError("The voice detector is not installed")
        protected=protected_speech_files()
        if protected is None:
            raise RuntimeError("Speech marker database unavailable; scan aborted")
        files=all_records(root,job["scope"],job["begin"],job["end"])
        with LOCK:job["total"]=len(files)
        cache=analysis_db()
        try:
            for _,path,stat in files:
                with LOCK:
                    if job["status"]=="cancelled":break
                # Audio with known positive speech markers is never deleted.
                if path.name in protected:
                    status,reason,detail="voice","known_speech_markers",{}
                else:
                    detail=check_one(path,stat,cache)
                    status=detail["status"]
                    reason=detail.get("reason","")
                with LOCK:
                    job["scanned"]+=1
                    job["counts"][status]+=1
                    if status=="no_voice":
                        job["candidates"].append({
                            "day":path.parent.name,"name":path.name,
                            "bytes":stat.st_size,"mtime_ns":stat.st_mtime_ns,
                            "reason":reason,"mean_db":detail.get("mean_db"),
                            "peak_db":detail.get("peak_db")})
                        job["bytes"]+=stat.st_size
        finally:
            cache.close()
        with LOCK:
            job["status"]="ready" if job["status"]!="cancelled" else "cancelled"
            job["finished_at"]=time.time()
    except Exception as exc:
        with LOCK:
            job["status"]="error"
            job["error"]=str(exc)[:200]
    finally:
        with LOCK:BUSY=False

def start_preview(root,payload):
    global BUSY
    scope=payload.get("scope")
    if scope not in ("period","all"):raise ValueError("Expected scope: period or all")
    begin=end=None
    if scope=="period":
        begin=archive_api.moment(payload.get("start"))
        end=archive_api.moment(payload.get("end"))
        if not dt.timedelta(0)<end-begin<=dt.timedelta(days=1):
            raise ValueError("Selection must be between 1 second and 24 hours")
    with LOCK:
        if BUSY:
            raise RuntimeError("An archive scan is already in progress")
        for key in list(JOBS):
            if time.time()-JOBS[key]["created"]>PREVIEW_LIFETIME:
                del JOBS[key]
        jid=secrets.token_urlsafe(18)
        JOBS[jid]={"id":jid,"scope":scope,"begin":begin,"end":end,
                   "created":time.time(),"status":"scanning",
                   "scanned":0,"total":0,"counts":{"no_voice":0,"voice":0,"uncertain":0,"error":0},
                   "candidates":[],"bytes":0,"error":None,"finished_at":None,
                   "batch":None}
        BUSY=True
    threading.Thread(target=run_scan,args=(jid,root),daemon=True,
                     name="roomaudio-silence-scan").start()
    return jid

def summary(jid):
    with LOCK:
        job=JOBS.get(jid)
        if not job:raise KeyError("Preview expired; rescan required")
        sample=job["candidates"][:30] if job["status"]=="ready" else []
        return {"job":jid,"status":job["status"],"scope":job["scope"],
                "scanned":job["scanned"],"total":job["total"],
                "counts":dict(job["counts"]),"candidates":len(job["candidates"]),
                "bytes":job["bytes"],"sample":sample,
                "error":job["error"],"batch":job["batch"],
                "created_at":job["created"]}

def trash_root(root):
    # Sibling of archive on the same volume: rename remains atomic.
    return root.parent/"archive-trash"

def write_manifest(path,manifest):
    temporary=path.with_suffix(".json.pending")
    try:
        with temporary.open("w",encoding="utf-8") as f:
            json.dump(manifest,f,ensure_ascii=False,indent=2)
            f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)

def move_to_trash(root,payload):
    jid=payload.get("job")
    if not isinstance(jid,str) or len(jid)>100:
        raise ValueError("Invalid preview ID")
    if payload.get("confirm")!="MOVE_TO_TRASH":
        raise ValueError("Confirmation required")
    with LOCK:
        job=JOBS.get(jid)
        if not job or job["status"]!="ready" or job["batch"] or time.time()-job["created"]>PREVIEW_LIFETIME:
            raise ValueError("Preview expired or already used")
        if payload.get("expected_count")!=len(job["candidates"]):
            raise ValueError("Candidate count has changed")
        if not job["candidates"]:
            raise ValueError("No fragments to remove")
        # Atomically mark the snapshot as consumed to block parallel operations.
        job["status"]="moving"
        candidates=list(job["candidates"])
    batch=time.strftime("%Y%m%dT%H%M%S")+"-"+secrets.token_hex(6)
    destination=trash_root(root)/batch
    destination.mkdir(parents=True,exist_ok=False,mode=0o700)
    manifest={"id":batch,"created_at":time.time(),"scope":job["scope"],
              "files":[],"skipped":[],"restored":[]}
    manifest_file=destination/"manifest.json"
    write_manifest(manifest_file,manifest)
    positive=protected_speech_files()
    if positive is None:
        with LOCK:job["status"]="error";job["error"]="Speech index unavailable"
        return {"batch":batch,"moved":0,"skipped":len(candidates),"bytes":0}
    moved_bytes=0
    try:
        for item in candidates:
            source=root/item["day"]/item["name"]
            if item["name"] in positive or source.is_symlink():
                manifest["skipped"].append(item["name"]);continue
            try:
                stat=source.stat()
                if stat.st_size!=item["bytes"] or stat.st_mtime_ns!=item["mtime_ns"]:
                    manifest["skipped"].append(item["name"]);continue
                target=destination/item["day"]/item["name"]
                target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                if target.exists():
                    manifest["skipped"].append(item["name"]);continue
                os.replace(source,target)
                manifest["files"].append({"day":item["day"],"name":item["name"],
                                          "size":item["bytes"],"restored":False})
                moved_bytes+=item["bytes"]
                write_manifest(manifest_file,manifest)
            except OSError:
                manifest["skipped"].append(item["name"])
                write_manifest(manifest_file,manifest)
    finally:
        with LOCK:
            job["batch"]=batch
            job["status"]="moved"
    return {"batch":batch,"moved":len(manifest["files"]),
            "skipped":len(manifest["skipped"]),"bytes":moved_bytes}

def available_batches(root):
    dest=trash_root(root)
    if not dest.is_dir():return []
    result=[]
    for f in sorted(dest.glob("*/manifest.json"),reverse=True):
        if not BATCH_ID.fullmatch(f.parent.name):continue
        try:
            m=json.loads(f.read_text())
            items=[r for r in m["files"] if not r.get("restored")]
            result.append({"batch":m["id"],"created_at":m["created_at"],
                           "files":len(items),"bytes":sum(r["size"] for r in items)})
        except (OSError,KeyError,ValueError):continue
    return result[:30]

def restore(root,payload):
    batch=payload.get("batch")
    if not isinstance(batch,str) or not BATCH_ID.fullmatch(batch):
        raise ValueError("Invalid trash batch")
    if payload.get("confirm")!="RESTORE":
        raise ValueError("Confirmation required")
    folder=trash_root(root)/batch
    manifest_file=folder/"manifest.json"
    manifest=json.loads(manifest_file.read_text())
    if manifest.get("id")!=batch:raise ValueError("Trash manifest mismatch")
    restored=skipped=0
    for item in manifest["files"]:
        if item.get("restored"):continue
        day,name=item["day"],item["name"]
        if not archive_api.DAY.fullmatch(day) or not NAME.fullmatch(name):
            skipped+=1;continue
        source=folder/day/name;dest=root/day/name
        if not source.is_file() or dest.exists():
            skipped+=1;continue
        dest.parent.mkdir(parents=True,exist_ok=True)
        os.replace(source,dest)
        item["restored"]=True;restored+=1
        write_manifest(manifest_file,manifest)
    return {"batch":batch,"restored":restored,"skipped":skipped}

def purge_trash(root,payload):
    batch=payload.get("batch")
    if not isinstance(batch,str) or not BATCH_ID.fullmatch(batch):
        raise ValueError("Invalid trash batch")
    if payload.get("confirm")!="DELETE_FOREVER":
        raise ValueError("Permanent deletion requires explicit confirmation")
    folder=trash_root(root)/batch
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Trash batch unavailable")
    manifest=json.loads((folder/"manifest.json").read_text())
    if manifest.get("id")!=batch:
        raise ValueError("Trash manifest mismatch")
    # Never follow symlinks while recursively deleting.
    if any(path.is_symlink() for path in folder.rglob("*")):
        raise RuntimeError("Trash includes a symlink; deletion refused")
    files=[r for r in manifest["files"] if not r.get("restored")]
    total=0
    count=0
    for entry in files:
        d,n=entry["day"],entry["name"]
        if not archive_api.DAY.fullmatch(d) or not NAME.fullmatch(n):
            raise ValueError("Invalid archive manifest entry")
        candidate=folder/d/n
        if candidate.is_file():
            total+=candidate.stat().st_size
            count+=1
    shutil.rmtree(folder)
    return {"batch":batch,"deleted":count,"bytes":total}

def api_get(handler,path,query,root):
    if path=="/api/archive/cleanup/status":
        jid=query.get("job",[""])[0]
        try:return handler.json_reply(summary(jid))
        except KeyError:return handler.reply(404,"Preview unavailable")
    if path=="/api/archive/cleanup/trash":
        return handler.json_reply({"batches":available_batches(root)})
    return handler.reply(404,"Unknown cleanup endpoint")

def api_post(handler,path,payload,root):
    try:
        if path=="/api/archive/cleanup/scan":
            return handler.json_reply({"job":start_preview(root,payload)})
        if path=="/api/archive/cleanup/apply":
            return handler.json_reply(move_to_trash(root,payload))
        if path=="/api/archive/cleanup/restore":
            return handler.json_reply(restore(root,payload))
        if path=="/api/archive/cleanup/purge":
            return handler.json_reply(purge_trash(root,payload))
        return handler.reply(404,"Unknown cleanup endpoint")
    except ValueError as exc:
        return handler.reply(400,str(exc))
    except RuntimeError as exc:
        return handler.reply(409,str(exc))
    except (OSError,sqlite3.Error,KeyError,json.JSONDecodeError) as exc:
        print("cleanup failure",repr(exc),flush=True)
        return handler.reply(503,"Cleanup unavailable")
