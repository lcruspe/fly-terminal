"""Continuous RoomAudio live encoder with reconnectable short authenticated uploads.

The recorder is the sole microphone owner. This module receives the same
48kHz mono float PCM already used for the archive, encodes one long MP3
bitstream, and publishes consecutive byte ranges in small HTTP requests.
"""
import http.client
import logging
import queue
import secrets
import subprocess
import threading
import time
from urllib.parse import urlsplit


class LivePublisher:
    def __init__(self, config):
        self.config = config
        self.queue = queue.Queue(maxsize=100)
        self.stop_event = threading.Event()
        self.thread = None
        self.encoder = None
        self.dropped = 0

    def start(self):
        if not self.thread:
            self.thread = threading.Thread(target=self._loop, name="roomaudio-live",
                                           daemon=True)
            self.thread.start()

    def feed(self, mono_f32le):
        if self.stop_event.is_set() or not mono_f32le:
            return
        try:
            self.queue.put_nowait(mono_f32le)
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.dropped += 1
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(mono_f32le)
            except queue.Full:
                self.dropped += 1

    def _terminate_encoder(self):
        proc = self.encoder
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    def stop(self):
        self.stop_event.set()
        self._terminate_encoder()
        if self.thread:
            self.thread.join(timeout=3)

    def _write_pcm(self, proc):
        try:
            while not self.stop_event.is_set() and proc.poll() is None:
                try:
                    data = self.queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                proc.stdin.write(data)
                proc.stdin.flush()
        except (OSError, ValueError):
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    def _loop(self):
        target = urlsplit(self.config["server"].rstrip("/") + "/ingest/live")
        if target.scheme not in ("http", "https") or not target.hostname:
            logging.error("Invalid RoomAudio live endpoint")
            return
        delay = 1.0
        while not self.stop_event.is_set():
            cmd = [self.config["ffmpeg_path"], "-hide_banner", "-nostdin",
                   "-loglevel", "error", "-f", "f32le", "-ar", "48000",
                   "-ac", "1", "-i", "pipe:0", "-vn", "-c:a", "libmp3lame",
                   "-b:a", "96k", "-f", "mp3", "pipe:1"]
            proc = None
            connection = None
            writer = None
            try:
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, bufsize=-1,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                self.encoder = proc
                writer = threading.Thread(target=self._write_pcm, args=(proc,),
                                          name="roomaudio-live-encoder", daemon=True)
                writer.start()
                connection_cls = (http.client.HTTPSConnection
                                  if target.scheme == "https"
                                  else http.client.HTTPConnection)
                connection = connection_cls(target.hostname, target.port, timeout=8)
                path = target.path or "/ingest/live"
                session = secrets.token_hex(16)
                sequence = 0
                while not self.stop_event.is_set():
                    # BufferedReader.read() coalesces continuous MP3 data;
                    # one 8192-byte packet is ~0.68 seconds at 96 kbps.
                    block = proc.stdout.read(8192)
                    if not block:
                        raise OSError("Live encoder exited")
                    connection.request(
                        "POST", path, body=block,
                        headers={"Content-Type": "audio/mpeg",
                                 "X-Ingest-Key": self.config["ingest_key"],
                                 "X-Live-Stream": session,
                                 "X-Live-Sequence": str(sequence)})
                    response = connection.getresponse()
                    response.read()
                    if response.status != 200:
                        raise OSError("Live upload HTTP %s" % response.status)
                    sequence += 1
                delay = 1.0
            except (OSError, http.client.HTTPException) as error:
                if not self.stop_event.is_set():
                    logging.warning("Live MP3 upload reconnect: %s", error)
            finally:
                self._terminate_encoder()
                if connection:
                    try:
                        connection.close()
                    except OSError:
                        pass
                if writer:
                    writer.join(timeout=2)
                if proc:
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                self.encoder = None
                # Do not replay old PCM after a broken network connection.
                while True:
                    try:
                        self.queue.get_nowait()
                    except queue.Empty:
                        break
            if not self.stop_event.is_set():
                self.stop_event.wait(delay)
                delay = min(12.0, delay * 1.7)
