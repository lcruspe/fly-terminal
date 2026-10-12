"""RoomAudio speech-marker index; independent of Whisper transcripts."""
from pathlib import Path
import datetime as dt
from contextlib import closing
import json
import re
import sqlite3
import threading

ROOT=Path(__file__).resolve().parent
DB=ROOT/"speech.sqlite3"
GUARD=threading.Lock()
NAME=re.compile(r"^\d{8}T\d{6}\.mp3$")
RANGE=re.compile(r"^(\d+(?:\.\d{1,2})?)-(\d+(?:\.\d{1,2})?)$")

def parse_ranges(value):
    if not value:
        return []
    if len(value)>512:
        raise ValueError("Speech marker data too large")
    output=[]
    for part in value.split(","):
        match=RANGE.fullmatch(part)
        if not match:
            raise ValueError("Bad speech range")
        start,end=map(float,match.groups())
        if not 0 <= start < end <= 16:
            raise ValueError("Speech range outside fragment")
        output.append([round(start,2),round(end,2)])
    return merge(output)

def merge(ranges):
    result=[]
    for start,end in sorted(ranges):
        if result and start<=result[-1][1]+0.40:
            result[-1][1]=round(max(end,result[-1][1]),2)
        else:
            result.append([round(start,2),round(end,2)])
    return result

def connect():
    db=sqlite3.connect(str(DB),timeout=8)
    db.execute("""CREATE TABLE IF NOT EXISTS speech (
        filename TEXT PRIMARY KEY, recorded_at TEXT NOT NULL,
        ranges TEXT NOT NULL, INDEXED INTEGER DEFAULT 1)""")
    db.execute("CREATE INDEX IF NOT EXISTS speech_by_time ON speech(recorded_at)")
    return db

def save(filename,encoded):
    if not NAME.fullmatch(filename):
        raise ValueError("Bad segment name")
    spans=parse_ranges(encoded)
    start=dt.datetime.strptime(filename[:-4],"%Y%m%dT%H%M%S")
    with GUARD:
        with closing(connect()) as db, db:
            db.execute("INSERT OR REPLACE INTO speech (filename,recorded_at,ranges) VALUES (?,?,?)",
                       (filename,start.isoformat(timespec="seconds"),json.dumps(spans)))
    return spans

def find(start,end):
    with GUARD:
        with closing(connect()) as db, db:
            rows=db.execute(
               "SELECT filename,recorded_at,ranges FROM speech WHERE recorded_at>=? AND recorded_at<? ORDER BY recorded_at",
               (start.isoformat(timespec="seconds"),end.isoformat(timespec="seconds"))).fetchall()
    output=[]
    for name,when,data in rows:
        a=dt.datetime.fromisoformat(when)
        for lo,hi in json.loads(data):
            t=a+dt.timedelta(seconds=float(lo))
            if start<=t<end:
                output.append({"time":t.isoformat(timespec="milliseconds"),"file":name,
                               "offset":lo,"length":round(hi-lo,2)})
    return output
