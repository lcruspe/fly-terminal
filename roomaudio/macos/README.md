# RoomAudio Mac server sources

These files are the Python sources of the live Mac mini service. They rely on a local `config.json` (never committed), a WD archive mount, FFmpeg, whisper.cpp, Silero VAD environment and launchd. Do not assume the repository itself is a runnable service bundle without these dependencies.

The source of truth for the running copy is `~/Library/Application Support/RoomAudio/`. Keep the deployed sources and this directory synchronized. The report exporter and authenticated audio-download endpoint are documented in the root `ROOMAUDIO.md`.

Never commit recordings, recognized speech, the model, the transcripts database, credentials, or session tokens.
