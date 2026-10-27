"""Authenticated, session-bound CSRF protection for RoomAudio JSON writes.

Works behind multi-hop HTTP/Tailscale/Oracle reverse proxies without trusting
Host or X-Forwarded-Host. The browser must first read its token from the
same-origin GET endpoint. Cross-site pages cannot read it (no CORS) or send a
custom header via a simple HTML form.
"""
import hashlib
import hmac
import re

TOKEN_RE = re.compile(r"[0-9a-f]{64}\Z")


def issue_token(secret, identity):
    if not isinstance(identity, bytes) or not identity:
        raise ValueError("Missing authorized session identity")
    return hmac.new(secret, b"roomaudio-csrf-v1:\x00" + identity, hashlib.sha256).hexdigest()


def valid_token(secret, identity, supplied):
    if (not isinstance(supplied, str) or TOKEN_RE.fullmatch(supplied) is None or
            not isinstance(identity, bytes) or not identity):
        return False
    return hmac.compare_digest(supplied, issue_token(secret, identity))
