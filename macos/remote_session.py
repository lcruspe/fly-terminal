import time

DEFAULT_IDLE_TIMEOUT_SECONDS = 300
DEFAULT_IDLE_FPS_AFTER_SECONDS = 30
MIN_IDLE_TIMEOUT_SECONDS = 60
MAX_IDLE_TIMEOUT_SECONDS = 3600
USER_ACTIVITY_MESSAGE_TYPES = frozenset({
    "mousemove", "mousedown", "mouseup", "wheel", "keydown", "keyup", "text", "clipboard"
})


def is_user_activity_message(message_type: str) -> bool:
    return message_type in USER_ACTIVITY_MESSAGE_TYPES


def clamp_idle_timeout_seconds(value, fallback: int = DEFAULT_IDLE_TIMEOUT_SECONDS) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = int(fallback)
    return max(MIN_IDLE_TIMEOUT_SECONDS, min(MAX_IDLE_TIMEOUT_SECONDS, seconds))


class RemoteSessionIdleGuard:
    def __init__(self, timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS, now: float | None = None):
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.last_activity = time.monotonic() if now is None else float(now)

    def mark_activity(self, now: float | None = None) -> None:
        self.last_activity = time.monotonic() if now is None else float(now)

    def set_timeout(self, timeout_seconds: int) -> None:
        self.timeout_seconds = max(1, int(timeout_seconds))

    def idle_for(self, now: float | None = None) -> float:
        current = time.monotonic() if now is None else float(now)
        return max(0.0, current - self.last_activity)

    def remaining(self, now: float | None = None) -> float:
        return max(0.0, self.timeout_seconds - self.idle_for(now))

    def should_reduce_fps(self, after_seconds: int = DEFAULT_IDLE_FPS_AFTER_SECONDS, now: float | None = None) -> bool:
        return self.idle_for(now) >= max(1, int(after_seconds))
