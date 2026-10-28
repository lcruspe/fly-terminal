from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, HttpUrl
from yt_dlp import YoutubeDL

app = FastAPI(title="YT Transcript Local", version="1.0")

ALLOWED_ORIGINS = [
    "https://chatgpt-mei4syop.webondemand.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Transcribe-Token"],
)

TOKEN = os.environ.get("TRANSCRIBE_TOKEN", "")
SESSION_SECRET = os.environ.get("YT_SESSION_SECRET", "")
BOOTSTRAP_SECRET = os.environ.get("YT_BOOTSTRAP_SECRET", "")
SESSION_COOKIE = "yt_session"
SESSION_TTL = 90 * 24 * 60 * 60
MODELS: dict[str, Any] = {}
logger = logging.getLogger("yt-transcriber")


class TranscribeRequest(BaseModel):
    url: HttpUrl
    language: str = "auto"
    model: str = "small"


def require_token(x_transcribe_token: str | None) -> None:
    if TOKEN and x_transcribe_token != TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


def youtube_host_ok(url: str) -> bool:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    return host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}


def pick_caption_track(info: dict, requested: str):
    sources = [
        ("subtitles", info.get("subtitles") or {}),
        ("automatic_captions", info.get("automatic_captions") or {}),
    ]
    available: list[tuple[str, str, list[dict]]] = []
    for source_name, tracks in sources:
        for code, fmts in tracks.items():
            if code == "live_chat" or not fmts:
                continue
            available.append((source_name, code, fmts))

    if not available:
        return None

    req = (requested or "auto").lower()
    preferred_codes: list[str] = []
    if req != "auto":
        preferred_codes.append(req)
    else:
        detected = (info.get("language") or "").lower()
        if detected:
            preferred_codes.append(detected)
        preferred_codes.extend(["ru", "en"])

    def score(item):
        source_name, code, fmts = item
        c = code.lower()
        score_value = 0
        if source_name == "subtitles":
            score_value += 100
        for idx, pref in enumerate(preferred_codes):
            if c == pref:
                score_value += 1000 - idx * 20
            elif c.startswith(pref + "-"):
                score_value += 900 - idx * 20
        if c.endswith("-orig"):
            score_value += 5
        return score_value

    chosen = max(available, key=score)
    source_name, code, fmts = chosen
    json3 = next((f for f in fmts if f.get("ext") == "json3"), None)
    return source_name, code, (json3 or fmts[0])


def fetch_caption_json3(fmt: dict) -> list[dict] | None:
    if fmt.get("ext") != "json3" or not fmt.get("url"):
        return None
    headers = {"User-Agent": "Mozilla/5.0"}
    headers.update(fmt.get("http_headers") or {})
    req = urllib.request.Request(fmt["url"], headers=headers)
    data = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in {403, 429}:
                raise
            logger.warning("YouTube captions HTTP %s; attempt %s/2", exc.code, attempt + 1)
            if attempt == 0:
                time.sleep(1.5)
        except urllib.error.URLError as exc:
            logger.warning("YouTube captions unavailable: %s", exc)
            break
    if data is None:
        return None

    out: list[dict] = []
    for event in data.get("events", []):
        segs = event.get("segs") or []
        text = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
        if not text:
            continue
        start = (event.get("tStartMs") or 0) / 1000
        dur = (event.get("dDurationMs") or 0) / 1000
        out.append({"start": start, "end": start + dur, "text": text})
    return out or None


def extract_info(url: str) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "retries": 5,
        "extractor_retries": 3,
    }
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def transcribe_with_whisper(url: str, info: dict, requested_language: str, model_name: str, report=None) -> dict:
    from faster_whisper import WhisperModel
    report = report or (lambda *args: None)

    if model_name not in {"base", "small", "medium"}:
        model_name = "small"

    if model_name not in MODELS:
        report("Загрузка модели Whisper")
        MODELS[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8")
    model = MODELS[model_name]

    with tempfile.TemporaryDirectory(prefix="yt-transcribe-") as td:
        outtmpl = str(Path(td) / "audio.%(ext)s")
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "retries": 5,
            "fragment_retries": 5,
            "extractor_retries": 3,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "64",
            }],
        }
        def download_progress(d):
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                report("Загрузка аудио", min(100, 100 * d.get("downloaded_bytes", 0) / total) if total else None)
            elif d.get("status") == "finished":
                report("Подготовка аудио")
        opts["progress_hooks"] = [download_progress]
        report("Загрузка аудио")
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
        audio = Path(td) / "audio.mp3"
        if not audio.exists():
            candidates = list(Path(td).glob("audio.*"))
            if not candidates:
                raise RuntimeError("Не удалось получить аудиодорожку")
            audio = candidates[0]

        language = None if requested_language == "auto" else requested_language
        report("Распознавание речи")
        seg_iter, meta = model.transcribe(
            str(audio),
            language=language,
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=True,
        )
        segments = []
        last_update = 0
        duration = info.get("duration") or getattr(meta, "duration", None)
        for segment in seg_iter:
            if segment.text.strip():
                segments.append({"start": float(segment.start), "end": float(segment.end), "text": segment.text.strip()})
            if time.monotonic() - last_update >= 2:
                report("Распознавание речи", min(99, segment.end / duration * 100) if duration else None)
                last_update = time.monotonic()

    return {
        "title": info.get("title") or "Транскрипт",
        "source": "whisper",
        "language": getattr(meta, "language", None) or requested_language,
        "duration": info.get("duration"),
        "segments": segments,
        "text": " ".join(s["text"] for s in segments),
    }



def _make_session(user: str) -> str:
    expires = int(time.time()) + SESSION_TTL
    payload = f"{user}:{expires}".encode()
    signature = hmac.new(SESSION_SECRET.encode(), payload, hashlib.sha256).hexdigest().encode()
    return base64.urlsafe_b64encode(payload + b"." + signature).decode()

def _session_valid(request: Request) -> bool:
    if not SESSION_SECRET:
        return False
    raw = request.cookies.get(SESSION_COOKIE, "")
    try:
        decoded = base64.urlsafe_b64decode(raw.encode())
        payload, signature = decoded.rsplit(b".", 1)
        expected = hmac.new(SESSION_SECRET.encode(), payload, hashlib.sha256).hexdigest().encode()
        if not hmac.compare_digest(signature, expected):
            return False
        _, expires = payload.decode().rsplit(":", 1)
        return int(expires) > int(time.time())
    except Exception:
        return False

def _require_session(request: Request) -> None:
    if not _session_valid(request):
        raise HTTPException(status_code=401, detail="Session required")

@app.get("/session/bootstrap", include_in_schema=False)
def session_bootstrap(
    x_authenticated_user: str | None = Header(default=None),
    x_yt_bootstrap_secret: str | None = Header(default=None),
):
    if (not x_authenticated_user or not SESSION_SECRET or not BOOTSTRAP_SECRET
            or not hmac.compare_digest(x_yt_bootstrap_secret or "", BOOTSTRAP_SECRET)):
        raise HTTPException(status_code=401, detail="Authentication required")
    response = RedirectResponse(url="/yt-transcriber/", status_code=302)
    response.set_cookie(
        SESSION_COOKIE, _make_session(x_authenticated_user), max_age=SESSION_TTL,
        path="/yt-transcriber", secure=True, httponly=True, samesite="lax",
    )
    return response

@app.get("/", include_in_schema=False)
def web_ui(request: Request):
    if not _session_valid(request):
        return RedirectResponse(url="/yt-login", status_code=302)
    return FileResponse(Path(__file__).with_name("web.html"), media_type="text/html")

@app.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon():
    return FileResponse(Path(__file__).with_name("apple-touch-icon.png"), media_type="image/png", headers={"Cache-Control": "public, max-age=300"})

@app.get("/health")
def health():
    return {"ok": True, "service": "yt-transcript-local"}


@app.post("/api/transcribe")
def transcribe(payload: TranscribeRequest, x_transcribe_token: str | None = Header(default=None)):
    require_token(x_transcribe_token)
    url = str(payload.url)
    if not youtube_host_ok(url):
        raise HTTPException(status_code=400, detail="Поддерживаются только ссылки YouTube")

    try:
        info = extract_info(url)
        selected = pick_caption_track(info, payload.language)
        if selected:
            source_name, code, fmt = selected
            segments = fetch_caption_json3(fmt)
            if segments:
                return {
                    "title": info.get("title") or "Транскрипт",
                    "source": "captions",
                    "captionType": source_name,
                    "language": code,
                    "duration": info.get("duration"),
                    "segments": segments,
                    "text": " ".join(s["text"] for s in segments),
                }
        return transcribe_with_whisper(url, info, payload.language, payload.model)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@app.post("/api/ui/transcribe")
def ui_transcribe(payload: TranscribeRequest, request: Request):
    _require_session(request)
    return transcribe(payload, TOKEN)

# ChatGPT tool bridge endpoints
TOOL_CACHE_DIR = Path(__file__).parent / "tool_cache"
TOOL_CACHE_DIR.mkdir(exist_ok=True)
TOOL_CHUNK_SIZE = 24000

def _tool_id(url: str) -> str:
    import hashlib
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]

def _timestamp(sec: float) -> str:
    total = max(0, int(sec or 0))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def _timestamped_text(result: dict) -> str:
    segments = result.get("segments") or []
    if not segments:
        return result.get("text") or ""
    return "\n".join(
        f"[{_timestamp(seg.get('start', 0))}] {seg.get('text', '').strip()}"
        for seg in segments if seg.get("text", "").strip()
    )

@app.post("/api/tool/transcribe")
def tool_transcribe(payload: TranscribeRequest, x_transcribe_token: str | None = Header(default=None)):
    require_token(x_transcribe_token)
    result = transcribe(payload, x_transcribe_token)
    url = str(payload.url)
    transcript_id = _tool_id(url)
    formatted = _timestamped_text(result)
    chunks = [formatted[i:i + TOOL_CHUNK_SIZE] for i in range(0, len(formatted), TOOL_CHUNK_SIZE)] or [""]
    cache = {
        "id": transcript_id,
        "url": url,
        "title": result.get("title"),
        "source": result.get("source"),
        "language": result.get("language"),
        "duration": result.get("duration"),
        "chunks": chunks,
        "plain_text": result.get("text") or "",
    }
    (TOOL_CACHE_DIR / f"{transcript_id}.json").write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return {
        "transcript_id": transcript_id,
        "title": cache["title"],
        "source": cache["source"],
        "language": cache["language"],
        "duration": cache["duration"],
        "chunk": 0,
        "chunk_count": len(chunks),
        "complete": len(chunks) == 1,
        "transcript": chunks[0],
    }

@app.get("/api/tool/transcript/{transcript_id}")
def tool_transcript_chunk(transcript_id: str, chunk: int = 0, x_transcribe_token: str | None = Header(default=None)):
    require_token(x_transcribe_token)
    if not transcript_id.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid transcript id")
    path = TOOL_CACHE_DIR / f"{transcript_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Transcript not found")
    cache = json.loads(path.read_text(encoding="utf-8"))
    chunks = cache.get("chunks") or []
    if chunk < 0 or chunk >= len(chunks):
        raise HTTPException(status_code=400, detail=f"Chunk must be 0..{max(0, len(chunks)-1)}")
    return {
        "transcript_id": transcript_id,
        "title": cache.get("title"),
        "chunk": chunk,
        "chunk_count": len(chunks),
        "complete": chunk == len(chunks) - 1,
        "transcript": chunks[chunk],
    }

@app.get("/api/tool/status")
def tool_status(x_transcribe_token: str | None = Header(default=None)):
    require_token(x_transcribe_token)
    return {"ok": True, "tool": "youtube-transcriber", "cache_dir": str(TOOL_CACHE_DIR)}



from jobs import install as install_jobs
install_jobs(app, _require_session, TranscribeRequest, youtube_host_ok)