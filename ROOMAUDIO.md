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

## Seamless live broadcast (2026-10-13)

**Fixed the 15-second splice problem without touching archival semantics.**

- The old `/live.mp3` concatenated independent archive segments on each 15-second boundary and the old HLS playlist referenced the same fragments. VAD could discard a segment entirely, so neither path was genuinely continuous. These archive endpoints remain useful only as fallback and for playback of historic records.
- One WDM-KS microphone capture process still owns the microphone in both `continuous` and `voice` modes. Both `capture_ks.py` and `capture_voice.py` feed their already-produced 48kHz mono float PCM to `LivePublisher` using a **bounded non-blocking queue**. Archive writers continue to use their existing 15-second segment pipeline.
- `roomaudio/windows/live_publisher.py` owns **one continuously running 96 kbps MP3 encoder** and publishes consecutive encoded byte ranges to `POST /ingest/live` every ~0.7s. Unlike the initial long-running chunked-HTTP attempt (which caused Windows WinError 10053/10054), the network uses short, acknowledged HTTP requests with source session ID, strictly monotonic packet sequence and existing `X-Ingest-Key`. On connection failure the encoder and session are restarted; stale queued PCM is discarded.
- `roomaudio/macos/live_relay.py` accepts authenticated, length-checked packets and holds a bounded in-memory ring buffer. It rejects missing/out-of-order packets and replaces the decoder generation on new source sessions. Multiple listeners subscribe to `/live.mp3`; lagging listeners cannot accumulate an unbounded backlog. Audio is streamed directly as a single MP3 bitstream, not separate MP3 files. No extra recording or report files are stored.
- The frontend `roomaudio/macos/index.html` defaults to **«Бесшовный эфир»**, uses `/api/live/status` and automatic reconnect on an interrupted stream. `HLS (резервный архивный)` remains available for clients that cannot decode a live MP3 HTTP response; **this HLS fallback still has 15-second archive boundaries and may stutter**. Do not describe fallback as seamless.
- Capture `off` mode terminates the microphone and the live encoder; the server automatically considers a source stale after 8 seconds without bytes. No secondary microphone stream is opened. Session/auth and report export URLs are unaffected.

### Verification

1. Windows: `D:\Conda\python.exe -m py_compile capture_ks.py capture_voice.py live_publisher.py`.
2. Mac: `python3 -m py_compile server.py live_relay.py`. Unit tests: reject oversized HTTP packet, nonsequential packet, expired source, new session resetting current listeners; verify ring bound and byte-exact concatenation.
3. Restart Mac `com.kruspe.roomaudio` (leave independent ASR running); restart only the current Windows capture child so its manager relaunches it using new code. Confirm Mac sees an established LAN TCP connection from Mate, that archive files continue arriving, and the former long-lived HTTP error does not recur.
4. In an authenticated RoomAudio browser, select **«Бесшовный эфир»**, verify `/api/live/status` reports online, `/live.mp3` plays normally, and listen continuously for several minutes across multiple former 15s boundaries. Toggle `continuous`↔`voice` and make sure recording archive/voice filtering still functions.
5. Stop/restore the live sender or disconnect/reconnect LAN: the UI must reconnect without replaying stale source data. Confirm unauthenticated `/live.mp3` and `/api/live/status` return HTTP 401.
6. Be explicit about remaining uncertainty: a successful TCP source connection and codec/relay unit tests **do not by themselves prove** uninterrupted playback on every browser. iOS Safari may require a future genuinely segmentable low-latency HLS rendition produced from this same continuous source (NOT the archive fragments).

## Original live-audio separation plan (superseded by streaming encoder)

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
- Private compatibility path: `~/Documents/RoomAudio-reports/audio/`. It is a symlink to the app-owned link, which points to external SSD storage. The authenticated API also searches WD directly if the SSD is absent.
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

### External SSD-first working storage (2026-10-13)

For all **report MP3, export and ASR scratch files**, use `roomaudio/macos/storage_paths.py`. This selector never writes to a shadow mountpoint in `/Volumes`.

1. **Preferred:** writable external APFS data volume `/Volumes/MacSSD — данные` (the space before the dash is **U+00A0**). `/Volumes/MacSSD` is read-only and MUST NOT be used.
2. **Fallback:** `/Volumes/WD`, only if the preferred SSD data volume is absent or unwritable.
3. If neither external volume is actually mounted and writable: fail explicitly, never default to the Mac system disk.
4. MP3 reports: `<mount>/RoomAudio-work/reports/audio/`; transient ffmpeg and Whisper processing: `<mount>/RoomAudio-work/tmp/`.
5. Exported MP3 reports are **atomically mirrored to WD** when WD is mounted, keeping secure URLs available without SSD. The authenticated server resolves the requested report dynamically against mounted SSD first, then WD, validates its real parent directory, and keeps existing authorization/Range handling.
6. Historical `~/Documents/RoomAudio-reports/audio/` → app-owned `reports/audio` → external SSD report directory compatibility symlinks are retained. The links may be temporarily inaccessible while the SSD is detached, but the HTTP API independently searches WD and remains functional.
7. Original recorder archive and Whisper model files remain on WD: moving them requires a separate archive-ingest migration. Small application sources/configuration, status and existing SQLite metadata remain in Application Support. **Large intermediate and report files** no longer use the internal disk.

Deploy the tracked `storage_paths.py`, `server.py`, `export_conversation.py` and `transcriber.py` together to Mac Application Support, then restart launchd `com.kruspe.roomaudio` and `com.kruspe.roomaudio.asr`. Do not sync login credentials or original recordings to Git.

Validated 2026-10-13: both mounted external volumes writable; six historic MP3 reports copied to both external disks, matching SHA-256 and ffprobe duration. Re-export created the MP3 under MacSSD with `mirrored_on_wd: true`, matching digest on WD. Simulated SSD removal selected WD for workdirs and existing MP3s, while simulated removal of both disks failed safely. Restarted services and confirmed unauthenticated HTTPS access remains HTTP 401. Always verify authenticated HTTP Range (206) with an actual authorized session before declaring end-to-end download verified.

Old application-folder report backups (`reports/audio.pre-ssd-20261013`) and iCloud-managed Documents backups are not served. System `/tmp` should not be used for future independent transcript processing; use the external temporary workdir.

### Live-stream end-to-end validation (2026-10-13)

- Windows Mate capture in `voice` mode continued generating archival MP3s after the live publisher was attached; no second microphone was opened.
- The original long-lived chunked HTTP uplink was discarded after repeated Windows `WinError 10053/10054`. Replaced by consecutive, short, acknowledged HTTP requests carrying one persistent MP3 encoder output. Live ingest requires `X-Ingest-Key`, a 32-hex source session, monotonically increasing packet sequence and length <= 65536 bytes.
- On Mac mini `test_live_relay.py` passed 5/5 tests. Protected route returned HTTP 401 to unauthenticated requests. With an authorized session, HTTPS `/roomaudio/api/live/status` returned `online: true` and a bounded buffer of 262144 bytes.
- Authenticated local `/live.mp3` returned HTTP 200 and a 100000-byte sample decoded as MP3, 8.329667 s. Public HTTPS gateway `/roomaudio/live.mp3` also returned HTTP 200 and live audio.
- A 33-second real external HTTPS capture returned 396000 MP3 bytes in 33 reads. FFmpeg decoder returned code 0 and FFprobe reported 32.983 seconds. The longest wait between reads was 1.56 seconds. This verifies continuity through multiple former 15-second segment boundaries at the byte/decoder level. Subjective listening and iPhone Safari validation remain user-side checks.
- After the final Mac server restart, relay unit tests passed 5/5 again and the authorized HTTPS status still reported `online: true`. Archive ASR worker was left running.

## Mate source-offline incident and recovery (2026-10-21)

**Symptoms:** RoomAudio UI reported `Источник не отвечает`. Mac mini server (`com.kruspe.roomaudio`) and transcriber (`com.kruspe.roomaudio.asr`) were alive, but no source MP3 had been received since 2026-10-15 03:20 MSK. On Mate both the capture supervisor and uploader had stopped. The previous AudioMonitor startup shortcut was disabled.

**Causes and permanent corrective changes:**

- The Mac mini's LAN address changed from `192.168.1.173` to `192.168.1.201`. The private **untracked** Mate `%LOCALAPPDATA%\RoomAudio\client.json` still contained the old hard-coded `server` endpoint. It was changed to **`http://Kruspe-Mac-mini.local:8766`**, which resolves on Mate, so future DHCP changes do not require manual repair. Do not commit the real client.json: it contains an ingest key. The Mac server also recognizes the stable lowercase `kruspe-mac-mini.local:8766` as an approved direct-login host and same-origin endpoint.
- Windows has `HTTP_PROXY` and `HTTPS_PROXY` configured; Python `urlopen` incorrectly routed local `.local` HTTP requests through this proxy, yielding HTTP 503. Both `roomaudio/windows/capture_manager.py` and `roomaudio/windows/uploader.py` now use a dedicated `build_opener(ProxyHandler({}))` so **RoomAudio only** connects directly to the LAN; global Windows proxy settings are untouched. The continuous live publisher already uses `http.client` directly.
- The UI formerly treated the lack of any newly uploaded MP3 within 65 seconds as the **source disconnecting**. This is false while capture mode is `voice` and VAD deliberately discards segments with no detected speech. `roomaudio/macos/server.py` now exposes `source_online` based on recent capture-client heartbeat OR recent ingest, plus a separate `audio_recent` flag. `index.html` distinguishes **`Ожидание речи`**, a stopped capture mode, an actual lost source, and a dead-silent microphone.
- On Mate the existing `Toggle-RoomAudio.ps1 -Action Start` started all three managers: `D:\Installed\AudioMonitor\autostart.py` (watchdog), `capture_manager.py` and `uploader.py`. The previous `voice` mode was preserved.
- To avoid another extended outage after logon or a silent process crash, a separate **idempotent** `roomaudio/windows/Ensure-RoomAudio.ps1` was deployed. It checks the existing user-session processes and starts **only missing** AudioMonitor/watchdog, capture manager, or uploader processes; it does not restart active capture processes or force the microphone mode. The Windows Task Scheduler task **`RoomAudio Auto Recovery`** runs the script at user logon and every **5 minutes**, with `MultipleInstances=IgnoreNew`. It uses the current user (interactive, least privilege) and a hidden PowerShell window. Do not reenlist the legacy disabled AudioMonitor shortcut in addition to this task: that could create duplicate watchdogs.

**Verifications on 2026-10-21 (~10:01 MSK):** Mate resolved `Kruspe-Mac-mini.local` to `192.168.1.201` and TCP/8766 succeeded; after proxy bypass, Mac reported `client_connected=true`, `active_mode=voice`, `source_online=true`. Mate produced and uploaded new MP3s (server HTTP 201). Mac's `/Volumes/WD/RoomAudio/archive/20261021` contained **15 new files**, the last at 10:00:42; the transcription database had processed the group beginning 09:58:12 and ASR was actively processing with 1 item in queue. Authenticated live endpoint reported `online=true`. The task was registered with logon and 5-minute triggers. If inspecting the task immediately after manual start, result `267009` means *running*, not failure; check its final result after completion.

**Operational check:** On Mate run `& "$env:LOCALAPPDATA\RoomAudio\Toggle-RoomAudio.ps1" -Action Status`; review `capture-manager.log`, `uploader.log`, `capture-managed-output.log`, and the scheduled task. On Mac inspect `/api/status` with an authorized session and review `capture.client_connected`, `capture.active_mode`, `source_online`, `audio_recent`, and `asr`. In voice mode, `audio_recent=false` is expected when there is no speech; check capture heartbeat, *not* just new archive filenames. If the source cannot connect, verify Windows mDNS resolves `Kruspe-Mac-mini.local`, port 8766 is reachable, direct URL requests bypass `HTTP_PROXY`, and the Mac IP has not changed again. Preserve `voice` vs `continuous` user setting and never put local ingest credentials into logs, ChatGPT, or Git.


## Manual live pipeline recovery (2026-10-23)

The Live tab has **«Восстановить тракт»**. Authenticated, origin-checked `POST /api/recovery` queues a persistent restart ID without changing `voice` / `continuous` / `off`. Repeated requests within 15 seconds reuse the ID. The relay discards stale buffered audio and disconnects old readers. The Windows capture manager receives the ID through its existing ingest-key-protected polling endpoint, stops the capture process tree (including the live encoder), starts the selected mode, and acknowledges the ID on its next heartbeat. The UI reports success only after a fresh acknowledgement and an online live source; in `off` mode it confirms recovery while leaving the microphone off. If playback was requested, it reconnects the player after recovery. After 60 seconds without confirmation the UI reports that recovery is unconfirmed; the saved command remains pending for the next client connection. This command requires the manager to reconnect; it cannot power on an offline Mate. The existing five-minute Windows auto-recovery task still starts missing managers.

On 2026-10-23 the managers were running, but Windows failed to resolve `Kruspe-Mac-mini.local` (`getaddrinfo failed`), so fail-closed capture stopped and both archive and live uploads lost their route. The shared Windows `client_transport.py` bypasses system proxies and tries the primary `server` plus optional `server_fallbacks` from private `client.json` on network failures. It remembers the reachable endpoint in each process; HTTP authentication/protocol errors do not cause fallback replay. Configure only addresses of the same RoomAudio server. Mate now has the reachable Mac LAN endpoint as a fallback. LAN IPs can change with DHCP; update configured addresses when the network changes. No credentials or actual client config are committed.

Deploy `client_transport.py`, `capture_manager.py`, `live_publisher.py` and `uploader.py` together on Mate, then restart only RoomAudio manager/uploader processes and run the existing `Ensure-RoomAudio.ps1`. Deploy Mac `server.py`, `recording_settings.py`, `live_relay.py`, `index.html`, preserving local config, and restart only `com.kruspe.roomaudio`. ASR stays independent. Rejected control POSTs close their connection so unread request bodies cannot corrupt the next request in Caddy's connection pool.

## Cross-network Mate recovery (2026-10-27)

**Incident:** Mate was connected to Wi-Fi `192.168.3.225/24`, while Mac mini was on `192.168.1.201/24`. The capture manager, uploader and scheduled `RoomAudio Auto Recovery` task were running, but both configured `.local` and LAN-IP URLs timed out. Thus the UI restart command was persisted on Mac but never polled by Mate; restarting the Windows processes alone could not fix routing.

**Permanent fix:** The Mac Caddy gateway permits the already implemented `/roomaudio/client/recording-mode` GET and `/roomaudio/ingest/*` POST over the **Oracle HTTPS reverse relay**, while retaining a 404 block for `/roomaudio/setup/*`. These source endpoints require the existing secret `X-Ingest-Key`, verified with constant-time comparison in `roomaudio/macos/server.py`. Unauthorized access returns 403. Do not loosen source authentication, expose `client.json`, store the ingest key in Git, or use plain public HTTP. The Windows private `%LOCALAPPDATA%\RoomAudio\client.json` has `https://129-158-49-130.sslip.io/roomaudio` appended to `server_fallbacks`, after LAN addresses. `client_transport.py` fails over on network errors and caches the successful endpoint within each process.

**Operational checks:** Mate HTTPS `/roomaudio/` responded 200; the source control path went from blocked 404 to 403 without a key, and an authorized `GET /client/recording-mode` responded 200 over HTTPS. Both capture manager and uploader were restarted using `Ensure-RoomAudio.ps1`; the pending recovery ID from October 26 was acknowledged with mode `voice`. A new live MP3 stream returned `online=true` and 262144 buffer bytes. The uploader got HTTP 201 and Mac received `20261027T022702.mp3`. Caddy config validation passed and `/roomaudio/setup/` remains 404.

**Limitation:** If Mate is shut down or cannot reach the Internet, Mac cannot execute a Windows process remotely. The control command stays pending and is delivered after Mate reconnects. The Windows Scheduled Task `RoomAudio Auto Recovery` now runs once per minute (`PT1M`, `MultipleInstances=IgnoreNew`) and runs tracked `Ensure-RoomAudio.ps1`. In addition to missing workers, it detects a **running but stuck** `capture_manager.py` using the independent `capture-manager.heartbeat` file, updated by the manager every ~10 seconds. If the process is at least 120 seconds old and its heartbeat is at least 90 seconds stale, it terminates that capture process tree and restarts only the manager. This preserves the stored recording mode, uploader, and AudioMonitor. On a first run without a heartbeat file, an already-aged manager is safely restarted. Restarting RoomAudio cannot recover a physically offline laptop or an unavailable Oracle relay.

**Watchdog deployment check (2026-10-27):** Both patched Windows files were copied to Mate with local backups, checked with `python -m py_compile` and the PowerShell parser, and `Ensure-RoomAudio.ps1` restarted the pre-patch manager. A new heartbeat file was produced; the Scheduled Task trigger was updated from `PT5M` to `PT1M` with `IgnoreNew` preserved. The manager resumed `voice` capture. The authenticated browser recovery POST was not independently retested; the previously queued recovery command was observed as acknowledged after network restoration.

## Weekly microphone schedule (2026-10-27)

A recurring on/off schedule is managed by the **Mac server**, not Windows Task Scheduler. It controls only the microphone capture process and live transmission, never the Mac server, the independent ASR worker, or past archives. The UI is the existing global **«Настройки источника»** accordion, available below either main tab. All times follow **Europe/Moscow (MSK)** regardless of the browser's timezone. The schedule is initially **disabled**; no microphone mode changes until the user explicitly enables and saves it.

- Interface: an enable switch, capture mode during active windows (`voice` or `continuous`), editable start/end time pickers, weekday chips, multiple intervals, and three quick templates (weekdays, every day, nights). One interval can cross midnight; its chosen weekday is the **start** day. A plain-language live summary shows whether the mic should currently be running and the next transition in Moscow time. An unsaved-change indication and explicit **Save** prevent accidental activation.
- Outside the configured windows, the effective capture mode is `off` (mic and live encoder stopped); inside it is the chosen schedule mode. Adjacent windows are continuous; overlapping intervals, invalid times/days, zero-length windows, and more than 14 intervals are rejected at the API boundary. Weekly wrap (Sunday→Monday) is supported. The evaluator uses the Mac's clock and timezone `Europe/Moscow` rather than the browser or Mate clock.
- The persisted schema extends the existing private `capture_settings.json`: `schedule_enabled`, `schedule_mode`, `schedule_rules`, and `schedule_updated_at`. The original `mode` remains the manual fallback. **Manual mode change disables automatic scheduling**, preserving the configured intervals for future reuse. Disabling scheduling resumes the last explicitly chosen manual mode, rather than silently keeping the scheduled `off`. `request_recovery` preserves both schedule and mode settings.
- Authenticated and origin-checked `POST /api/recording-schedule` accepts `{"enabled": bool, "mode": "voice"|"continuous", "rules": [{"days": [0..6], "start": "HH:MM", "end": "HH:MM"}]}`; weekdays use Monday=0. Reuses the existing RoomAudio session, security and atomic disk writes; maximum request size 8192 bytes. GET `/api/recording-mode`, `/api/status`, and the ingest-key-protected Windows polling endpoint all return the **computed effective mode** and a nonsecret `schedule` status with `next_transition_at` (Unix timestamp). There is no separate cron on Mac: the existing Mate manager polls every few seconds and applies the current desired mode. If Mate is offline at a boundary, it applies the *current* schedule upon reconnection, without trying to backfill skipped capture.
- Deploy **all three** `roomaudio/macos/{recording_settings.py,server.py,index.html}` together into the active `~/Library/Application Support/RoomAudio/` directory, leaving private `config.json`, `capture_settings.json` and all archives untouched. Compile/test before restarting only `com.kruspe.roomaudio` (do not restart ASR or Mate). Do not activate a live schedule as part of deployment.
- Regression test: `python3 -m unittest discover -s roomaudio/macos -p 'test_*.py'`. Includes weekday boundaries, Sunday rollover, overnight periods, adjoining windows, invalid overlaps, preservation of legacy mode and manual override.
