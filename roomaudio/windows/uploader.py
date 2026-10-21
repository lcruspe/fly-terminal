# RoomAudio reliable uploader for Windows / Python standard library.
# No credentials in source: all configuration from local client.json.
from pathlib import Path
import hashlib
import json
import logging
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

# A machine-wide proxy must never intercept direct RoomAudio LAN uploads.
DIRECT_HTTP = build_opener(ProxyHandler({}))
from speech_activity import detect_file, text_ranges

HOME = Path(__file__).resolve().parent
CONF = json.loads((HOME / "client.json").read_text(encoding="utf-8-sig"))
BUFFER = Path(CONF["buffer"])
SERVER = CONF["server"].rstrip("/")
KEY = CONF["ingest_key"]
BUFFER.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(HOME / "uploader.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8"
)

def once():
    transferred = 0
    for p in sorted(BUFFER.glob("*.mp3")):
        try:
            info = p.stat()
            # Never upload the segment FFmpeg is currently writing.
            if info.st_size < 200 or time.time() - info.st_mtime < 2:
                continue
            before = (info.st_size, info.st_mtime_ns)
            markers = p.with_suffix('.speech.json')
            if markers.is_file():
                spans = json.loads(markers.read_text(encoding='utf-8'))
            else:
                spans, _ = detect_file(p, CONF['ffmpeg_path'])
            if not isinstance(spans,list):
                raise RuntimeError('Invalid speech marker data')
            voice_ranges = text_ranges(spans)
            data = p.read_bytes()
            after = p.stat()
            if (after.st_size, after.st_mtime_ns) != before:
                continue
            req = Request(
                SERVER + "/ingest/" + p.name,
                data=data,
                headers={
                    "X-Ingest-Key": KEY,
                    "X-SHA256": hashlib.sha256(data).hexdigest(),
                    "Content-Type": "audio/mpeg",
                    "X-Speech-Ranges": voice_ranges,
                }, method="POST"
            )
            with DIRECT_HTTP.open(req, timeout=15) as response:
                status = response.status
                response.read()
            if status not in (200, 201):
                raise RuntimeError("Unexpected HTTP " + str(status))
            # No delete if the underlying file changed while transferring.
            current = p.stat()
            if (current.st_size, current.st_mtime_ns) == before:
                p.unlink()
                markers.unlink(missing_ok=True)
            logging.info("Stored %s (%s), HTTP %d", p.name, before[0], status)
            transferred += 1
        except FileNotFoundError:
            continue
        except (HTTPError, URLError, OSError, RuntimeError) as exc:
            logging.error("Upload pending %s: %s", p.name, exc)
            print("Upload pending: %s -> %s" % (p.name, exc))
            break
    return transferred

if __name__ == "__main__":
    count = once()
    print("Uploaded segments:", count)
    if "--once" not in sys.argv:
        while True:
            time.sleep(1)
            count = once()
            if count:
                print("Uploaded segments:", count, flush=True)