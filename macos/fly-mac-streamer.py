#!/usr/bin/env python3
import asyncio
import ctypes
import ctypes.util
import json
import logging
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Set

import websockets
from aiohttp import web

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
VALID_STREAM_FPS = {15, 30, 45, 60}
VALID_DISPLAY_NAMES = {"", "Fly Remote"}
TARGET_DISPLAY_BOUNDS = [0.0, 0.0, 2560.0, 1440.0]
TARGET_DISPLAY_PIXELS = [2560, 1440]

# MARK: - CoreGraphics & AppKit ctypes setup

cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))
cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
appkit = ctypes.cdll.LoadLibrary(ctypes.util.find_library("AppKit"))

class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

class CGRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("w", ctypes.c_double), ("h", ctypes.c_double)]

cg.CGMainDisplayID.restype = ctypes.c_uint32
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


def valid_stream_dimensions(width: int, height: int):
    return (
        640 <= width <= 7680
        and 360 <= height <= 4320
        and width % 2 == 0
        and height % 2 == 0
    )


def inject_mouse(event_type: str, x_norm: float, y_norm: float, button: int = 0):
    screen_w, screen_h = get_screen_dimensions()
    x = TARGET_DISPLAY_BOUNDS[0] + max(0.0, min(float(screen_w), x_norm * screen_w))
    y = TARGET_DISPLAY_BOUNDS[1] + max(0.0, min(float(screen_h), y_norm * screen_h))
    pos = CGPoint(x, y)

    if event_type == "move":
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


def inject_scroll(dx: float, dy: float):
    # dx, dy in pixels
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
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(text.encode("utf-8"))
        # Simulate Cmd+V
        inject_key("KeyV", "v", True, {"meta": True})
        time.sleep(0.02)
        inject_key("KeyV", "v", False, {"meta": True})
    except Exception as e:
        logger.warning("Clipboard injection error: %s", e)


# MARK: - Server & Encoder Orchestration

class StreamServer:
    def __init__(self):
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        self.latest_keyframe: bytes = b""
        self.encoder_proc: subprocess.Popen = None
        self.running = False
        self.tcc_required = False
        self.status_message = "Инициализация захвата экрана..."
        self.target_width = TARGET_WIDTH
        self.target_height = TARGET_HEIGHT
        self.target_fps = TARGET_FPS
        self.target_display_name = os.environ.get("FLY_STREAMER_DISPLAY_NAME", "")
        self.encoder_lock = asyncio.Lock()

    async def broadcast_json(self, msg: dict):
        if not self.clients:
            return
        payload = json.dumps(msg)
        dead = set()
        for client in list(self.clients):
            try:
                await client.send(payload)
            except Exception:
                dead.add(client)
        self.clients.difference_update(dead)

    async def start_encoder(self):
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

        logger.info("Initializing Unix socket server...")
        await self._start_unix_socket_server()

        encoder_env = os.environ.copy()
        encoder_env.update({
            "FLY_STREAMER_WIDTH": str(self.target_width),
            "FLY_STREAMER_HEIGHT": str(self.target_height),
            "FLY_STREAMER_FPS": str(self.target_fps),
            "FLY_STREAMER_DISPLAY_NAME": self.target_display_name,
        })
        logger.info(
            "Starting fly-mac-encoder subprocess: %s (%dx%d @ %d FPS)",
            ENCODER_BIN, self.target_width, self.target_height, self.target_fps,
        )
        encoder_proc = subprocess.Popen(
            [str(ENCODER_BIN)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=encoder_env,
        )
        self.encoder_proc = encoder_proc

        loop = asyncio.get_running_loop()
        loop.create_task(self._read_encoder_frames(encoder_proc))
        loop.create_task(self._log_encoder_stderr(encoder_proc))

    async def configure_encoder(self, width: int, height: int, fps: int, display_name: str = "", force: bool = False):
        if not valid_stream_dimensions(width, height) or fps not in VALID_STREAM_FPS or display_name not in VALID_DISPLAY_NAMES:
            return False
        async with self.encoder_lock:
            if not force and (width, height, fps, display_name) == (self.target_width, self.target_height, self.target_fps, self.target_display_name):
                return True
            self.target_width, self.target_height, self.target_fps = width, height, fps
            self.target_display_name = display_name
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
                "codec": "avc1.42E01F",
                "width": width,
                "height": height,
                "fps": fps,
                "screenWidth": get_screen_dimensions()[0],
                "screenHeight": get_screen_dimensions()[1],
                "pixelWidth": TARGET_DISPLAY_PIXELS[0],
                "pixelHeight": TARGET_DISPLAY_PIXELS[1],
            })
            return True

    async def _start_unix_socket_server(self):
        sock_path = "/tmp/fly-mac-stream.sock"
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
            server = await asyncio.start_unix_server(handle_sock_client, path=sock_path)
            os.chmod(sock_path, 0o777)
            logger.info("Unix socket frame server listening on %s", sock_path)
        except Exception as e:
            logger.warning("Could not start Unix socket server: %s", e)

    async def _handle_raw_packet(self, payload: bytes):
        if not payload:
            return
        flags = payload[0]
        is_key = bool(flags & 1)
        if is_key:
            self.latest_keyframe = payload
            self.tcc_required = False

        if self.clients:
            dead_clients = set()
            for client in list(self.clients):
                try:
                    await client.send(payload)
                except Exception:
                    dead_clients.add(client)
            self.clients.difference_update(dead_clients)

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
                    if self.running and self.encoder_proc is encoder_proc:
                        logger.warning("Encoder output ended, restarting in 2s...")
                        await asyncio.sleep(2)
                        if self.running and self.encoder_proc is encoder_proc:
                            await self.start_encoder()
                    break

                payload_len = struct.unpack("!I", len_bytes)[0]
                payload = await loop.run_in_executor(None, encoder_proc.stdout.read, payload_len)
                if not payload or len(payload) < payload_len:
                    continue

                await self._handle_raw_packet(payload)
            except Exception as e:
                logger.error("Error reading encoder frames: %s", e)
                await asyncio.sleep(0.5)

    async def handle_websocket(self, websocket):
        logger.info("Client connected to stream WebSocket: %s", websocket.remote_address)
        self.clients.add(websocket)
        screen_w, screen_h = get_screen_dimensions()

        # Send Init metadata JSON
        init_payload = {
            "type": "init",
            "codec": "avc1.42E01F",
            "width": self.target_width,
            "height": self.target_height,
            "fps": self.target_fps,
            "screenWidth": screen_w,
            "screenHeight": screen_h,
            "pixelWidth": TARGET_DISPLAY_PIXELS[0],
            "pixelHeight": TARGET_DISPLAY_PIXELS[1],
        }
        await websocket.send(json.dumps(init_payload))

        if self.latest_keyframe:
            try:
                await websocket.send(self.latest_keyframe)
            except Exception:
                pass

        # Immediately send latest keyframe so client can start decoding with 0ms delay
        if self.latest_keyframe:
            try:
                await websocket.send(self.latest_keyframe)
            except Exception:
                pass

        try:
            async for message in websocket:
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                        msg_type = data.get("type")
                        if msg_type == "configure":
                            await self.configure_encoder(
                                int(data.get("width", 0)),
                                int(data.get("height", 0)),
                                int(data.get("fps", 0)),
                                str(data.get("displayName", "")),
                                bool(data.get("force", False)),
                            )
                        elif msg_type == "mousemove":
                            inject_mouse("move", data.get("x", 0), data.get("y", 0))
                        elif msg_type == "mousedown":
                            inject_mouse("down", data.get("x", 0), data.get("y", 0), data.get("button", 0))
                        elif msg_type == "mouseup":
                            inject_mouse("up", data.get("x", 0), data.get("y", 0), data.get("button", 0))
                        elif msg_type == "wheel":
                            inject_scroll(data.get("dx", 0), data.get("dy", 0))
                        elif msg_type == "keydown":
                            inject_key(data.get("code", ""), data.get("key", ""), True, data.get("modifiers"))
                        elif msg_type == "keyup":
                            inject_key(data.get("code", ""), data.get("key", ""), False, data.get("modifiers"))
                        elif msg_type == "clipboard":
                            inject_clipboard(data.get("text", ""))
                    except Exception as err:
                        logger.warning("Error processing client input: %s", err)
        finally:
            self.clients.discard(websocket)
            logger.info("Client disconnected from stream WebSocket")


async def main():
    server = StreamServer()
    server.running = True
    await server.start_encoder()

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
        if server.encoder_proc:
            server.encoder_proc.terminate()
        ws_server.close()
        await ws_server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
