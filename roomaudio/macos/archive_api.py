"""RoomAudio archive API: chronological browser, bounded playback, transcript exports, spectrograms."""
from __future__ import annotations
from collections import defaultdict
import datetime as dt
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import threading
import time
from urllib.parse import quote
import speech_index

SEGMENT = re.compile(r"^\d{8}T\d{6}\.mp3$")
STAMP = re.compile(r"^\d{8}T\d{6}$")
DAY = re.compile(r"^\d{8}$")
FFMPEG = "/opt/homebrew/bin/ffmpeg"
SPECTRO_LOCK = threading.Lock()

def stamp_parse(value: str):
    if not STAMP.fullmatch(value):
        raise ValueError("Expected YYYYMMDDTHHMMSS")
    t = dt.datetime.strptime(value, "%Y%m%dT%H%M%S")
    if t.strftime("%Y%m%dT%H%M%S") != value:
        raise ValueError("Invalid timestamp")
    return t

def moment(value: str):
    if not isinstance(value, str) or len(value) not in (16, 19):
        raise ValueError("Invalid ISO datetime")
    t = dt.datetime.fromisoformat(value)
    if t.tzinfo is not None:
        raise ValueError("Local datetime required")
    return t

def bounds(query):
    a = moment(query.get("start", [""])[0])
    b = moment(query.get("end", [""])[0])
    if not dt.timedelta(0) < b-a <= dt.timedelta(days=1):
        raise ValueError("Period must be greater than zero and at most 24 hours")
    return a, b

def dates_between(a,b):
    date = a.date()
    while date <= b.date():
        yield date.strftime("%Y%m%d")
        date += dt.timedelta(days=1)

def fetch_segments(root, a, b):
    result = []
    for day in dates_between(a,b):
        folder = root/day
        if not folder.is_dir():
            continue
        for p in folder.glob("*.mp3"):
            if not SEGMENT.fullmatch(p.name):
                continue
            try:
                start = stamp_parse(p.stem)
                size = p.stat().st_size
                if size > 200 and a <= start < b:
                    result.append((start, p, size))
            except (OSError, ValueError):
                continue
    return sorted(result, key=lambda row: (row[0], row[1].name))

def transcript_rows(db, a, b):
    if not db.is_file():
        return []
    out = []
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT group_id, started, ended, text, segments_json FROM transcripts "
            "WHERE started < ? AND ended > ? ORDER BY started ASC LIMIT 1000",
            (b.isoformat(timespec="seconds"), a.isoformat(timespec="seconds"))
        ).fetchall()
        for r in rows:
            started = dt.datetime.fromisoformat(r["started"])
            segments = json.loads(r["segments_json"])
            if not segments and r["text"]:
                if a <= started < b:
                    out.append({"time": started.isoformat(timespec="seconds"),
                                "text": r["text"], "group": r["group_id"], "offset": 0})
            for s in segments:
                text = s.get("text", "").strip()
                if not text:
                    continue
                t = started + dt.timedelta(seconds=float(s.get("start", 0)))
                if a <= t < b:
                    out.append({"time": t.isoformat(timespec="seconds"),
                                "text": text, "group": r["group_id"],
                                "offset": max(0, float(s.get("start",0)))})
    return out

def total_days(root):
    days = []
    if not root.is_dir():
        return days
    for p in root.iterdir():
        if p.is_dir() and DAY.fullmatch(p.name):
            days.append(p.name)
    return sorted(days, reverse=True)

def archive_api(handler, path, query, root, app):
    """Returns True if the archive handler was responsible for this request."""
    if not (path.startswith("/api/archive/") or path.startswith("/period/")):
        return False
    def reply_error(code, message):
        handler.reply(code, message)
        return True
    try:
        if path == "/api/archive/days":
            handler.json_reply({"days": total_days(root)})
            return True
        if path == "/api/archive/latest":
            newest = None
            for d in total_days(root)[:3]:
                folder = root / d
                for file in folder.glob("*.mp3"):
                    if SEGMENT.fullmatch(file.name) and file.stat().st_size > 200:
                        if newest is None or file.name > newest.name:
                            newest = file
                if newest is not None:
                    break
            handler.json_reply({"time": stamp_parse(newest.stem).isoformat(timespec="seconds"),
                                "name": newest.name} if newest else {"time":None,"name":None})
            return True
        if path == "/api/archive/speech":
            a,b = bounds(query)
            items=speech_index.find(a,b)
            offsets={}
            playhead=0.0
            for start,source,size in fetch_segments(root,a,b):
                offsets[source.name]=playhead
                # Archived audio is CBR 96 kb/s MP3; subtract ID3 headers.
                playhead += max(0.0,(size-320)/12000)
            for item in items:
                if item["file"] in offsets:
                    item["position"]=round(offsets[item["file"]]+float(item["offset"]),2)
            items=[item for item in items if "position" in item]
            handler.json_reply({"items":items,"count":len(items),"playback_seconds":round(playhead,2)})
            return True

        if path == "/api/archive/records":
            a,b = bounds(query)
            items = fetch_segments(root,a,b)
            try:
                limit = min(200,max(1,int(query.get("limit",["80"])[0])))
                offset = max(0,int(query.get("offset",["0"])[0]))
            except (ValueError,OverflowError):
                return reply_error(400,"Bad paging")
            direction = query.get("sort",["asc"])[0]
            if direction not in ("asc","desc"):
                return reply_error(400,"Bad sort")
            buckets = defaultdict(int)
            for start,_,_ in items:
                minute = start.strftime("%Y-%m-%dT%H:%M")
                buckets[minute] += 1
            display = items[::-1] if direction == "desc" else items
            rows = [{"name":f.name, "time":t.isoformat(timespec="seconds"),
                     "duration":15, "bytes":size,
                     "token": handler.media_token("/segment/" + t.strftime("%Y%m%d") + "/" + f.name)}
                    for t,f,size in display[offset:offset+limit]]
            handler.json_reply({"total":len(items),"items":rows,"offset":offset,
                                "limit":limit,"minutes":dict(buckets),
                                "total_bytes":sum(it[2] for it in items),
                                "audio_seconds":len(items)*15})
            return True
        if path == "/api/archive/text":
            a,b = bounds(query)
            rows = transcript_rows(app/"transcripts.sqlite3",a,b)
            search = query.get("q",[""])[0].strip()[:120].casefold()
            if search:
                rows = [r for r in rows if search in r["text"].casefold()]
            handler.json_reply({"items":rows,"count":len(rows),
                                "start":a.isoformat(timespec="seconds"),
                                "end":b.isoformat(timespec="seconds")})
            return True
        if path == "/api/archive/export":
            a,b = bounds(query)
            rows = transcript_rows(app/"transcripts.sqlite3",a,b)
            fmt = query.get("format",["txt"])[0]
            if fmt not in ("txt","srt"):
                return reply_error(400,"Only txt and srt")
            if fmt == "txt":
                body = "\n".join("["+r["time"].replace("T"," ")+"] "+r["text"] for r in rows)
            else:
                def srt_time(seconds):
                    t = dt.timedelta(seconds=max(0,seconds))
                    total = int(t.total_seconds())
                    ms = int((t.total_seconds()%1)*1000)
                    return f"{total//3600:02}:{(total//60)%60:02}:{total%60:02},{ms:03}"
                # SRT relative to selected period: playable with the exported range.
                seq = []
                for i,row in enumerate(rows):
                    at = moment(row["time"])
                    begin = (at-a).total_seconds()
                    if i+1 < len(rows):
                        nxt = (moment(rows[i+1]["time"])-a).total_seconds()
                        finish = min(begin+6,max(begin+0.75,nxt))
                    else:
                        finish = min((b-a).total_seconds(),begin+4)
                    seq.append(f"{i+1}\n{srt_time(begin)} --> {srt_time(finish)}\n{row['text']}\n")
                body = "\n".join(seq)
            data = ("\ufeff"+body).encode("utf-8")
            title = f"RoomAudio-{a.strftime('%Y%m%d-%H%M')}-{b.strftime('%Y%m%d-%H%M')}.{fmt}"
            handler.reply(200,data,"text/plain; charset=utf-8",headers={
                "Content-Disposition":'attachment; filename="'+title+'"'
            })
            return True
        if path.startswith("/api/archive/spectrogram/"):
            stamp = path[len("/api/archive/spectrogram/"):]
            if not re.fullmatch(r"\d{8}T\d{6}\.png",stamp):
                return reply_error(400,"Invalid spectrogram id")
            audio = root/stamp[:8]/(stamp[:-4]+".mp3")
            if not audio.is_file() or audio.stat().st_size <= 200:
                return reply_error(404,"Audio not found")
            cache = app/"spectrogram-cache"
            cache.mkdir(mode=0o700,exist_ok=True)
            st = audio.stat()
            name = f"{audio.stem}-{st.st_size}-{st.st_mtime_ns}.png"
            output=cache/name
            if not output.is_file():
                with SPECTRO_LOCK:
                    if not output.is_file():
                        temp=cache/(name+".pending.png")
                        cmd=[FFMPEG,"-hide_banner","-nostdin","-loglevel","error","-y",
                             "-i",str(audio),"-lavfi",
                             "showspectrumpic=s=1200x300:legend=0:fscale=log:scale=log:color=viridis:start=80:stop=7800",
                             "-frames:v","1",str(temp)]
                        try:
                            subprocess.run(cmd,capture_output=True,check=True,timeout=35)
                            if not temp.is_file() or temp.stat().st_size<100:
                                raise RuntimeError("Empty spectrogram")
                            os.replace(temp,output)
                        finally:
                            temp.unlink(missing_ok=True)
            handler.send_file(output,"image/png")
            return True
        if path.startswith("/period/"):
            match = re.fullmatch(r"/period/(\d{8}T\d{6})/(\d{8}T\d{6})\.mp3",path)
            if not match:
                return reply_error(400,"Invalid audio period")
            a,b = stamp_parse(match.group(1)),stamp_parse(match.group(2))
            if not dt.timedelta(0) < b-a <= dt.timedelta(days=1):
                return reply_error(400,"Period must be at most one day")
            items = fetch_segments(root,a,b)
            if not items:
                return reply_error(404,"No recordings for the period")
            handler.send_audio_sequence([r[1] for r in items],f"RoomAudio-{match.group(1)}-{match.group(2)}.mp3")
            return True
        return reply_error(404,"Unknown archive endpoint")
    except (ValueError,TypeError) as exc:
        return reply_error(400,str(exc))
    except (sqlite3.Error,subprocess.CalledProcessError,subprocess.TimeoutExpired,OSError,RuntimeError) as exc:
        print("archive API error:",repr(exc),flush=True)
        return reply_error(503,"Archive temporarily unavailable")
