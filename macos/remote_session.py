import time

DEFAULT_IDLE_TIMEOUT_SECONDS = 300
USER_ACTIVITY_MESSAGE_TYPES = frozenset({
    "mousemove", "mousedown", "mouseup", "wheel", "keydown", "keyup", "clipboard"
})


def is_user_activity_message(message_type: str) -> bool:
    return message_type in USER_ACTIVITY_MESSAGE_TYPES


class RemoteSessionIdleGuard:
    def __init__(self, timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS, now: float | None = None):
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.last_activity = time.monotonic() if now is None else float(now)

    def mark_activity(self, now: float | None = None) -> None:
        self.last_activity = time.monotonic() if now is None else float(now)

    def remaining(self, now: float | None = None) -> float:
        current = time.monotonic() if now is None else float(now)
        return max(0.0, self.timeout_seconds - (current - self.last_activity))
