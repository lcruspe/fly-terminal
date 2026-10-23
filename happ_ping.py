"""Bounded TCP-connect probes and short-lived, process-local VPN measurements."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import socket
import threading
import time


TTL_SECONDS = 180
CONNECT_TIMEOUT_SECONDS = 3
MAX_WORKERS = 8


class PingBusyError(Exception):
    pass


def tcp_ping(target):
    """Connect to the configured endpoint; never authenticate or change the VPN."""
    if target is None:
        return {"status": "unsupported", "rttMs": None}
    start = time.perf_counter()
    try:
        with socket.create_connection(target, timeout=CONNECT_TIMEOUT_SECONDS):
            return {"status": "ok", "rttMs": round((time.perf_counter() - start) * 1000, 1)}
    except TimeoutError:
        return {"status": "timeout", "rttMs": None}
    except (OSError, ValueError, OverflowError):
        # Network exceptions can contain private hosts; never return their text.
        return {"status": "unreachable", "rttMs": None}


def _timed_ping(target):
    result = dict(tcp_ping(target), measuredAt=int(time.time() * 1000))
    return time.monotonic() + TTL_SECONDS, result


class Measurements:
    def __init__(self):
        self._results = {}
        self._lock = threading.Lock()
        self._batch_lock = threading.Lock()

    def _prune(self):
        now = time.monotonic()
        self._results = {key: value for key, value in self._results.items() if value[1] > now}

    def latest(self, subscription_id, location):
        with self._lock:
            self._prune()
            cached = self._results.get((subscription_id, location["id"]))
            if cached is None or cached[0] != location.get("_pingTarget"):
                return None
            _, deadline, result = cached
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            return dict(result, expiresInMs=remaining) if remaining else None

    def measure(self, subscription):
        if not self._batch_lock.acquire(blocking=False):
            raise PingBusyError()
        try:
            # Multiple configs often share an endpoint. Probe it once per batch.
            targets = {location.get("_pingTarget") for location in subscription["locations"]}
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                pending = {executor.submit(_timed_ping, target): target for target in targets}
                for future in as_completed(pending):
                    target = pending[future]
                    deadline, result = future.result()
                    with self._lock:
                        self._prune()
                        for location in subscription["locations"]:
                            if location.get("_pingTarget") == target:
                                self._results[(subscription["id"], location["id"])] = (target, deadline, result)
            return [{"subscriptionId": subscription["id"], "locationId": location["id"],
                     **result}
                    for location in subscription["locations"]
                    if (result := self.latest(subscription["id"], location)) is not None]
        finally:
            self._batch_lock.release()
