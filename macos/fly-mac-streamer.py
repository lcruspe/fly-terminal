#!/usr/bin/env python3
import asyncio
import ctypes
import ctypes.util
import json
import logging
import math
import os
import re
import struct
import subprocess
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, Optional

import websockets
from aiohttp import web

from remote_session import DEFAULT_IDLE_TIMEOUT_SECONDS, RemoteSessionIdleGuard, is_user_activity_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("fly-mac-streamer")

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
USER_APP_BIN = Path.home() / "Applications" / "FlyDesktopCapture.app" / "Contents" / "MacOS" / "FlyDesktopCapture"
LOCAL_APP_BIN = SCRIPT_DIR / "bin" / "FlyDesktopCapture.app" / "Contents" / "MacOS" / "FlyDesktopCapture"
ENCODER_BIN = USER_APP_BIN if USER_APP_BIN.exists() else (LOCAL_APP_BIN if LOCAL_APP_BIN.exists() else (SCRIPT_DIR / "bin" / "fly-mac-encoder"))
PORT = int(os.environ.get("FLY_STREAMER_PORT", 5905))
TARGET_FPS = int(os.environ.get("FLY_STREAMER_FPS", 60))
TARGET_WIDTH = int(os.environ.get("FLY_STREAMER_WIDTH", 1920))
TARGET_HEIGHT = int(os.environ.get("FLY_STREAMER_HEIGHT", 1080))
REMOTE_IDLE_TIMEOUT_SECONDS = int(os.environ.get("FLY_DESKTOP_IDLE_TIMEOUT_SECONDS", DEFAULT_IDLE_TIMEOUT_SECONDS))
H264_CODEC = os.environ.get("FLY_STREAMER_H264_CODEC", "avc1.4D002A")
SOCKET_PATH = os.environ.get("FLY_STREAMER_SOCKET_PATH", "/tmp/fly-mac-stream.sock")
VALID_STREAM_FPS = {15, 30, 45, 60}
VALID_DISPLAY_NAMES = {"", "Fly Remote", "Fly Browser"}
TARGET_DISPLAY_BOUNDS = [0.0, 0.0, 2560.0, 1440.0]
TARGET_DISPLAY_PIXELS = [2560, 1440]
TARGET_BITRATE = int(os.environ.get("FLY_STREAMER_BITRATE", 4_500_000))
MIN_BITRATE = 300_000
MAX_BITRATE = 20_000_000
STREAM_QUEUE_MAX_BYTES = int(os.environ.get("FLY_STREAM_QUEUE_MAX_BYTES", 4 * 1024 * 1024))
STREAM_QUEUE_MAX_AGE_MS = int(os.environ.get("FLY_STREAM_QUEUE_MAX_AGE_MS", 250))
STREAM_SEND_TIMEOUT_SECONDS = float(os.environ.get("FLY_STREAM_SEND_TIMEOUT_SECONDS", 0.35))
STREAM_TRANSPORT_BUFFER_MAX_BYTES = int(os.environ.get("FLY_STREAM_TRANSPORT_BUFFER_MAX_BYTES", 1024 * 1024))
KEYFRAME_REQUEST_COOLDOWN_MS = int(os.environ.get("FLY_KEYFRAME_REQUEST_COOLDOWN_MS", 250))
EXTENDED_FRAME_HEADER_SIZE = 34
EXTENDED_FRAME_FLAG = 0x80
EXTENDED_FRAME_VERSION = 1

# MARK: - CoreGraphics & AppKit ctypes setup

cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))
cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
appkit = ctypes.cdll.LoadLibrary(ctypes.util.find_library("AppKit"))

class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

class CGRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("w", ctypes.c_double), ("h", ctypes.c_double)]

cg.CGMainDisplayID.restype = ctypes.c_uint32
cg.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
cf.CFStringCreateWithCString.restype = ctypes.c_void_p
cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
cf.CFDictionaryGetValue.restype = ctypes.c_void_p
cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
cf.CFGetTypeID.restype = ctypes.c_ulong
cf.CFGetTypeID.argtypes = [ctypes.c_void_p]
cf.CFBooleanGetTypeID.restype = ctypes.c_ulong
cf.CFBooleanGetValue.restype = ctypes.c_bool
cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
cg.CGDisplayPixelsWide.restype = ctypes.c_size_t
cg.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
cg.CGDisplayPixelsHigh.restype = ctypes.c_size_t
cg.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]

cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
cg.CGEventCreateScrollWheelEvent2.restype = ctypes.c_void_p
cg.CGEventCreateScrollWheelEvent2.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
    ctypes.c_int32, ctypes.c_int32, ctypes.c_int32
]
cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
cg.CGEventKeyboardSetUnicodeString.restype = None
cg.CGEventKeyboardSetUnicodeString.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
cg.CGEventSetFlags.restype = None
cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
cg.CGEventPost.restype = None
cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
cf.CFRelease.restype = None
cf.CFRelease.argtypes = [ctypes.c_void_p]

# Event constants
kCGHIDEventTap = 0
kCGEventLeftMouseDown = 1
kCGEventLeftMouseUp = 2
kCGEventRightMouseDown = 3
kCGEventRightMouseUp = 4
kCGEventMouseMoved = 5
kCGEventLeftMouseDragged = 6
kCGEventRightMouseDragged = 7
kCGEventOtherMouseDown = 25
kCGEventOtherMouseUp = 26
kCGEventOtherMouseDragged = 27
kCGScrollEventUnitPixel = 0

kCGMouseButtonLeft = 0
kCGMouseButtonRight = 1
kCGMouseButtonCenter = 2

# Modifier flags
kCGEventFlagMaskCommand = 0x00100000
kCGEventFlagMaskShift = 0x00020000
kCGEventFlagMaskControl = 0x00040000
kCGEventFlagMaskAlternate = 0x00080000

# Key mapping table
WEB_KEY_TO_MAC_VK = {
    "KeyA": 0x00, "KeyS": 0x01, "KeyD": 0x02, "KeyF": 0x03, "KeyH": 0x04, "KeyG": 0x05, "KeyZ": 0x06, "KeyX": 0x07,
    "KeyC": 0x08, "KeyV": 0x09, "KeyB": 0x0B, "KeyQ": 0x0C, "KeyW": 0x0D, "KeyE": 0x0E, "KeyR": 0x0F, "KeyY": 0x10,
    "KeyT": 0x11, "Digit1": 0x12, "Digit2": 0x13, "Digit3": 0x14, "Digit4": 0x15, "Digit6": 0x16, "Digit5": 0x17,
    "Equal": 0x18, "Digit9": 0x19, "Digit7": 0x1A, "Minus": 0x1B, "Digit8": 0x1C, "Digit0": 0x1D, "BracketRight": 0x1E,
    "KeyO": 0x1F, "KeyU": 0x20, "BracketLeft": 0x21, "KeyI": 0x22, "KeyP": 0x23, "KeyL": 0x25, "KeyJ": 0x26,
    "Quote": 0x27, "KeyK": 0x28, "Semicolon": 0x29, "Backslash": 0x2A, "Comma": 0x2B, "Slash": 0x2C, "KeyN": 0x2D,
    "KeyM": 0x2E, "Period": 0x2F, "Backquote": 0x32,
    "Return": 0x24, "Enter": 0x24, "Tab": 0x30, "Space": 0x31, "Backspace": 0x33, "Escape": 0x35,
    "MetaLeft": 0x37, "MetaRight": 0x36, "Command": 0x37, "ShiftLeft": 0x38, "ShiftRight": 0x3C, "CapsLock": 0x39,
    "AltLeft": 0x3A, "AltRight": 0x3D, "ControlLeft": 0x3B, "ControlRight": 0x3E,
    "ArrowLeft": 0x7B, "ArrowRight": 0x7C, "ArrowDown": 0x7D, "ArrowUp": 0x7E,
    "Home": 0x73, "End": 0x77, "PageUp": 0x74, "PageDown": 0x79, "Delete": 0x75,
    "F1": 0x7A, "F2": 0x78, "F3": 0x63, "F4": 0x76, "F5": 0x60, "F6": 0x61, "F7": 0x62, "F8": 0x64,
    "F9": 0x65, "F10": 0x6D, "F11": 0x67, "F12": 0x6F
}


def get_screen_dimensions():
    return int(TARGET_DISPLAY_BOUNDS[2]), int(TARGET_DISPLAY_BOUNDS[3])


def parse_frame_metadata(packet: bytes):
    if not packet:
        return {"flags": 0, "is_key": False, "frame_id": 0, "capture_pts_us": 0, "encode_start_ns": 0, "encode_done_ns": 0, "data_offset": 0}
    flags = packet[0]
    if flags & EXTENDED_FRAME_FLAG and len(packet) >= EXTENDED_FRAME_HEADER_SIZE and packet[1] == EXTENDED_FRAME_VERSION:
        return {
            "flags": flags,
            "is_key": bool(flags & 1),
            "frame_id": struct.unpack_from("!Q", packet, 2)[0],
            "capture_pts_us": struct.unpack_from("!Q", packet, 10)[0],
            "encode_start_ns": struct.unpack_from("!Q", packet, 18)[0],
            "encode_done_ns": struct.unpack_from("!Q", packet, 26)[0],
            "data_offset": EXTENDED_FRAME_HEADER_SIZE,
        }
    if len(packet) >= 9:
        return {
            "flags": flags,
            "is_key": bool(flags & 1),
            "frame_id": 0,
            "capture_pts_us": max(0, struct.unpack_from("!q", packet, 1)[0]) * 1000,
            "encode_start_ns": 0,
            "encode_done_ns": 0,
            "data_offset": 9,
        }
    return {"flags": flags, "is_key": bool(flags & 1), "frame_id": 0, "capture_pts_us": 0, "encode_start_ns": 0, "encode_done_ns": 0, "data_offset": 1}


def detect_h264_codec(packet: bytes):
    """Возвращает RFC 6381 avc1 codec из SPS Annex B пакета."""
    metadata = parse_frame_metadata(packet)
    data = packet[metadata["data_offset"]:]
    starts = []
    i = 0
    while i < len(data) - 3:
        if data[i:i + 4] == b"\x00\x00\x00\x01":
            starts.append((i, 4))
            i += 4
        elif data[i:i + 3] == b"\x00\x00\x01":
            starts.append((i, 3))
            i += 3
        else:
            i += 1
    for index, (start, prefix_len) in enumerate(starts):
        nal_start = start + prefix_len
        nal_end = starts[index + 1][0] if index + 1 < len(starts) else len(data)
        nal = data[nal_start:nal_end]
        if len(nal) >= 4 and (nal[0] & 0x1F) == 7:
            return f"avc1.{nal[1]:02X}{nal[2]:02X}{nal[3]:02X}"
    return None


def is_screen_locked():
    session = cg.CGSessionCopyCurrentDictionary()
    if not session:
        return False
    key = cf.CFStringCreateWithCString(None, b"CGSSessionScreenIsLocked", 0x08000100)
    if not key:
        cf.CFRelease(session)
        return False
    try:
        value = cf.CFDictionaryGetValue(session, key)
        if not value or cf.CFGetTypeID(value) != cf.CFBooleanGetTypeID():
            return False
        return bool(cf.CFBooleanGetValue(value))
    finally:
        cf.CFRelease(key)
        cf.CFRelease(session)


def valid_stream_dimensions(width: int, height: int):
    return (
        640 <= width <= 7680
        and 360 <= height <= 4320
        and width % 2 == 0
        and height % 2 == 0
    )


def inject_mouse(event_type: str, x_norm: float, y_norm: float, button: int = 0, drag_button: Optional[int] = None):
    screen_w, screen_h = get_screen_dimensions()
    x = TARGET_DISPLAY_BOUNDS[0] + max(0.0, min(float(screen_w), x_norm * screen_w))
    y = TARGET_DISPLAY_BOUNDS[1] + max(0.0, min(float(screen_h), y_norm * screen_h))
    pos = CGPoint(x, y)

    if event_type == "move" and drag_button is not None:
        if drag_button == 0:
            ev = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseDragged, pos, kCGMouseButtonLeft)
        elif drag_button == 2:
            ev = cg.CGEventCreateMouseEvent(None, kCGEventRightMouseDragged, pos, kCGMouseButtonRight)
        else:
            ev = cg.CGEventCreateMouseEvent(None, kCGEventOtherMouseDragged, pos, kCGMouseButtonCenter)
    elif event_type == "move":
        ev = cg.CGEventCreateMouseEvent(None, kCGEventMouseMoved, pos, kCGMouseButtonLeft)
    elif event_type == "down":
        if button == 0:
            ev = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, pos, kCGMouseButtonLeft)
        elif button == 2:
            ev = cg.CGEventCreateMouseEvent(None, kCGEventRightMouseDown, pos, kCGMouseButtonRight)
        else:
            ev = cg.CGEventCreateMouseEvent(None, kCGEventOtherMouseDown, pos, kCGMouseButtonCenter)
    elif event_type == "up":
        if button == 0:
            ev = cg.CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, pos, kCGMouseButtonLeft)
        elif button == 2:
            ev = cg.CGEventCreateMouseEvent(None, kCGEventRightMouseUp, pos, kCGMouseButtonRight)
        else:
            ev = cg.CGEventCreateMouseEvent(None, kCGEventOtherMouseUp, pos, kCGMouseButtonCenter)
    else:
        return

    if ev:
        cg.CGEventPost(kCGHIDEventTap, ev)
        cf.CFRelease(ev)


def inject_scroll(dx: int, dy: int):
    # CoreGraphics принимает целые пиксели; дробная часть сохраняется на уровне сессии.
    ev = cg.CGEventCreateScrollWheelEvent2(
        None,
        kCGScrollEventUnitPixel,
        2,
        int(dy),
        int(dx),
        0
    )
    if ev:
        cg.CGEventPost(kCGHIDEventTap, ev)
        cf.CFRelease(ev)


def inject_key(code: str, key: str, is_down: bool, modifiers: dict = None):
    vk = WEB_KEY_TO_MAC_VK.get(code)
    if vk is not None:
        ev = cg.CGEventCreateKeyboardEvent(None, vk, is_down)
        if ev:
            flags = 0
            if modifiers:
                if modifiers.get("meta") or modifiers.get("cmd"):
                    flags |= kCGEventFlagMaskCommand
                if modifiers.get("shift"):
                    flags |= kCGEventFlagMaskShift
                if modifiers.get("ctrl") or modifiers.get("control"):
                    flags |= kCGEventFlagMaskControl
                if modifiers.get("alt") or modifiers.get("option"):
                    flags |= kCGEventFlagMaskAlternate
            if flags:
                cg.CGEventSetFlags(ev, flags)
            cg.CGEventPost(kCGHIDEventTap, ev)
            cf.CFRelease(ev)
        return

    # Direct Unicode string typing
    if is_down and len(key) == 1:
        ev = cg.CGEventCreateKeyboardEvent(None, 0, True)
        if ev:
            utf16_bytes = key.encode("utf-16le")
            utf16_arr = (ctypes.c_uint16 * len(key)).from_buffer_copy(utf16_bytes)
            cg.CGEventKeyboardSetUnicodeString(ev, len(key), ctypes.byref(utf16_arr))
            cg.CGEventPost(kCGHIDEventTap, ev)
            cf.CFRelease(ev)

        up_ev = cg.CGEventCreateKeyboardEvent(None, 0, False)
        if up_ev:
            cg.CGEventPost(kCGHIDEventTap, up_ev)
            cf.CFRelease(up_ev)


def inject_clipboard(text: str):
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        inject_key("KeyV", "v", True, {"meta": True})
        time.sleep(0.02)
        inject_key("KeyV", "v", False, {"meta": True})
    except Exception as e:
        logger.warning("Clipboard injection error: %s", e)


def inject_text(text: str):
    for char in text:
        inject_key("", char, True)


@dataclass
class OutboundMessage:
    kind: str
    payload: object
    enqueued_ns: int
    size: int = 0
    is_key: bool = False
    frame_id: int = 0


@dataclass
class ClientState:
    websocket: object
    client_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    queue: Deque[OutboundMessage] = field(default_factory=deque)
    queue_event: asyncio.Event = field(default_factory=asyncio.Event)
    queue_bytes: int = 0
    waiting_for_keyframe: bool = True
    sender_task: Optional[asyncio.Task] = None
    pressed_buttons: set = field(default_factory=set)
    pressed_keys: Dict[str, tuple] = field(default_factory=dict)
    last_x: float = 0.5
    last_y: float = 0.5
    scroll_x: float = 0.0
    scroll_y: float = 0.0
    dropped_frames: int = 0
    sent_frames: int = 0
    window_bytes: int = 0
    window_started_ns: int = field(default_factory=time.monotonic_ns)
    queue_delay_total_ms: float = 0.0
    queue_delay_samples: int = 0
    queue_delay_max_ms: float = 0.0
    media_bridge: bool = False
    last_reliable_seq: int = 0


# MARK: - Server & Encoder Orchestration

class StreamServer:
    def __init__(self):
        self.clients: Dict[object, ClientState] = {}
        self.latest_keyframe: bytes = b""
        self.h264_codec = H264_CODEC
        self.encoder_proc: subprocess.Popen = None
        self.running = False
        self.tcc_required = False
        self.status_message = "Инициализация захвата экрана..."
        self.target_width = TARGET_WIDTH
        self.target_height = TARGET_HEIGHT
        self.target_fps = TARGET_FPS
        self.target_bitrate = TARGET_BITRATE
        self.requested_display_name = os.environ.get("FLY_STREAMER_DISPLAY_NAME", "")
        self.follow_main_when_locked = os.environ.get("FLY_STREAMER_FOLLOW_MAIN_WHEN_LOCKED", "0") == "1"
        self.screen_locked = is_screen_locked()
        self.target_display_name = self._effective_display_name()
        self.encoder_lock = asyncio.Lock()
        self.encoder_control_lock = asyncio.Lock()
        self.unix_server = None
        self.last_frame_id = 0
        self.last_keyframe_request_ns = 0
        self.last_frame_telemetry_ns = 0
        self.control_owner_id: Optional[str] = None

    def _effective_display_name(self):
        if self.follow_main_when_locked and self.screen_locked:
            return ""
        return self.requested_display_name

    def _enqueue_json(self, state: ClientState, msg: dict):
        payload = json.dumps(msg, separators=(",", ":"))
        state.queue.append(OutboundMessage("json", payload, time.monotonic_ns()))
        state.queue_event.set()

    async def broadcast_json(self, msg: dict):
        for state in list(self.clients.values()):
            self._enqueue_json(state, msg)

    def _drop_queued_video(self, state: ClientState):
        kept = deque()
        dropped = 0
        bytes_kept = 0
        for item in state.queue:
            if item.kind == "video":
                dropped += 1
                continue
            kept.append(item)
            bytes_kept += item.size
        state.queue = kept
        state.queue_bytes = bytes_kept
        state.dropped_frames += dropped
        state.waiting_for_keyframe = True
        return dropped

    def _queue_video(self, state: ClientState, payload: bytes, metadata: dict):
        now_ns = time.monotonic_ns()
        oldest_video = next((item for item in state.queue if item.kind == "video"), None)
        stale = oldest_video is not None and (now_ns - oldest_video.enqueued_ns) / 1_000_000 > STREAM_QUEUE_MAX_AGE_MS
        over_bytes = state.queue_bytes + len(payload) > STREAM_QUEUE_MAX_BYTES
        if stale or over_bytes:
            self._drop_queued_video(state)
            self.request_keyframe("client_queue_overload")
        if state.waiting_for_keyframe and not metadata["is_key"]:
            state.dropped_frames += 1
            return
        if metadata["is_key"]:
            state.waiting_for_keyframe = False
        state.queue.append(OutboundMessage("video", payload, now_ns, len(payload), metadata["is_key"], metadata["frame_id"]))
        state.queue_bytes += len(payload)
        state.queue_event.set()

    async def _send_transport_stats(self, state: ClientState):
        now_ns = time.monotonic_ns()
        elapsed = max(1, now_ns - state.window_started_ns)
        if elapsed < 1_000_000_000:
            return
        bitrate_bps = int(state.window_bytes * 8 * 1_000_000_000 / elapsed)
        avg_queue_ms = state.queue_delay_total_ms / state.queue_delay_samples if state.queue_delay_samples else 0.0
        payload = json.dumps({
            "type": "transport_stats",
            "bitrateBps": bitrate_bps,
            "queueBytes": state.queue_bytes,
            "queueDelayMs": round(avg_queue_ms, 2),
            "queueDelayMaxMs": round(state.queue_delay_max_ms, 2),
            "droppedFrames": state.dropped_frames,
            "sentFrames": state.sent_frames,
        }, separators=(",", ":"))
        try:
            await asyncio.wait_for(state.websocket.send(payload), timeout=STREAM_SEND_TIMEOUT_SECONDS)
        except Exception:
            return
        state.window_started_ns = now_ns
        state.window_bytes = 0
        state.queue_delay_total_ms = 0.0
        state.queue_delay_samples = 0
        state.queue_delay_max_ms = 0.0

    async def _client_sender(self, state: ClientState):
        websocket = state.websocket
        try:
            while self.running:
                if not state.queue:
                    state.queue_event.clear()
                    await state.queue_event.wait()
                    continue
                item = state.queue.popleft()
                if item.kind == "video":
                    state.queue_bytes = max(0, state.queue_bytes - item.size)
                    age_ms = (time.monotonic_ns() - item.enqueued_ns) / 1_000_000
                    if age_ms > STREAM_QUEUE_MAX_AGE_MS:
                        self._drop_queued_video(state)
                        self.request_keyframe("stale_client_frame")
                        continue
                    state.queue_delay_total_ms += age_ms
                    state.queue_delay_samples += 1
                    state.queue_delay_max_ms = max(state.queue_delay_max_ms, age_ms)
                transport = getattr(websocket, "transport", None)
                if transport is not None and transport.get_write_buffer_size() > STREAM_TRANSPORT_BUFFER_MAX_BYTES:
                    await websocket.close(code=4002, reason="stream transport buffer overloaded")
                    return
                try:
                    await asyncio.wait_for(websocket.send(item.payload), timeout=STREAM_SEND_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    await websocket.close(code=4002, reason="stream send timeout")
                    return
                if item.kind == "video":
                    state.sent_frames += 1
                    state.window_bytes += item.size
                    await self._send_transport_stats(state)
        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
            pass
        except Exception as exc:
            logger.warning("Client sender failed (%s): %s", state.client_id, exc)
            try:
                await websocket.close(code=1011, reason="stream sender failed")
            except Exception:
                pass

    async def _send_encoder_command(self, command: dict):
        proc = self.encoder_proc
        if not proc or proc.poll() is not None or not proc.stdin:
            return False
        data = (json.dumps(command, separators=(",", ":")) + "\n").encode("utf-8")
        async with self.encoder_control_lock:
            try:
                await asyncio.to_thread(proc.stdin.write, data)
                await asyncio.to_thread(proc.stdin.flush)
                return True
            except Exception as exc:
                logger.warning("Encoder control command failed: %s", exc)
                return False

    def request_keyframe(self, reason: str = "client_request"):
        now_ns = time.monotonic_ns()
        if (now_ns - self.last_keyframe_request_ns) / 1_000_000 < KEYFRAME_REQUEST_COOLDOWN_MS:
            return
        self.last_keyframe_request_ns = now_ns
        asyncio.create_task(self._send_encoder_command({"type": "keyframe", "reason": reason}))

    async def set_bitrate(self, bitrate: int):
        bitrate = max(MIN_BITRATE, min(MAX_BITRATE, int(bitrate)))
        if bitrate == self.target_bitrate:
            return True
        self.target_bitrate = bitrate
        if self.encoder_proc and self.encoder_proc.poll() is None:
            return await self._send_encoder_command({"type": "bitrate", "value": bitrate})
        return True

    async def start_encoder(self):
        if not self.clients:
            logger.debug("Encoder start skipped: no active stream clients")
            return
        if self.encoder_proc and self.encoder_proc.poll() is None:
            return
        if not ENCODER_BIN.exists():
            logger.info("Compiling native fly-mac-encoder...")
            swift_src = SCRIPT_DIR / "fly-mac-encoder.swift"
            ENCODER_BIN.parent.mkdir(parents=True, exist_ok=True)
            res = subprocess.run(
                ["swiftc", "-O", str(swift_src), "-o", str(ENCODER_BIN)],
                capture_output=True,
                text=True
            )
            if res.returncode != 0:
                logger.error("Failed to compile fly-mac-encoder: %s", res.stderr)
                raise RuntimeError("Failed to compile fly-mac-encoder")

        if self.unix_server is None:
            logger.info("Initializing Unix socket server...")
            await self._start_unix_socket_server()

        encoder_env = os.environ.copy()
        encoder_env.update({
            "FLY_STREAMER_WIDTH": str(self.target_width),
            "FLY_STREAMER_HEIGHT": str(self.target_height),
            "FLY_STREAMER_FPS": str(self.target_fps),
            "FLY_STREAMER_BITRATE": str(self.target_bitrate),
            "FLY_STREAMER_DISPLAY_NAME": self.target_display_name,
            "FLY_STREAMER_SOCKET_PATH": SOCKET_PATH,
        })
        logger.info(
            "Starting fly-mac-encoder subprocess: %s (%dx%d @ %d FPS)",
            ENCODER_BIN, self.target_width, self.target_height, self.target_fps,
        )
        encoder_proc = subprocess.Popen(
            [str(ENCODER_BIN)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=encoder_env,
            bufsize=0,
        )
        self.encoder_proc = encoder_proc

        loop = asyncio.get_running_loop()
        loop.create_task(self._read_encoder_frames(encoder_proc))
        loop.create_task(self._log_encoder_stderr(encoder_proc))

    async def ensure_encoder_started(self):
        async with self.encoder_lock:
            await self.start_encoder()

    async def stop_encoder_if_idle(self):
        if self.clients:
            return
        async with self.encoder_lock:
            if self.clients:
                return
            encoder_proc = self.encoder_proc
            self.encoder_proc = None
            self.latest_keyframe = b""
            if not encoder_proc or encoder_proc.poll() is not None:
                return
            logger.info("Stopping screen capture: no active stream clients")
            encoder_proc.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(encoder_proc.wait), timeout=3)
            except asyncio.TimeoutError:
                encoder_proc.kill()
                await asyncio.to_thread(encoder_proc.wait)

    async def configure_encoder(self, width: int, height: int, fps: int, display_name: str = "", force: bool = False, track_request: bool = True, bitrate: int = 0):
        if not valid_stream_dimensions(width, height) or fps not in VALID_STREAM_FPS or display_name not in VALID_DISPLAY_NAMES:
            return False
        if bitrate:
            await self.set_bitrate(bitrate)
        if track_request:
            self.requested_display_name = display_name
        effective_display = self._effective_display_name()
        async with self.encoder_lock:
            if not force and (width, height, fps, effective_display) == (self.target_width, self.target_height, self.target_fps, self.target_display_name):
                return True
            self.target_width, self.target_height, self.target_fps = width, height, fps
            self.target_display_name = effective_display
            self.latest_keyframe = b""
            previous = self.encoder_proc
            self.encoder_proc = None
            if previous and previous.poll() is None:
                previous.terminate()
                try:
                    await asyncio.wait_for(asyncio.to_thread(previous.wait), timeout=3)
                except asyncio.TimeoutError:
                    previous.kill()
            await self.start_encoder()
            await self.broadcast_json({
                "type": "init",
                "codec": self.h264_codec,
                "width": width,
                "height": height,
                "fps": fps,
                "screenWidth": get_screen_dimensions()[0],
                "screenHeight": get_screen_dimensions()[1],
                "pixelWidth": TARGET_DISPLAY_PIXELS[0],
                "pixelHeight": TARGET_DISPLAY_PIXELS[1],
                "screenLocked": self.screen_locked,
                "bitrate": self.target_bitrate,
            })
            return True

    async def monitor_lock_state(self):
        if not self.follow_main_when_locked:
            return
        logger.info(
            "Lock-aware display routing enabled: requested=%r, locked=%s, active=%r",
            self.requested_display_name, self.screen_locked, self.target_display_name
        )
        while self.running:
            await asyncio.sleep(1)
            locked = is_screen_locked()
            if locked == self.screen_locked:
                continue
            self.screen_locked = locked
            next_display = self._effective_display_name()
            logger.info(
                "macOS lock state changed: locked=%s, switching capture %r -> %r",
                locked, self.target_display_name, next_display
            )
            await self.broadcast_json({
                "type": "status",
                "state": "host_locked" if locked else "host_unlocked",
                "message": "Mac заблокирован: показан основной дисплей для входа" if locked else "Mac разблокирован: возвращаю браузерный дисплей",
            })
            if self.clients:
                await self.configure_encoder(
                    self.target_width,
                    self.target_height,
                    self.target_fps,
                    self.requested_display_name,
                    force=True,
                    track_request=False,
                )
            else:
                self.target_display_name = next_display

    async def _start_unix_socket_server(self):
        sock_path = SOCKET_PATH
        try:
            if os.path.exists(sock_path):
                os.remove(sock_path)
        except Exception:
            pass

        async def handle_sock_client(reader, writer):
            logger.info("FlyDesktopCapture connected via Unix Domain Socket")
            while self.running:
                try:
                    len_bytes = await reader.readexactly(4)
                    payload_len = struct.unpack("!I", len_bytes)[0]
                    payload = await reader.readexactly(payload_len)
                    await self._handle_raw_packet(payload)
                except asyncio.IncompleteReadError:
                    break
                except Exception as e:
                    logger.error("Socket client error: %s", e)
                    break

        try:
            self.unix_server = await asyncio.start_unix_server(handle_sock_client, path=sock_path)
            os.chmod(sock_path, 0o777)
            logger.info("Unix socket frame server listening on %s", sock_path)
        except Exception as e:
            logger.warning("Could not start Unix socket server: %s", e)

    async def _handle_raw_packet(self, payload: bytes):
        if not payload:
            return
        metadata = parse_frame_metadata(payload)
        if metadata["frame_id"]:
            self.last_frame_id = metadata["frame_id"]
        else:
            self.last_frame_id += 1
            metadata["frame_id"] = self.last_frame_id
        if metadata["encode_start_ns"] and metadata["encode_done_ns"] and metadata["capture_pts_us"]:
            now_ns = time.monotonic_ns()
            if now_ns - self.last_frame_telemetry_ns >= 250_000_000:
                self.last_frame_telemetry_ns = now_ns
                capture_to_encode_ms = metadata["encode_start_ns"] / 1_000_000 - metadata["capture_pts_us"] / 1000
                encode_ms = (metadata["encode_done_ns"] - metadata["encode_start_ns"]) / 1_000_000
                if 0 <= capture_to_encode_ms < 10_000 and 0 <= encode_ms < 10_000:
                    await self.broadcast_json({
                        "type": "frame_telemetry",
                        "frameId": metadata["frame_id"],
                        "captureToEncodeMs": round(capture_to_encode_ms, 3),
                        "encodeMs": round(encode_ms, 3),
                    })

        if metadata["is_key"]:
            self.latest_keyframe = payload
            self.tcc_required = False
            detected_codec = detect_h264_codec(payload)
            if detected_codec and detected_codec != self.h264_codec:
                logger.info("Detected H.264 codec from SPS: %s -> %s", self.h264_codec, detected_codec)
                self.h264_codec = detected_codec
                await self.broadcast_json({"type": "codec", "codec": detected_codec})

        for state in list(self.clients.values()):
            self._queue_video(state, payload, metadata)

    async def _log_encoder_stderr(self, encoder_proc):
        loop = asyncio.get_running_loop()
        while self.running and encoder_proc.poll() is None:
            line = await loop.run_in_executor(None, encoder_proc.stderr.readline)
            if not line:
                break
            text = line.decode(errors="ignore").strip()
            logger.info("[Encoder] %s", text)
            if "-3801" in text or "declined TCCs" in text:
                self.tcc_required = True
                self.status_message = "Требуется разрешение «Запись экрана» в Системных настройках macOS"
                await self.broadcast_json({
                    "type": "status",
                    "state": "tcc_required",
                    "message": self.status_message
                })
            elif "Capture started" in text or "Found display" in text:
                self.tcc_required = False
                self.status_message = f"Захват экрана активен ({self.target_fps} FPS)"
                await self.broadcast_json({
                    "type": "status",
                    "state": "capturing",
                    "message": self.status_message
                })
            geometry = re.search(r"Display geometry id=(\d+) name=.* x=(-?\d+) y=(-?\d+) width=(\d+) height=(\d+)", text)
            if geometry:
                display_id = int(geometry.group(1))
                TARGET_DISPLAY_BOUNDS[:] = [float(value) for value in geometry.groups()[1:]]
                pixel_width = int(cg.CGDisplayPixelsWide(display_id))
                pixel_height = int(cg.CGDisplayPixelsHigh(display_id))
                if pixel_width > 0 and pixel_height > 0:
                    TARGET_DISPLAY_PIXELS[:] = [pixel_width, pixel_height]
                await self.broadcast_json({
                    "type": "display",
                    "screenWidth": int(TARGET_DISPLAY_BOUNDS[2]),
                    "screenHeight": int(TARGET_DISPLAY_BOUNDS[3]),
                    "pixelWidth": TARGET_DISPLAY_PIXELS[0],
                    "pixelHeight": TARGET_DISPLAY_PIXELS[1],
                })

    async def _read_encoder_frames(self, encoder_proc):
        loop = asyncio.get_running_loop()
        logger.info("Beginning encoder frame consumption loop...")
        while self.running and encoder_proc.poll() is None:
            try:
                len_bytes = await loop.run_in_executor(None, encoder_proc.stdout.read, 4)
                if not len_bytes or len(len_bytes) < 4:
                    if self.running and self.clients and self.encoder_proc is encoder_proc:
                        logger.warning("Encoder output ended, restarting in 2s...")
                        await asyncio.sleep(2)
                        if self.running and self.clients and self.encoder_proc is encoder_proc:
                            self.encoder_proc = None
                            await self.ensure_encoder_started()
                    break

                payload_len = struct.unpack("!I", len_bytes)[0]
                payload = await loop.run_in_executor(None, encoder_proc.stdout.read, payload_len)
                if not payload or len(payload) < payload_len:
                    continue

                await self._handle_raw_packet(payload)
            except Exception as e:
                logger.error("Error reading encoder frames: %s", e)
                await asyncio.sleep(0.5)

    def _is_control_owner(self, state: ClientState):
        return state.client_id == self.control_owner_id

    async def _announce_control_owner(self):
        for state in self.clients.values():
            self._enqueue_json(state, {
                "type": "control",
                "owner": self._is_control_owner(state),
                "ownerId": self.control_owner_id,
            })

    def _release_client_input(self, state: ClientState):
        for button in list(state.pressed_buttons):
            inject_mouse("up", state.last_x, state.last_y, button)
        state.pressed_buttons.clear()
        for code, (key, modifiers) in list(state.pressed_keys.items()):
            inject_key(code, key, False, modifiers)
        state.pressed_keys.clear()
        state.scroll_x = 0.0
        state.scroll_y = 0.0

    def _ack_input(self, state: ClientState, data: dict):
        seq = data.get("seq")
        if seq is None:
            return
        self._enqueue_json(state, {"type": "input_ack", "seq": seq, "afterFrameId": self.last_frame_id})

    async def handle_websocket(self, websocket):
        logger.info("Client connected to stream WebSocket: %s", websocket.remote_address)
        state = ClientState(websocket=websocket)
        self.clients[websocket] = state
        if self.control_owner_id is None:
            self.control_owner_id = state.client_id
        state.sender_task = asyncio.create_task(self._client_sender(state))
        await self.ensure_encoder_started()
        screen_w, screen_h = get_screen_dimensions()

        self._enqueue_json(state, {
            "type": "init",
            "codec": self.h264_codec,
            "width": self.target_width,
            "height": self.target_height,
            "fps": self.target_fps,
            "bitrate": self.target_bitrate,
            "screenWidth": screen_w,
            "screenHeight": screen_h,
            "pixelWidth": TARGET_DISPLAY_PIXELS[0],
            "pixelHeight": TARGET_DISPLAY_PIXELS[1],
            "screenLocked": self.screen_locked,
            "clientId": state.client_id,
            "canControl": self._is_control_owner(state),
        })
        # Старый keyframe намеренно не отправляется: новому клиенту нужна свежая точка входа.
        self.request_keyframe("new_client")
        await self._announce_control_owner()

        idle_guard = RemoteSessionIdleGuard(REMOTE_IDLE_TIMEOUT_SECONDS)
        try:
            while True:
                remaining = idle_guard.remaining()
                if remaining <= 0:
                    await websocket.close(code=4000, reason="remote desktop idle timeout")
                    logger.info("Remote desktop session closed after %ds of inactivity", REMOTE_IDLE_TIMEOUT_SECONDS)
                    break
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    await websocket.close(code=4000, reason="remote desktop idle timeout")
                    logger.info("Remote desktop session closed after %ds of inactivity", REMOTE_IDLE_TIMEOUT_SECONDS)
                    break
                except websockets.exceptions.ConnectionClosed:
                    break
                if not isinstance(message, str):
                    continue
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    if is_user_activity_message(msg_type):
                        idle_guard.mark_activity()
                    if msg_type == "bridge_hello":
                        state.media_bridge = True
                        idle_guard.mark_activity()
                        self._enqueue_json(state, {"type": "bridge_ready", "clientId": state.client_id})
                        continue
                    if msg_type == "bridge_keepalive" and state.media_bridge:
                        idle_guard.mark_activity()
                        continue
                    if msg_type == "probe":
                        self._enqueue_json(state, {"type": "probe_ack", "seq": data.get("seq"), "clientPerfMs": data.get("clientPerfMs")})
                        continue
                    if msg_type == "keyframe":
                        self.request_keyframe("client_request")
                        continue
                    if msg_type == "claim_control":
                        previous = next((item for item in self.clients.values() if item.client_id == self.control_owner_id), None)
                        if previous and previous is not state:
                            self._release_client_input(previous)
                        self.control_owner_id = state.client_id
                        await self._announce_control_owner()
                        continue
                    if msg_type == "reset_input":
                        self._release_client_input(state)
                        continue
                    if msg_type == "configure":
                        if self._is_control_owner(state):
                            await self.configure_encoder(
                                int(data.get("width", 0)),
                                int(data.get("height", 0)),
                                int(data.get("fps", 0)),
                                str(data.get("displayName", "")),
                                bool(data.get("force", False)),
                                bitrate=int(data.get("bitrate", 0) or 0),
                            )
                        else:
                            self._enqueue_json(state, {"type": "configure_ignored", "reason": "not_control_owner"})
                        continue
                    if msg_type == "bitrate":
                        if self._is_control_owner(state):
                            await self.set_bitrate(int(data.get("value", self.target_bitrate)))
                        continue
                    if not self._is_control_owner(state):
                        continue

                    seq = int(data.get("seq", 0) or 0)
                    delivery = str(data.get("delivery", "reliable"))
                    if delivery == "motion":
                        if seq and seq < state.last_reliable_seq:
                            continue
                    elif seq:
                        state.last_reliable_seq = max(state.last_reliable_seq, seq)

                    state.last_x = float(data.get("x", state.last_x))
                    state.last_y = float(data.get("y", state.last_y))
                    if msg_type == "mousemove":
                        drag_button = 0 if 0 in state.pressed_buttons else (2 if 2 in state.pressed_buttons else (next(iter(state.pressed_buttons)) if state.pressed_buttons else None))
                        inject_mouse("move", state.last_x, state.last_y, drag_button=drag_button)
                    elif msg_type == "mousedown":
                        button = int(data.get("button", 0))
                        state.pressed_buttons.add(button)
                        inject_mouse("down", state.last_x, state.last_y, button)
                        self._ack_input(state, data)
                    elif msg_type == "mouseup":
                        button = int(data.get("button", 0))
                        inject_mouse("up", state.last_x, state.last_y, button)
                        state.pressed_buttons.discard(button)
                        self._ack_input(state, data)
                    elif msg_type == "wheel":
                        state.scroll_x += float(data.get("dx", 0))
                        state.scroll_y += float(data.get("dy", 0))
                        dx = math.trunc(state.scroll_x)
                        dy = math.trunc(state.scroll_y)
                        state.scroll_x -= dx
                        state.scroll_y -= dy
                        if dx or dy:
                            inject_scroll(dx, dy)
                        self._ack_input(state, data)
                    elif msg_type == "keydown":
                        code = data.get("code", "")
                        key = data.get("key", "")
                        modifiers = data.get("modifiers")
                        state.pressed_keys[code] = (key, modifiers)
                        inject_key(code, key, True, modifiers)
                        self._ack_input(state, data)
                    elif msg_type == "keyup":
                        code = data.get("code", "")
                        inject_key(code, data.get("key", ""), False, data.get("modifiers"))
                        state.pressed_keys.pop(code, None)
                        self._ack_input(state, data)
                    elif msg_type == "text":
                        inject_text(str(data.get("text", "")))
                        self._ack_input(state, data)
                    elif msg_type == "clipboard":
                        await asyncio.to_thread(inject_clipboard, str(data.get("text", "")))
                        self._ack_input(state, data)
                except Exception as err:
                    logger.warning("Error processing client input: %s", err)
        finally:
            self._release_client_input(state)
            self.clients.pop(websocket, None)
            if state.sender_task:
                state.sender_task.cancel()
            if self.control_owner_id == state.client_id:
                self.control_owner_id = next((item.client_id for item in self.clients.values()), None)
                await self._announce_control_owner()
            logger.info("Client disconnected from stream WebSocket")
            await self.stop_encoder_if_idle()


async def main():
    server = StreamServer()
    server.running = True
    lock_monitor = asyncio.create_task(server.monitor_lock_state())

    ws_server = await websockets.serve(
        server.handle_websocket,
        "127.0.0.1",
        PORT,
        max_size=20 * 1024 * 1024,
        ping_interval=15,
        ping_timeout=20
    )
    logger.info("Mac H.264 Stream Server listening on ws://127.0.0.1:%d", PORT)

    try:
        await asyncio.Future()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        server.running = False
        lock_monitor.cancel()
        if server.encoder_proc:
            server.encoder_proc.terminate()
        if server.unix_server:
            server.unix_server.close()
            await server.unix_server.wait_closed()
        ws_server.close()
        await ws_server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
