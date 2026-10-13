# RoomAudio — Windows capture and Mac server

RoomAudio is a separate service linked from the Fly Terminal gateway. This directory tracks the Windows capture pipeline and Mac server scripts in source control. Local credentials and recordings are never committed.

## Deployment map

- Mate: `%LOCALAPPDATA%\RoomAudio` contains `client.json`, capture supervisor, voice-activity detector, buffer and uploader. `D:\Conda\python.exe` runs capture and upload. `D:\Installed\AudioMonitor` provides the microphone/RTSP stack and FFmpeg.
- Mac mini: `~/Library/Application Support/RoomAudio/server.py` and `config.json`, port `8766`, archive on WD. The Python sources are mirrored in `roomaudio/macos/`; the active launchd service loads the deployed copies from the Application Support directory.
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

Required future live-stream refactor (Mac server source is now tracked):

1. Fan out frames from the **single** microphone capture stream to independent live transport and archival segmenter. Do not open a second WDM-KS microphone stream.
2. Use bounded memory, low-latency encoding, backpressure/drop-oldest for live only, authentication, reconnect with exponential backoff, and explicit connection status. Never let a stalled live socket block or lose archival capture.
3. Keep live transport running in both `continuous` and `voice`. In `voice`, VAD controls only the archive and its speech metadata; `off` stops both.
4. Server delivers an actual continuous stream to authenticated listeners and makes browser reconnect/resume playback, without depending on the 15-second archive index or uploader.
5. Add tests for VAD silence, spoken segments, archive continuity, stream reconnect, client queue saturation, server disconnect, and `off` state.
6. Keep launchd service deployment synchronized with the tracked `roomaudio/macos/` sources and verify authentication/session and archive API behavior before each restart.

## Windows validation

```powershell
& D:\Conda\python.exe -m py_compile capture_ks.py capture_voice.py capture_manager.py speech_activity.py uploader.py
Get-Content "$env:LOCALAPPDATA\RoomAudio\uploader.log" -Tail 20
```

`client.json`, speech archives, logs and captured audio must never be placed in version control.

## Important-conversation audio attachments (2026-10-12)

The recurring RoomAudio analysis task sends only semantically significant conversations. Each selected conversation must have **one downloadable MP3, one transcript and one analytical summary**. The source is the original archive audio, not speech regenerated from ASR text.

- Deployed exporter: `~/Library/Application Support/RoomAudio/export_conversation.py` (tracked as `roomaudio/macos/export_conversation.py`).
- Private output directory exposed to users: `~/Documents/RoomAudio-reports/audio/` (`0700` directory, `0600` MP3); on the Mac mini this is a directory symlink to the **actual** private storage `~/Library/Application Support/RoomAudio/reports/audio/` (also `0700`). The exporter and authenticated endpoint keep the same documented path/URL and resolve the same private directory; the original archive is unchanged.
- Filename: `RoomAudio_YYYY-MM-DD_HHMM-HHMM_<ascii_slug>.mp3`.
- Authenticated URL: `https://129-158-49-130.sslip.io/roomaudio/api/reports/audio/<filename>`. The Mac server checks its existing RoomAudio session or credentials *before* serving; report files do not accept URL media tokens.
- Endpoint validates exact filename pattern, prevents symlink-based traversal, returns `audio/mpeg` with `Content-Disposition: attachment` and supports `Range` requests for resumable mobile downloads.
- Inaccessible source intervals remain silence, with gaps and coverage included in export metadata. Overlaps are placed on the original timeline instead of being blindly concatenated.

Example, run on the Mac mini (use quotes around the Application Support path):

```bash
python3 "$HOME/Library/Application Support/RoomAudio/export_conversation.py"   --start 2026-10-12T12:30:00 --end 2026-10-12T12:41:00   --slug razvod_zhile
```

The exporter prints a machine-readable JSON object with the saved path, `url_path`, source count, measured source coverage and silence duration. Analysis reports should use `url_path` with the configured HTTPS gateway address to link to the exact file. Never store MP3s, transcripts with personal content, `config.json`, login cookies, or private archives in Git.

Deployment: update changed Python sources from the repository into the Mac Application Support service directory (preserve local `config.json`), compile with `python3 -m py_compile`, restart the user launchd agent `com.kruspe.roomaudio`, and verify (a) an unauthorized GET returns HTTP 401, (b) authorized 0–127 byte `Range` returns HTTP 206 with attachment filename, (c) unexpected file names and traversal are rejected. Avoid restarting the unrelated ASR agent.

The recurring task schedule uses Europe/Moscow: 00:00, 09:00 (entire night), 13:00, 17:00 and 21:00. The task should only send important conversations and must clearly report inability to access or attach audio.

### macOS Documents file-provider issue (2026-10-13)

The macOS `~/Documents` directory is managed by a file provider and can evict report MP3 contents, making them `compressed,dataless`. A name can then pass `stat()` and produce an HTTP 401 for unauthenticated requests, but an authorized download/read may fail with macOS `Resource deadlock avoided`. **A 401 alone is not proof that the MP3 payload can be read.**

To keep the user-facing path and gateway URL stable without letting File Provider evict the payload, the entire `~/Documents/RoomAudio-reports/audio` directory was replaced with a symlink to the non-synced app-owned `~/Library/Application Support/RoomAudio/reports/audio`. All six pre-existing MP3 reports were regenerated from the untouched source archive into that real directory and validated through the symlink using `ffprobe`. The former iCloud-managed folder is retained under `~/Documents/RoomAudio-reports/audio.icloud-backup-20261013T132643` for recovery (do not accidentally serve it).

When diagnosing a missing download, verify `report_path.resolve().parent == REPORT_AUDIO_DIR.resolve()`, `ffprobe` playback of the exact path, file mode `0600`, HTTP 401 when unauthenticated, and an authorized range GET with HTTP 206 if available. New exports written through the symlink remain outside iCloud-managed Documents. Transient ASR scratch WAVs should use OS temporary directories, **not `~/Documents`**, which may produce `Resource deadlock avoided` during automated reads. Avoid filling the system volume: on 2026-10-13 its free space was only about 1.8 GiB.
