#!/usr/bin/env python3
"""Local, authenticated audio ingest and playback server."""
import base64
from contextlib import closing
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import archive_api
import archive_cleanup
import audio_quality
import recording_settings
import speech_index
import live_relay
import storage_paths
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from http.cookies import SimpleCookie, CookieError
from urllib.parse import urlsplit, parse_qs
import secrets

BASE = Path(__file__).resolve().parent
CONFIG = json.loads((BASE / "config.json").read_text())
ROOT = Path(CONFIG["archive"])
PORT = int(CONFIG.get("port", 8766))
SESSION_DAYS = 90
SESSION_SECONDS = SESSION_DAYS * 86400
SESSION_COOKIE = "ra_session"
SESSION_KEY = hmac.new(
    CONFIG["ingest_key"].encode(),
    ("roomaudio-session-v2:" + CONFIG["password"]).encode(),
    hashlib.sha256
).digest()
SEGMENT_RE = re.compile(r"^(\d{8})T(\d{6})\.mp3$")
DAY_RE = re.compile(r"^\d{8}$")
REPORT_AUDIO_RE = re.compile(r"^RoomAudio_20\d{2}-\d{2}-\d{2}_\d{4}-\d{4}_[a-z0-9_-]{1,80}\.mp3$")
condition = threading.Condition()
state = {"last_received": None, "last_name": None,
         "last_source_seen": None, "mic_silent": False,
         "mean_db": None, "peak_db": None}
if not os.path.ismount("/Volumes/WD"):
    raise RuntimeError("Archive disk /Volumes/WD is not mounted")
ROOT.mkdir(parents=True, exist_ok=True)

def segment_files(day):
    folder = ROOT / day
    if not DAY_RE.fullmatch(day) or not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.mp3") if SEGMENT_RE.fullmatch(p.name))

def recent_segments(limit=8):
    today = dt.datetime.now().date()
    files = []
    for offset in (2, 1, 0):
        files.extend(segment_files((today - dt.timedelta(days=offset)).strftime("%Y%m%d")))
    return files[-limit:]

def fresh_live_segments(limit=8, max_age=120):
    # Live audio must not replay days-old MP3s while the uploader catches up
    # with a historical backlog.
    now=dt.datetime.now()
    result=[]
    for file in recent_segments(limit):
        try:
            age=(now-dt.datetime.strptime(file.stem,"%Y%m%dT%H%M%S")).total_seconds()
            if -30<=age<=max_age:
                result.append(file)
        except ValueError:
            continue
    return result

def cleanup():
    cutoff = dt.datetime.now().date() - dt.timedelta(days=int(CONFIG.get("retention_days", 30)))
    if not ROOT.is_dir():
        return
    for folder in ROOT.iterdir():
        if folder.is_dir() and DAY_RE.fullmatch(folder.name):
            try:
                d = dt.datetime.strptime(folder.name, "%Y%m%d").date()
                if d < cutoff:
                    shutil.rmtree(folder)
            except (ValueError, OSError):
                pass

def maintenance():
    while True:
        try:
            cleanup()
        except Exception as exc:
            print("cleanup failed:", exc, flush=True)
        time.sleep(3600)

def asr_health():
    status=BASE/"transcriber-status.json"
    try:
        if status.stat().st_size>4096:
            return {"state":"unknown"}
        report=json.loads(status.read_text(encoding="utf-8"))
        return {key:report[key] for key in ("state","pending","group","updated","error")
                if key in report}
    except (OSError,ValueError,TypeError):
        return {"state":"unknown"}

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "RoomAudio/1.0"

    def log_message(self, fmt, *args):
        if self.path.startswith("/api/status"):
            return
        message = fmt % args if args else fmt
        clean = urlsplit(self.path).path
        if self.path != clean:
            message = message.replace(self.path, clean)
        super().log_message("%s", message)

    def reply(self, status, data=b"", content_type="text/plain; charset=utf-8", headers=None):
        if isinstance(data, str):
            data = data.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if data:
            self.wfile.write(data)

    def basic_valid(self):
        hdr = self.headers.get("Authorization", "")
        if not hdr.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(hdr[6:], validate=True).decode()
            username, password = raw.split(":", 1)
            return hmac.compare_digest(username, CONFIG["username"]) and hmac.compare_digest(password, CONFIG["password"])
        except (ValueError, UnicodeError):
            return False

    @staticmethod
    def cookie_value():
        expires = str(int(time.time()) + SESSION_SECONDS)
        nonce = secrets.token_urlsafe(24)
        raw = expires + "." + nonce
        signature = hmac.new(SESSION_KEY, raw.encode(), hashlib.sha256).hexdigest()
        return raw + "." + signature

    def session_valid(self):
        raw = self.headers.get("Cookie", "")
        if not raw or len(raw) > 4096:
            return False
        try:
            cookies = SimpleCookie()
            cookies.load(raw)
            if SESSION_COOKIE not in cookies:
                return False
            token = cookies[SESSION_COOKIE].value
            expires, nonce, signature = token.split(".")
            if not expires.isascii() or not expires.isdigit() or not 8 <= len(nonce) <= 64:
                return False
            expiry = int(expires)
            if not time.time() < expiry <= time.time() + SESSION_SECONDS + 60:
                return False
            expected = hmac.new(SESSION_KEY, (expires + "." + nonce).encode(), hashlib.sha256).hexdigest()
            return hmac.compare_digest(signature, expected)
        except (CookieError, ValueError, TypeError, KeyError):
            return False

    @staticmethod
    def is_media_path(path):
        return path in ("/live.mp3", "/live.m3u8") or path.startswith(("/archive/", "/clip/", "/segment/", "/period/"))

    @staticmethod
    def media_token(path):
        exp = int(time.time()) + 7200
        body = str(exp) + ":" + path
        return str(exp) + "." + hmac.new(SESSION_KEY, body.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def valid_media_token(path, token):
        if not Handler.is_media_path(path) or len(token) > 100:
            return False
        try:
            exp, signature = token.split(".")
            if not exp.isascii() or not exp.isdigit() or len(signature) != 64:
                return False
            now = int(time.time())
            if not now < int(exp) <= now + 7260:
                return False
            expected = hmac.new(SESSION_KEY, (exp + ":" + path).encode(), hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, signature)
        except (ValueError, TypeError):
            return False

    def authorized(self):
        return self.session_valid() or self.basic_valid()

    def require_auth(self):
        if self.authorized():
            return True
        # Deliberately no WWW-Authenticate: iOS home-screen apps otherwise re-prompt.
        self.reply(401, "Sign in at /roomaudio/")
        return False

    def direct_access(self):
        # Direct fallback is restricted to explicit LAN / Tailscale endpoints.
        # Reverse-proxied HTTPS retains Secure cookies and /roomaudio prefix.
        return self.headers.get("Host", "").lower() in (
            "192.168.1.173:8766", "kruspe-mac-mini.local:8766", "100.105.89.30:8766",
            "127.0.0.1:8766", "localhost:8766")

    def issue_cookie(self, value, max_age=SESSION_SECONDS):
        return (SESSION_COOKIE + "=" + value
                + ("; Path=/" if self.direct_access() else "; Path=/roomaudio")
                + "; Max-Age=" + str(max_age)
                + ("" if self.direct_access() else "; Secure")
                + "; HttpOnly; SameSite=Lax")

    def login_page(self):
        markup=(BASE / "login.html").read_bytes()
        if self.direct_access():
            markup=markup.replace(b'action="/roomaudio/login"',b'action="/login"')
        self.reply(200,markup,"text/html; charset=utf-8")

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/ingest/live":
            # Sequential transport for one continuous MP3 encoder. Never
            # concatenate separately encoded 15-second archive fragments.
            if not hmac.compare_digest(self.headers.get("X-Ingest-Key", ""),
                                       CONFIG["ingest_key"]):
                return self.reply(403, "Forbidden")
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "audio/mpeg":
                return self.reply(415, "Expected audio/mpeg")
            try:
                count = int(self.headers.get("Content-Length", "0"))
                sequence = int(self.headers.get("X-Live-Sequence", "-1"))
                session = self.headers.get("X-Live-Stream", "")
                if not 0 < count <= 65536 or not 0 <= sequence < 10_000_000:
                    raise ValueError("Invalid live packet")
                if not re.fullmatch(r"[0-9a-f]{32}", session):
                    raise ValueError("Invalid live stream identifier")
            except ValueError:
                return self.reply(400, "Invalid live packet")
            self.connection.settimeout(12)
            try:
                data = self.rfile.read(count)
            except (TimeoutError, ConnectionResetError, OSError):
                self.close_connection = True
                return
            if len(data) != count:
                return self.reply(400, "Truncated packet")
            if not live_relay.hub.ingest_packet(session, sequence, data):
                return self.reply(409, "Out-of-order live packet")
            return self.reply(200, "OK")
        if path.startswith("/api/archive/cleanup/"):
            if not self.authorized():
                return self.reply(401, "Login required")
            origin = self.headers.get("Origin", "")
            if origin not in ("https://129-158-49-130.sslip.io", "https://home.tail1c55c5.ts.net",
                               "http://127.0.0.1:8766", "http://localhost:8766",
                              "http://192.168.1.173:8766", "http://kruspe-mac-mini.local:8766", "http://100.105.89.30:8766"):
                return self.reply(403, "Invalid origin")
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self.reply(415, "Expected JSON")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 8192:
                    return self.reply(413, "Invalid payload")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    return self.reply(400, "Expected object")
            except (ValueError, UnicodeError, json.JSONDecodeError):
                return self.reply(400, "Invalid payload")
            return archive_cleanup.api_post(self,path,payload,ROOT)
        if path in ("/api/recording-mode", "/api/recovery"):
            # Rejected requests may still have unread bodies. Do not let a
            # proxy reuse that connection and parse the body as another method.
            self.close_connection = True
            if not self.authorized():
                return self.reply(401, "Login required")
            # A browser session must only change modes from our own site.
            origin = self.headers.get("Origin", "")
            if origin not in ("https://129-158-49-130.sslip.io", "https://home.tail1c55c5.ts.net", 
                               "http://127.0.0.1:8766", "http://localhost:8766",
                              "http://192.168.1.173:8766", "http://kruspe-mac-mini.local:8766", "http://100.105.89.30:8766"):
                return self.reply(403, "Invalid origin")
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self.reply(415, "Expected JSON")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 256:
                    return self.reply(413, "Invalid payload")
                payload = json.loads(self.rfile.read(length))
                if path == "/api/recovery":
                    if not isinstance(payload,dict) or payload:
                        return self.reply(400, "Expected empty object")
                    token,created=recording_settings.request_recovery()
                    if created:
                        live_relay.hub.reset()
                    return self.json_reply({"recovery_id":token,"capture":recording_settings.status()})
                requested = payload["mode"]
                if not isinstance(requested,str) or requested not in recording_settings.VALID:
                    return self.reply(400, "Unknown recording mode")
                recording_settings.set_mode(requested)
            except (ValueError, KeyError, TypeError, OSError):
                return self.reply(400, "Invalid settings")
            return self.json_reply(recording_settings.status())
        if path == "/login":
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/x-www-form-urlencoded":
                return self.reply(415, "Unsupported form")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 2048:
                    return self.reply(413, "Invalid form")
                params = parse_qs(self.rfile.read(length).decode("utf-8", "strict"), keep_blank_values=True)
                password = params.get("password", [""])[0]
                username = params.get("username", [""])[0]
            except (UnicodeError, ValueError, IndexError):
                return self.reply(400, "Invalid form")
            if (hmac.compare_digest(username, CONFIG["username"])
                    and hmac.compare_digest(password, CONFIG["password"])):
                return self.reply(303, b"", headers={
                    "Location": "/" if self.direct_access() else "/roomaudio/",
                    "Set-Cookie": self.issue_cookie(self.cookie_value())})
            time.sleep(0.45)
            return self.reply(403, "Неверный пароль. Вернитесь назад и повторите вход.")
        if path == "/logout":
            return self.reply(303, b"", headers={
                "Location": "/" if self.direct_access() else "/roomaudio/",
                "Set-Cookie": self.issue_cookie("", 0)})
        if not path.startswith("/ingest/"):
            return self.reply(404, "Not found")
        token = self.headers.get("X-Ingest-Key", "")
        if not hmac.compare_digest(token, CONFIG["ingest_key"]):
            return self.reply(403, "Forbidden")
        name = path.split("/")[-1]
        match = SEGMENT_RE.fullmatch(name)
        if not match:
            return self.reply(400, "Invalid filename")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.reply(400, "Invalid length")
        if length < 200 or length > 2_000_000:
            return self.reply(413, "Invalid audio size")
        if not ROOT.is_dir():
            return self.reply(503, "Archive disk unavailable")
        data = self.rfile.read(length)
        if len(data) != length:
            return self.reply(400, "Incomplete upload")
        if not (data.startswith(b"ID3") or (data[0] == 0xff and data[1] & 0xe0 == 0xe0)):
            return self.reply(415, "Expected MP3")
        digest = self.headers.get("X-SHA256")
        if digest and not hmac.compare_digest(digest.lower(), hashlib.sha256(data).hexdigest()):
            return self.reply(422, "Checksum mismatch")
        folder = ROOT / match.group(1)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        if target.exists():
            if target.stat().st_size == length:
                return self.reply(200, "Already received")
            return self.reply(409, "Filename collision")
        temp = folder / (name + "." + str(threading.get_ident()) + ".part")
        try:
            with temp.open("wb") as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            try:
                mean, peak = audio_quality.measure(temp)
            except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
                print("Audio quality check failed:", repr(exc), flush=True)
                return self.reply(503, "Audio verification unavailable")
            quiet = audio_quality.silent(mean, peak)
            if quiet:
                quiet_folder = audio_quality.ROOT / "incoming" / match.group(1)
                quiet_folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                q = quiet_folder / name
                if q.exists():
                    if q.stat().st_size != length:
                        return self.reply(409, "Silence quarantine collision")
                else:
                    os.replace(temp, q)
            else:
                os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        if not quiet and "X-Speech-Ranges" in self.headers:
            try:
                speech_index.save(name,self.headers.get("X-Speech-Ranges", ""))
            except (ValueError, OSError, sqlite3.Error) as exc:
                print("Speech marker indexing failed:",repr(exc),flush=True)
        with condition:
            state["last_source_seen"] = time.time()
            state["mic_silent"] = quiet
            state["mean_db"] = mean
            state["peak_db"] = peak
            if not quiet:
                state["last_received"] = state["last_source_seen"]
                state["last_name"] = name
            condition.notify_all()
        return self.reply(201, "Silent audio quarantined" if quiet else "Stored")

    def do_GET(self):
        path = urlsplit(self.path).path
        query = parse_qs(urlsplit(self.path).query)
        if path == "/client/recording-mode":
            if not hmac.compare_digest(self.headers.get("X-Ingest-Key", ""), CONFIG["ingest_key"]):
                return self.reply(403, "Invalid client key")
            active = query.get("active", ["starting"])[0]
            speech = query.get("speech", ["0"])[0] == "1"
            recording_settings.heartbeat(active,speech,query.get("recovery_ack",[""])[0])
            return self.json_reply(recording_settings.status())
        if path == "/" and not self.authorized():
            return self.login_page()
        if not (self.authorized() or self.valid_media_token(path, query.get("mt", [""])[0])):
            return self.reply(401, "Authentication required")
        if path == "/api/recording-mode":
            return self.json_reply(recording_settings.status())
        if path == "/api/live/status":
            return self.json_reply(live_relay.hub.status())
        if path == "/api/media-token":
            target = query.get("path", [""])[0]
            if not self.authorized() or not self.is_media_path(target):
                return self.reply(403, "Forbidden")
            return self.json_reply({"token": self.media_token(target), "expires_in": 7200})
        if path == "/":
            markup=(BASE / "index.html").read_bytes()
            if self.direct_access():
                markup=markup.replace(b'action="/roomaudio/logout"',b'action="/logout"')
            return self.reply(200,markup,"text/html; charset=utf-8")
        if path.startswith("/api/archive/cleanup/"):
            return archive_cleanup.api_get(self,path,query,ROOT)
        if path.startswith("/api/reports/audio/"):
            name = path.removeprefix("/api/reports/audio/")
            if not REPORT_AUDIO_RE.fullmatch(name):
                return self.reply(400, "Invalid audio report name")
            # Resolve mounted external SSD first, then WD; never follow escape symlinks.
            report_file = storage_paths.report_file(name)
            if report_file is None:
                return self.reply(404, "Report not found")
            return self.send_audio_sequence([report_file], name, disposition="attachment")
        if archive_api.archive_api(self, path, query, ROOT, BASE):
            return
        if path == "/api/status":
            last = state["last_received"]
            capture = recording_settings.status()
            audio_recent = bool(last and time.time() - last < 65)
            ingest_recent = bool(state["last_source_seen"] and
                                 time.time() - state["last_source_seen"] < 65)
            source_connected = bool(capture["client_connected"] or ingest_recent)
            return self.json_reply({"online": source_connected,
                "last_received": dt.datetime.fromtimestamp(last).isoformat(timespec="seconds") if last else None,
                "last_name": state["last_name"], "retention_days": CONFIG.get("retention_days", 30),
                "archive_available": ROOT.is_dir(),
                "source_online": source_connected,
                "audio_recent": audio_recent,
                "mic_silent": bool(state["mic_silent"] and state["last_source_seen"] and time.time()-state["last_source_seen"] < 65),
                "mean_db": state["mean_db"], "peak_db": state["peak_db"],
                "capture": capture,
                "archive_free_gb": round(shutil.disk_usage(ROOT).free / 1e9, 1) if ROOT.is_dir() else None,
                "asr_model_ready": (Path(CONFIG.get("transcription_model",
                    "/Volumes/WD/RoomAudio/models/ggml-large-v3-turbo.bin")).is_file()),
                "asr": asr_health()})
        if path == "/api/transcripts":
            date = query.get("date", [""])[0]
            term = query.get("q", [""])[0].strip()[:120].casefold()
            if date and not DAY_RE.fullmatch(date):
                return self.reply(400, "Invalid date")
            db = BASE / "transcripts.sqlite3"
            if not db.is_file():
                return self.json_reply({"items": [], "total": 0})
            try:
                with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)) as conn:
                    if date:
                        rows = conn.execute("SELECT group_id, day, started, ended, text, segments_json FROM transcripts WHERE day=? ORDER BY started DESC LIMIT 25000", (date,)).fetchall()
                    else:
                        rows = conn.execute("SELECT group_id, day, started, ended, text, segments_json FROM transcripts ORDER BY started DESC LIMIT 25000").fetchall()
                if term:
                    rows = [r for r in rows if term in r[4].casefold()]
                total = len(rows)
                items = [{"id":r[0], "day":r[1], "start":r[2], "end":r[3], "text":r[4],
                          "segments":json.loads(r[5])} for r in rows[:120]]
                return self.json_reply({"items": items, "total": total})
            except (sqlite3.Error, ValueError):
                return self.reply(503, "Transcript database unavailable")
        if path == "/api/days":
            days = sorted((p.name for p in ROOT.iterdir() if p.is_dir() and DAY_RE.fullmatch(p.name)), reverse=True)
            return self.json_reply({"days": days})
        if path == "/api/day":
            day = query.get("date", [""])[0]
            if not DAY_RE.fullmatch(day):
                return self.reply(400, "Bad date")
            hours = {}
            for p in segment_files(day):
                h = p.name[9:11]
                hours[h] = hours.get(h, 0) + 1
            return self.json_reply({"date": day, "hours": hours})
        if path == "/live.m3u8":
            files = fresh_live_segments(8)
            if not files:
                return self.reply(503, "No recent live audio. Waiting for speech.")
            lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:20",
                     "#EXT-X-MEDIA-SEQUENCE:" + str(int(dt.datetime.strptime(files[0].stem, "%Y%m%dT%H%M%S").timestamp() // 15))]
            for p in files:
                segment = "/segment/" + p.parent.name + "/" + p.name
                lines += ["#EXTINF:15.0,", "segment/" + p.parent.name + "/" + p.name
                          + "?mt=" + self.media_token(segment)]
            return self.reply(200, "\n".join(lines) + "\n", "application/vnd.apple.mpegurl")
        if path == "/live.mp3":
            return self.live_stream()
        if path.startswith("/clip/"):
            key = path.removeprefix("/clip/")
            if not re.fullmatch(r"\d{8}T\d{6}\.mp3", key):
                return self.reply(400, "Invalid clip")
            anchor = dt.datetime.strptime(key[:-4], "%Y%m%dT%H%M%S")
            files = [p for p in segment_files(key[:8]) if
                     dt.datetime.strptime(p.stem, "%Y%m%dT%H%M%S").replace(
                         minute=(int(p.stem[11:13])//2)*2, second=0) == anchor]
            if not files:
                return self.reply(404, "No audio")
            return self.send_audio_sequence(files)
        if path.startswith("/segment/"):
            parts = path.split("/")
            if len(parts) != 4 or not DAY_RE.fullmatch(parts[2]) or not SEGMENT_RE.fullmatch(parts[3]):
                return self.reply(400, "Bad segment")
            return self.send_audio_sequence([ROOT / parts[2] / parts[3]])
        if path.startswith("/archive/"):
            parts = path.split("/")
            if len(parts) != 4 or not DAY_RE.fullmatch(parts[2]) or not re.fullmatch(r"\d{2}\.mp3", parts[3]):
                return self.reply(400, "Bad archive")
            files = [p for p in segment_files(parts[2]) if p.name[9:11] == parts[3][:2]]
            if not files:
                return self.reply(404, "No recordings")
            return self.send_audio_sequence(files, parts[2] + "-" + parts[3])
        if path == "/setup/windows.zip":
            return self.send_file(BASE / "windows.zip", "application/zip")
        return self.reply(404, "Not found")

    def json_reply(self, obj):
        return self.reply(200, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def send_audio_sequence(self, files, filename=None, disposition="inline"):
        if not files or any(not p.is_file() for p in files):
            return self.reply(404, "No audio")
        sizes = [p.stat().st_size for p in files]
        total = sum(sizes)
        if not total:
            return self.reply(404, "Empty audio")
        start, end = 0, total-1
        requested = self.headers.get("Range", "")
        if requested:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            if not match or not any(match.groups()):
                return self.reply(416, "", headers={"Content-Range": f"bytes */{total}"})
            lo, hi = match.groups()
            if lo:
                start = int(lo)
                end = min(total-1, int(hi)) if hi else total-1
            else:
                start = max(0, total-int(hi))
            if start > end or start >= total:
                return self.reply(416, "", headers={"Content-Range": f"bytes */{total}"})
        self.send_response(206 if requested else 200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end-start+1))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        if requested:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        if filename:
            self.send_header("Content-Disposition", disposition + '; filename="' + filename + '"')
        self.end_headers()
        offset = 0
        try:
            for f, size in zip(files, sizes):
                lo, hi = offset, offset+size-1
                offset += size
                if hi < start or lo > end: continue
                local_start = max(0, start-lo)
                remaining = min(size-1,end-lo)-local_start+1
                with f.open("rb") as stream:
                    stream.seek(local_start)
                    while remaining:
                        data = stream.read(min(65536,remaining))
                        if not data: break
                        self.wfile.write(data)
                        remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass

    def send_file(self, path, content_type):
        if not path.is_file():
            return self.reply(404, "Not found")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            with path.open("rb") as stream:
                shutil.copyfileobj(stream, self.wfile)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def live_stream(self):
        current = live_relay.hub.subscribe()
        if current is None:
            return self.reply(503, "Continuous live audio is not connected")
        generation, seq = current
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Cache-Control", "no-store, no-transform")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            while True:
                result = live_relay.hub.read(generation, seq)
                if result is None:
                    return
                frames, seq = result
                for _, data in frames:
                    self.wfile.write(data)
                if frames:
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            live_relay.hub.unsubscribe()

if __name__ == "__main__":
    threading.Thread(target=maintenance, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    print(f"RoomAudio listening on port {PORT}; archive {ROOT}", flush=True)
    server.serve_forever()
