"""Bounded in-memory relay for a continuously encoded MP3 live source.

The recorder owns the microphone.  Incoming MP3 bytes are never persisted here.
Listeners have bounded history and are disconnected on source replacement.
"""
from collections import deque
import threading
import time


class LiveHub:
    def __init__(self, max_bytes=256 * 1024):
        self.max_bytes = max_bytes
        self.lock = threading.Condition()
        self.history = deque()
        self.total = 0
        self.sequence = 0
        self.generation = 0
        self.active = False
        self.updated = 0.0
        self.listeners = 0
        self.source_session = None
        self.source_sequence = -1

    def begin(self):
        with self.lock:
            self.generation += 1
            self.history.clear()
            self.total = 0
            self.sequence = 0
            self.active = True
            self.updated = time.monotonic()
            self.lock.notify_all()
            return self.generation

    def end(self, generation):
        with self.lock:
            if generation == self.generation:
                self.active = False
                self.lock.notify_all()

    def publish(self, generation, chunk):
        if not chunk or len(chunk) > 65536:
            return False
        with self.lock:
            if generation != self.generation or not self.active:
                return False
            self.sequence += 1
            self.history.append((self.sequence, bytes(chunk)))
            self.total += len(chunk)
            while self.total > self.max_bytes and len(self.history) > 1:
                _, evicted = self.history.popleft()
                self.total -= len(evicted)
            self.updated = time.monotonic()
            self.lock.notify_all()
            return True

    def ingest_packet(self, session, sequence, data):
        """Add sequential encoded bytes from a persistent encoder, HTTP by HTTP."""
        if not data or len(data) > 65536 or len(session) != 32:
            return False
        if not session.isascii() or any(c not in "0123456789abcdef" for c in session):
            return False
        with self.lock:
            if self.source_session != session or not self.active or time.monotonic() - self.updated > 8:
                # Start new MP3 decoder generation. A genuine new stream must
                # begin at packet zero; random stale sources cannot evict it.
                if sequence != 0:
                    return False
                self.generation += 1
                self.history.clear()
                self.total = 0
                self.sequence = 0
                self.active = True
                self.source_session = session
                self.source_sequence = -1
            if sequence != self.source_sequence + 1:
                return False
            self.source_sequence = sequence
            self.sequence += 1
            self.history.append((self.sequence, bytes(data)))
            self.total += len(data)
            while self.total > self.max_bytes and len(self.history) > 1:
                _, evicted = self.history.popleft()
                self.total -= len(evicted)
            self.updated = time.monotonic()
            self.lock.notify_all()
            return True

    def source_ready(self):
        with self.lock:
            return self.active and time.monotonic() - self.updated < 8

    def status(self):
        with self.lock:
            return {"online": self.active and time.monotonic() - self.updated < 8,
                    "listeners": self.listeners, "buffer_bytes": self.total}

    def subscribe(self):
        with self.lock:
            if not self.active or time.monotonic() - self.updated > 8:
                return None
            self.listeners += 1
            # Include a short pre-roll to help decoder lock on MP3 frames.
            initial = self.sequence
            bytes_kept = 0
            for seq, data in reversed(self.history):
                bytes_kept += len(data)
                initial = seq - 1
                if bytes_kept >= 24 * 1024:
                    break
            return self.generation, initial

    def unsubscribe(self):
        with self.lock:
            self.listeners = max(0, self.listeners - 1)

    def read(self, generation, after, wait=3):
        with self.lock:
            if self.generation != generation or not self.active:
                return None
            if self.sequence <= after:
                self.lock.wait(wait)
            if self.generation != generation or not self.active:
                return None
            if self.sequence <= after:
                if time.monotonic() - self.updated > 8:
                    return None
                return [], after
            oldest = self.history[0][0]
            # An overloaded listener skips outdated frames rather than
            # accumulating hours of backlog in server memory.
            if after < oldest - 1:
                after = oldest - 1
            chunks = [(seq, blob) for seq, blob in self.history if seq > after]
            return chunks, chunks[-1][0] if chunks else after


def chunked_mp3(reader):
    """Decode one HTTP/1.1 chunked transfer; bound all input sizes."""
    while True:
        line = reader.readline(65)
        if not line or len(line) >= 65 or not line.endswith(b"\r\n"):
            raise ValueError("Malformed live upload")
        try:
            size = int(line[:-2].split(b";", 1)[0], 16)
        except ValueError as exc:
            raise ValueError("Bad live chunk length") from exc
        if size > 65536 or size < 0:
            raise ValueError("Live chunk too large")
        if size == 0:
            if reader.readline(3) != b"\r\n":
                raise ValueError("Unsupported chunk trailers")
            return
        data = reader.read(size)
        if len(data) != size or reader.read(2) != b"\r\n":
            raise ValueError("Truncated live chunk")
        yield data


hub = LiveHub()