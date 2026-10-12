# RoomAudio — Windows capture and Mac server

RoomAudio is a separate service linked from the Fly Terminal gateway. This directory tracks its Windows-side scripts in source control; local credentials and recordings are never committed.

## Deployment map

- Mate: `%LOCALAPPDATA%\RoomAudio` contains `client.json`, capture supervisor, voice-activity detector, buffer and uploader. `D:\Conda\python.exe` runs capture and upload. `D:\Installed\AudioMonitor` provides the microphone/RTSP stack and FFmpeg.
- Mac mini: `~/Library/Application Support/RoomAudio/server.py` and `config.json`, port `8766`, archive on WD. This server is **not** included here yet.
- Fly Terminal Caddy proxies `/roomaudio/` to the Mac RoomAudio server. Caddy routing does not change capture or streaming behavior.

## Current Windows archive transport (2026-10-12)

`capture_manager.py` polls the server every 3 seconds for `off`, `continuous`, or `voice`. Only one microphone capture process should exist at a time.

- `continuous`: WDM-KS microphone → `capture_ks.py` → FFmpeg → 15-second MP3 segments.
- `voice`: WDM-KS microphone → `capture_voice.py` → WebRTC VAD → discard a 15-second segment if no speech; otherwise store the *full* 15-second MP3 segment and speech windows marker.
- `off`: stop capture process; microphone must be closed.
- `uploader.py`: transfers completed MP3 to `POST /ingest/<filename>` with `X-Ingest-Key`, SHA256 digest and optional `X-Speech-Ranges`. The server acknowledges with HTTP 200/201. Files and markers are removed locally **only after** a successful acknowledgement and unchanged size/mtime check.

Uploader uses atomic capture-side rename from `.pending`, at least 2 seconds file-age guard, and a 1-second polling loop. Earlier settings were 45 seconds and 5 seconds, causing about a minute of artificial delivery delay. Failures retain data and retry. These changes have been applied on Mate on 2026-10-12.

## Outstanding live-audio separation

**This is still an archive-upload architecture, not real-time streaming.** The web player on the Mac can encounter gaps whenever VAD rejects segments; a smaller upload delay cannot fix this.

Required server/client refactor when the Mac server source can be accessed:

1. Fan out frames from the **single** microphone capture stream to independent live transport and archival segmenter. Do not open a second WDM-KS microphone stream.
2. Use bounded memory, low-latency encoding, backpressure/drop-oldest for live only, authentication, reconnect with exponential backoff, and explicit connection status. Never let a stalled live socket block or lose archival capture.
3. Keep live transport running in both `continuous` and `voice`. In `voice`, VAD controls only the archive and its speech metadata; `off` stops both.
4. Server delivers an actual continuous stream to authenticated listeners and makes browser reconnect/resume playback, without depending on the 15-second archive index or uploader.
5. Add tests for VAD silence, spoken segments, archive continuity, stream reconnect, client queue saturation, server disconnect, and `off` state.
6. Deploy the Mac service with its launchd unit after verifying its existing authentication/session and archive APIs. Do not replace unknown server code without reviewing it.

## Windows validation

```powershell
& D:\Conda\python.exe -m py_compile capture_ks.py capture_voice.py capture_manager.py speech_activity.py uploader.py
Get-Content "$env:LOCALAPPDATA\RoomAudio\uploader.log" -Tail 20
```

`client.json`, speech archives, logs and captured audio must never be placed in version control.