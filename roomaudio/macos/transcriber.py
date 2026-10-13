#!/usr/bin/env python3
"""RoomAudio ASR worker; preserves original audio, uses external whisper.cpp."""
import datetime as dt
import hashlib
import json
import logging
import audio_quality
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import storage_paths
import secrets
import time

APP = Path(__file__).resolve().parent
CFG = json.loads((APP / "config.json").read_text())
ROOT = Path(CFG["archive"])
MODEL = Path(CFG.get("transcription_model", "/Volumes/WD/RoomAudio/models/ggml-large-v3-turbo.bin"))
DB = APP / "transcripts.sqlite3"
FFMPEG = "/opt/homebrew/bin/ffmpeg"
WHISPER = "/opt/homebrew/bin/whisper-cli"
NAME = re.compile(r"^\d{8}T\d{6}\.mp3$")
DATE = re.compile(r"^\d{8}$")
GROUP_LENGTH = 120
STATUS = APP / "transcriber-status.json"
VAD_PY = APP / ".vad-venv/bin/python"
VAD_SCRIPT = APP / "vad_inspect.py"

def report_status(state, pending=0, group=None, error=None):
    report={"state":state,"pending":max(0,int(pending)),
            "group":group,"updated":time.time()}
    if error:report["error"]=str(error)[:160]
    temp=STATUS.with_name(".transcriber-status-"+secrets.token_hex(5))
    try:
        with temp.open("w",encoding="utf-8") as f:json.dump(report,f)
        temp.chmod(0o600)
        os.replace(temp,STATUS)
    finally:temp.unlink(missing_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def connect():
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("""CREATE TABLE IF NOT EXISTS transcripts (
      group_id TEXT PRIMARY KEY, day TEXT NOT NULL,
      started TEXT NOT NULL, ended TEXT NOT NULL,
      text TEXT NOT NULL, segments_json TEXT NOT NULL,
      files_json TEXT NOT NULL, processed_at TEXT NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_transcripts_day ON transcripts(day, started)")
    conn.commit()
    return conn

def all_groups():
    # Never create the external mount point as a local directory.
    if not os.path.ismount("/Volumes/WD") or not ROOT.is_dir():
        return {}
    current = time.time()
    groups = {}
    for folder in ROOT.iterdir():
        if not folder.is_dir() or not DATE.fullmatch(folder.name):
            continue
        for f in folder.glob("*.mp3"):
            if not NAME.fullmatch(f.name) or f.stat().st_size < 256:
                continue
            try:
                started = dt.datetime.strptime(f.stem, "%Y%m%dT%H%M%S")
            except ValueError:
                continue
            # Two-minute aligned windows; wait 50 s for late uploads.
            window = started.replace(minute=started.minute // 2 * 2, second=0)
            if (window + dt.timedelta(seconds=GROUP_LENGTH+50)).timestamp() > current:
                continue
            key = window.strftime("%Y%m%dT%H%M%S")
            groups.setdefault(key, []).append(f)
    return groups

def decode_timestamp(ms):
    ms = int(ms)
    return ms / 1000.0

# Stable rejection rules for common Whisper hallucinations, never generic speech.
CREDIT_PHRASE = re.compile(
    r"^(?:Редактор субтитров\b|Корректор А\.|Субтитры создавал\b|"
    r"Субтитры делал DimaTorzok\b|Добавил субтитры DimaTorzok\b)",
    re.IGNORECASE)
OUTRO_PHRASE = re.compile(r"^Продолжение следует[.!… ]*$", re.IGNORECASE)
OUTRO_LOOP = re.compile(r"^(?:Продолжение следует[.!… ]*){2,}$", re.IGNORECASE)

def remove_hallucinations(segments):
    if not segments:
        return []
    output = []
    for s in segments:
        text = s["text"].strip()
        # Credits and channel subtitles have repeatedly been invented on
        # near-silent source audio (never present in a real recording).
        if CREDIT_PHRASE.match(text) or OUTRO_LOOP.fullmatch(text):
            continue
        output.append(s)
    # Repeated fabricated video endings are common after genuine short speech.
    # Preserve preceding speech and discard only the repeated trailing suffix.
    trailing=0
    for item in reversed(output):
        if OUTRO_PHRASE.fullmatch(item["text"]):
            trailing+=1
        else:
            break
    if trailing >= 2:
        output=output[:-trailing]
    # A single "Продолжение следует" hallucinated across an entire 30 s window
    # is also not credible speech. Do not reject genuine short utterances.
    if len(output)==1 and OUTRO_PHRASE.fullmatch(output[0]["text"]):
        if float(output[0].get("end",0))-float(output[0].get("start",0)) >= 10:
            return []
    # Some model outputs combine the repeated credits into one segment.
    joined = " ".join(x["text"] for x in output).strip()
    if joined and len(joined) >= 32:
        token = re.sub(r"\s+", " ", joined).strip()
        if OUTRO_LOOP.fullmatch(token):
            return []
    return output

def process(files, gid):
    files = sorted(files)
    stamp = dt.datetime.strptime(files[0].stem, "%Y%m%dT%H%M%S")
    stop = dt.datetime.strptime(files[-1].stem, "%Y%m%dT%H%M%S") + dt.timedelta(seconds=15)
    with tempfile.TemporaryDirectory(prefix="ra-asr-", dir=str(storage_paths.work_dir("tmp"))) as folder:
        work = Path(folder)
        manifest = work / "input.txt"
        manifest.write_text("".join("file '" + str(p).replace("'", "'\\''") + "'\n" for p in files))
        wav = work / "voice.wav"
        # Moderate speech-band filtering and denoise; original archive untouched.
        filters = "highpass=f=95,lowpass=f=7500,afftdn=nr=8:nf=-35"
        command = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                   "-safe", "0", "-i", str(manifest), "-vn", "-af", filters,
                   "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)]
        subprocess.run(command, check=True, capture_output=True, timeout=120)
        # Whisper hallucinates subtitles on digital silence. Skip those groups.
        mean, peak = audio_quality.measure(wav, timeout=30)
        if audio_quality.silent(mean, peak):
            logging.info("Skipping digitally silent ASR group %s: mean %.1f peak %.1f dB",
                         gid, mean, peak)
            return (gid, stamp.strftime("%Y%m%d"),
                    stamp.isoformat(timespec="seconds"),
                    stop.isoformat(timespec="seconds"), "",
                    "[]", json.dumps([str(p) for p in files]),
                    dt.datetime.now().isoformat(timespec="seconds"))
        if VAD_PY.is_file() and VAD_SCRIPT.is_file():
            try:
                vad=subprocess.run([str(VAD_PY),str(VAD_SCRIPT),str(wav)],
                                   capture_output=True,text=True,timeout=45)
                if vad.returncode==0 and json.loads(vad.stdout).get("status")=="no_voice":
                    logging.info("Skipping speech-free ASR group %s",gid)
                    return (gid, stamp.strftime("%Y%m%d"),
                            stamp.isoformat(timespec="seconds"),
                            stop.isoformat(timespec="seconds"), "",
                            "[]",json.dumps([str(p) for p in files]),
                            dt.datetime.now().isoformat(timespec="seconds"))
            except (subprocess.SubprocessError,ValueError,OSError):
                logging.exception("VAD failure for %s; running Whisper",gid)
        outfile = work / "result"
        command = [WHISPER, "-m", str(MODEL), "-f", str(wav), "-l", "ru",
                   "-oj", "-of", str(outfile), "-sns", "-t", "6", "-np"]
        output = subprocess.run(command, capture_output=True, text=True, timeout=420)
        if output.returncode != 0:
            raise RuntimeError("whisper-cli: " + output.stderr[-1500:])
        result = json.loads((work / "result.json").read_text())
        segments = []
        for s in result.get("transcription", []):
            value = " ".join(s.get("text", "").split())
            if not value:
                continue
            offsets = s.get("offsets", {})
            begin = decode_timestamp(offsets.get("from", 0))
            end = decode_timestamp(offsets.get("to", 0))
            segments.append({"start": round(begin, 2), "end": round(end, 2), "text": value})
        before=len(segments)
        segments=remove_hallucinations(segments)
        if before!=len(segments):
            logging.warning("Removed %d Whisper hallucination segments in group %s",
                            before-len(segments),gid)
        transcript = " ".join(x["text"] for x in segments)
        return (gid, stamp.strftime("%Y%m%d"), stamp.isoformat(timespec="seconds"),
                stop.isoformat(timespec="seconds"), transcript,
                json.dumps(segments, ensure_ascii=False),
                json.dumps([str(p) for p in files]),
                dt.datetime.now().isoformat(timespec="seconds"))

def purge(conn):
    oldest = (dt.datetime.now().date() - dt.timedelta(days=int(CFG.get("retention_days", 30)))).strftime("%Y%m%d")
    conn.execute("DELETE FROM transcripts WHERE day < ?", (oldest,))
    conn.commit()

def finalize_model():
    if MODEL.is_file():
        return
    partial = Path(str(MODEL) + ".part")
    if not partial.is_file() or partial.stat().st_size != 1624555275:
        return
    digest = hashlib.sha256()
    with partial.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024*1024*4), b""):
            digest.update(chunk)
    if digest.hexdigest() != "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69":
        logging.error("Downloaded model checksum mismatch; refusing to load model")
        return
    partial.rename(MODEL)
    logging.info("Model verified and activated: %s", MODEL)

def loop(once=False):
    conn = connect()
    retry_after = {}
    while True:
        try:
            finalize_model()
            if not MODEL.is_file() or MODEL.stat().st_size < 500_000_000:
                logging.warning("Model missing/incomplete: %s", MODEL)
                if once:
                    return
                time.sleep(60)
                continue
            purge(conn)
            groups = all_groups()
            saved = {row[0] for row in conn.execute("SELECT group_id FROM transcripts")}
            remaining = [(key, files) for key, files in sorted(groups.items())
                         if key not in saved and retry_after.get(key, 0) < time.time()]
            cutoff=(dt.datetime.now()-dt.timedelta(hours=2)).strftime("%Y%m%dT%H%M%S")
            recent=[entry for entry in remaining if entry[0]>=cutoff]
            backlog=[entry for entry in remaining if entry[0]<cutoff]
            remaining=recent+backlog
            if not remaining:report_status("idle")
            for index,(key,files) in enumerate(remaining):
                report_status("processing",pending=len(remaining)-index,group=key)
                try:
                    logging.info("Transcribing %s (%d fragments)", key, len(files))
                    item = process(files, key)
                    conn.execute("INSERT OR IGNORE INTO transcripts VALUES(?,?,?,?,?,?,?,?)", item)
                    conn.commit()
                    logging.info("Finished %s: %d chars", key, len(item[4]))
                except Exception as exc:
                    retry_after[key] = time.time() + 180
                    logging.exception("Unable to transcribe %s: %s", key, exc)
                    report_status("error",pending=len(remaining)-index,group=key,error=exc)
                if once:
                    return
        except Exception as exc:
            logging.exception("Scanner failure: %s", exc)
            report_status("error",error=exc)
        if once:
            return
        time.sleep(25)

if __name__ == "__main__":
    import sys
    loop(once="--once" in sys.argv)