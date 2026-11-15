# RoomAudio Mac server sources

These files are the Python sources of the live Mac mini service. They rely on a local `config.json` (never committed), a WD archive mount, FFmpeg, whisper.cpp, Silero VAD environment and launchd. Do not assume the repository itself is a runnable service bundle without these dependencies.

The source of truth for the running copy is `~/Library/Application Support/RoomAudio/`. Keep the deployed sources and this directory synchronized. The report exporter and authenticated audio-download endpoint are documented in the root `ROOMAUDIO.md`.

Never commit recordings, recognized speech, the model, the transcripts database, credentials, or session tokens.

## On-demand Yandex Station Lite microphone

The optional `alice_source` is independent of the Mate live relay. The authenticated
`/alice-live.mp3` endpoint starts capture only while a client is listening. The
response requires a path-specific media token. Ending the last listener stops
capture; an on-device watchdog restores the ordinary Quasar profile if the SSH
session or Mac fails. Starting and stopping capture briefly restarts Quasar.
Recordings go under `<archive>/_alice/YYYYMMDD/` and obey the existing retention
period. Alice transcripts are stored separately in `transcripts-alice.sqlite3`.
A second launchd worker runs `transcriber.py` with `ROOMAUDIO_SOURCE=alice`;
both workers share a lock so only one Whisper job runs at a time.

The receiver is `../station/alice_receiver.go`; build a Linux ARMv7 binary with
`CGO_ENABLED=0 GOOS=linux GOARCH=arm GOARM=7 go build -o alice_receiver alice_receiver.go`.
The device profile script is `../station/alice_profile.sh`. It refuses to run
unless the exact supported firmware and VQE tap hashes match. The VQE tap is
obtained from the Alisa Voice project at commit
`35734bfbc000e92fc04a147a72df52ad304137f9`, path
`engines/bridge/build/vqe_tap.so`, SHA-256
`9a237062255c9fc44e4666a3e1273e33064f652b9428fb06781ee7df17a7a22b`.
It copies the already processed 16 kHz mono VQE output into a local Unix datagram
socket; it is not an independent ALSA capture. Do not use the stock bridge
installer on Lite 1: that project does not support its bridge mode on this model.

Provision `/data/opt/roomaudio-alice` privately with the receiver, tap, profile
script, SHA-256 of the current `/system/vendor/quasar/launch.json`, and a copy
of that JSON with **only** the platformd task's `LD_PRELOAD` and
`ALICE_CAPTURE_SOCKET` added. Do not replace the original launcher config or
`quasar.cfg`. Rebuild the staged profile if the stock launcher changes. Private
Mac configuration sets `alice_source.host`, `alice_source.identity_file`, and
`alice_source.known_hosts`; use a dedicated SSH key and verified host key.
The receiver directory on the station and the SSH credentials on the Mac must
not be world-readable. Never commit these files or captured audio.
