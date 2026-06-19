#!/usr/bin/env python3
"""
Patch Selkies keyboard input so Cyrillic text is injected as ordered text, not
as independent keydown/keyup events.

The linuxserver Chromium image currently runs Selkies on X11. Newer Selkies
routes alphabetic printable input through pynput or xdotool key events; for
Cyrillic this can race under fast typing and characters are dropped. The patch
keeps shortcuts and Latin key events intact, but batches Cyrillic characters
and sends each batch with one `xdotool type` call.
"""

import os
import py_compile
import re
import sys
from pathlib import Path


PATCH_MARKER = "fly-terminal-cyrillic-batch-input-v2"
LEGACY_MARKER = "/tmp/fly-terminal-selkies-xtest-patched"
MARKER = "/tmp/fly-terminal-selkies-cyrillic-batch-v2"

SEARCH_PATHS = [
    "/lsiopy/lib/python3.13/site-packages/selkies/input_handler.py",
    "/lsiopy/lib/python3.12/site-packages/selkies/input_handler.py",
    "/lsiopy/lib/python3.11/site-packages/selkies/input_handler.py",
    "/lsiopy/lib64/python3.13/site-packages/selkies/input_handler.py",
    "/lsiopy/lib64/python3.12/site-packages/selkies/input_handler.py",
    "/lsiopy/lib64/python3.11/site-packages/selkies/input_handler.py",
    "/usr/local/lib/python3.13/dist-packages/selkies/input_handler.py",
    "/usr/local/lib/python3.12/dist-packages/selkies/input_handler.py",
    "/usr/local/lib/python3.11/dist-packages/selkies/input_handler.py",
    "/usr/lib/python3/dist-packages/selkies/input_handler.py",
    "/usr/local/lib/python3.11/dist-packages/selkies_gstreamer/webrtc_input.py",
    "/usr/lib/python3/dist-packages/selkies_gstreamer/webrtc_input.py",
]


HELPERS = f'''
## {PATCH_MARKER}: helpers ##
def _fly_terminal_is_cyrillic_char(ch):
    if not ch:
        return False
    cp = ord(ch[0])
    return (
        0x0400 <= cp <= 0x04FF or
        0x0500 <= cp <= 0x052F or
        0x2DE0 <= cp <= 0x2DFF or
        0xA640 <= cp <= 0xA69F
    )


def _fly_terminal_keysym_to_cyrillic_text(keysym):
    candidates = []

    if (keysym & 0xFF000000) == 0x01000000:
        cp = keysym & 0x00FFFFFF
        if 0 <= cp <= 0x10FFFF:
            try:
                candidates.append(chr(cp))
            except ValueError:
                pass
    elif 0x0400 <= keysym <= 0x04FF or 0x0500 <= keysym <= 0x052F:
        try:
            candidates.append(chr(keysym))
        except ValueError:
            pass

    if libxkb is not None:
        try:
            buf = ctypes.create_string_buffer(16)
            result = libxkb.xkb_keysym_to_utf8(keysym, buf, 16)
            if result > 0:
                candidates.append(buf.value.decode("utf-8"))
        except Exception:
            pass

    if XK is not None:
        try:
            value = XK.keysym_to_string(keysym)
            if value:
                candidates.append(value)
        except Exception:
            pass

    for value in candidates:
        if len(value) == 1 and _fly_terminal_is_cyrillic_char(value):
            return value
    return None
## end {PATCH_MARKER}: helpers ##
'''


X11_TYPE_METHOD = f'''
    ## {PATCH_MARKER}: x11 text batching ##
    async def _fly_terminal_type_text_x11(self, text_to_type):
        if not text_to_type:
            return

        currently_active_mods = list(self.active_modifiers)

        try:
            for mod_keysym in currently_active_mods:
                await self.send_x11_keypress(mod_keysym, down=False)

            process = await subprocess.create_subprocess_exec(
                "xdotool", "type", "--clearmodifiers", "--delay", "1", "--", text_to_type,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            timeout = max(1.0, min(5.0, 0.03 * len(text_to_type) + 1.0))
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            if process.returncode == 0:
                return

            logger_webrtc_input.warning(
                "Batched xdotool Cyrillic input failed: %s",
                stderr.decode("utf-8", "replace").strip(),
            )
            await self._inject_unicode_via_clipboard(text_to_type)
        except Exception as e:
            logger_webrtc_input.warning(f"Batched xdotool Cyrillic input failed: {{e}}")
            await self._inject_unicode_via_clipboard(text_to_type)
        finally:
            for mod_keysym in currently_active_mods:
                if mod_keysym in self.active_modifiers:
                    await self.send_x11_keypress(mod_keysym, down=True)
    ## end {PATCH_MARKER}: x11 text batching ##
'''


def unique_existing_paths():
    seen = set()
    for raw_path in SEARCH_PATHS:
        path = Path(raw_path)
        if not path.is_file():
            continue
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        yield path


def find_dict_insert_point(src):
    anchor = "CYRILLIC_TO_QWERTY_KEYSYM = {"
    start = src.find(anchor)
    if start < 0:
        return -1

    depth = 0
    for idx in range(start, len(src)):
        char = src[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return src.find("\n", idx)
    return -1


def patch_helpers(src):
    if f"## {PATCH_MARKER}: helpers ##" in src:
        return src, False

    insert_at = find_dict_insert_point(src)
    if insert_at < 0:
        raise RuntimeError("CYRILLIC_TO_QWERTY_KEYSYM anchor not found")

    return src[:insert_at] + "\n" + HELPERS + src[insert_at:], True


def patch_init(src):
    old = "        self.keyboard_queue = asyncio.Queue()\n        self.keyboard_worker_task = None\n"
    new = (
        "        self.keyboard_queue = asyncio.Queue()\n"
        "        self.keyboard_worker_task = None\n"
        f"        self.fly_terminal_cyrillic_batch_input = True  # {PATCH_MARKER}\n"
    )
    if f"self.fly_terminal_cyrillic_batch_input = True  # {PATCH_MARKER}" in src:
        return src, False
    if old not in src:
        raise RuntimeError("keyboard queue initializer anchor not found")
    return src.replace(old, new, 1), True


def patch_connect(src):
    old = (
        "        if self.is_wayland:\n"
        "            self.keyboard_worker_task = asyncio.create_task(self._keyboard_worker())        \n"
    )
    new = (
        "        if self.is_wayland or getattr(self, 'fly_terminal_cyrillic_batch_input', False):\n"
        "            self.keyboard_worker_task = asyncio.create_task(self._keyboard_worker())        \n"
    )
    if "if self.is_wayland or getattr(self, 'fly_terminal_cyrillic_batch_input', False):" in src:
        return src, False
    if old not in src:
        raise RuntimeError("keyboard worker startup anchor not found")
    return src.replace(old, new, 1), True


def patch_keyboard_worker_flush(src):
    if f"await self._fly_terminal_type_text_x11(combined_text)" in src:
        return src, False

    old = '''                if getattr(self, 'use_clipboard_fallback', False):
                    await self._inject_unicode_via_clipboard(combined_text)
                else:
                    try:
                        cmd = ["wtype", "--", combined_text]
                        proc = await subprocess.create_subprocess_exec(
                            *cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            env=self._get_wl_env()
                        )
                        await asyncio.wait_for(proc.communicate(), timeout=2.0)
                    except Exception as e:
                        logger_webrtc_input.warning(f"Batched wtype failed: {e}")'''

    new = '''                if self.is_wayland:
                    if getattr(self, 'use_clipboard_fallback', False):
                        await self._inject_unicode_via_clipboard(combined_text)
                    else:
                        try:
                            cmd = ["wtype", "--", combined_text]
                            proc = await subprocess.create_subprocess_exec(
                                *cmd,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                env=self._get_wl_env()
                            )
                            await asyncio.wait_for(proc.communicate(), timeout=2.0)
                        except Exception as e:
                            logger_webrtc_input.warning(f"Batched wtype failed: {e}")
                else:
                    await self._fly_terminal_type_text_x11(combined_text)'''

    if old not in src:
        raise RuntimeError("keyboard worker flush anchor not found")
    return src.replace(old, new, 1), True


def patch_keyboard_worker_text_message(src):
    if 'elif msg_type == "text":\n                        unicode_buffer.append(data)' in src:
        return src, False

    old = '''                    elif msg_type == "co_end":
                        unicode_buffer.append(data)'''
    new = '''                    elif msg_type == "co_end":
                        unicode_buffer.append(data)

                    elif msg_type == "text":
                        unicode_buffer.append(data)'''

    if old not in src:
        raise RuntimeError("keyboard worker co_end anchor not found")
    return src.replace(old, new, 1), True


def patch_x11_type_method(src):
    if f"## {PATCH_MARKER}: x11 text batching ##" in src:
        return src, False

    anchor = "    async def _keyboard_worker(self):\n"
    idx = src.find(anchor)
    if idx < 0:
        raise RuntimeError("_keyboard_worker anchor not found")
    return src[:idx] + X11_TYPE_METHOD + "\n" + src[idx:], True


def patch_on_message_keydown(src):
    if "cyrillic_text = _fly_terminal_keysym_to_cyrillic_text(keysym)" in src:
        return src, False

    old = '''            else:
                is_printable = (0x20 <= keysym <= 0xFF) or ((keysym & 0xFF000000) == 0x01000000)
                if keysym in self.MODIFIER_KEYSYMS:
                    self.active_modifiers.add(keysym)
                if is_printable and not self.active_modifiers:
                    unicode_codepoint = keysym & 0x00FFFFFF if (keysym & 0xFF000000) == 0x01000000 else keysym
                    try:
                        char_to_type = chr(unicode_codepoint)
                        if not char_to_type.isalpha() and char_to_type != ' ':
                            await self.on_message(f"co,end,{char_to_type}")
                            self.atomically_typed_keys.add(keysym)
                        else:
                            await self.send_x11_keypress(keysym, down=True)
                    except (ValueError, TypeError):
                        await self.send_x11_keypress(keysym, down=True)
                else:
                    await self.send_x11_keypress(keysym, down=True)'''

    new = '''            else:
                is_printable = (0x20 <= keysym <= 0xFF) or ((keysym & 0xFF000000) == 0x01000000)
                if keysym in self.MODIFIER_KEYSYMS:
                    self.active_modifiers.add(keysym)

                cyrillic_text = None
                if not (self.active_modifiers & self.ACTION_MODIFIER_KEYSYMS):
                    cyrillic_text = _fly_terminal_keysym_to_cyrillic_text(keysym)

                if cyrillic_text:
                    self.keyboard_queue.put_nowait(("text", cyrillic_text))
                    self.atomically_typed_keys.add(keysym)
                elif keysym == 65288:
                    self.keyboard_queue.put_nowait(("kd", keysym))
                elif is_printable and not self.active_modifiers:
                    unicode_codepoint = keysym & 0x00FFFFFF if (keysym & 0xFF000000) == 0x01000000 else keysym
                    try:
                        char_to_type = chr(unicode_codepoint)
                        if not char_to_type.isalpha() and char_to_type != ' ':
                            await self.on_message(f"co,end,{char_to_type}")
                            self.atomically_typed_keys.add(keysym)
                        else:
                            await self.send_x11_keypress(keysym, down=True)
                    except (ValueError, TypeError):
                        await self.send_x11_keypress(keysym, down=True)
                else:
                    await self.send_x11_keypress(keysym, down=True)'''

    if old not in src:
        raise RuntimeError("X11 keydown branch anchor not found")
    return src.replace(old, new, 1), True


def patch_on_message_keyup(src):
    if 'elif keysym == 65288:\n                    self.keyboard_queue.put_nowait(("ku", keysym))' in src:
        return src, False

    old = '''                if keysym in self.atomically_typed_keys:
                    self.atomically_typed_keys.discard(keysym)
                    pass
                else:
                    await self.send_x11_keypress(keysym, down=False)'''
    new = '''                if keysym in self.atomically_typed_keys:
                    self.atomically_typed_keys.discard(keysym)
                    pass
                elif keysym == 65288:
                    self.keyboard_queue.put_nowait(("ku", keysym))
                else:
                    await self.send_x11_keypress(keysym, down=False)'''

    if old not in src:
        raise RuntimeError("X11 keyup branch anchor not found")
    return src.replace(old, new, 1), True


def patch_co_end(src):
    if 'self.keyboard_queue.put_nowait(("co_end", text_to_type))\n                else:\n                    self.keyboard_queue.put_nowait(("co_end", text_to_type))' in src:
        return src, False

    old = '''                if self.is_wayland:
                    self.keyboard_queue.put_nowait(("co_end", text_to_type))
                else:
                    cmd = ["xdotool", "type", text_to_type]
                    process = await subprocess.create_subprocess_exec(
                        *cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    await asyncio.wait_for(process.communicate(), timeout=0.5)'''
    new = '''                if self.is_wayland:
                    self.keyboard_queue.put_nowait(("co_end", text_to_type))
                else:
                    self.keyboard_queue.put_nowait(("co_end", text_to_type))'''

    if old not in src:
        raise RuntimeError("co,end branch anchor not found")
    return src.replace(old, new, 1), True


def validate_source(path, src):
    tmp = path.with_suffix(path.suffix + ".validate")
    tmp.write_text(src)
    try:
        py_compile.compile(str(tmp), doraise=True)
    finally:
        tmp.unlink(missing_ok=True)


def patch_file(path):
    src = path.read_text()
    original = src

    patchers = [
        patch_helpers,
        patch_init,
        patch_connect,
        patch_keyboard_worker_flush,
        patch_keyboard_worker_text_message,
        patch_x11_type_method,
        patch_on_message_keydown,
        patch_on_message_keyup,
        patch_co_end,
    ]

    changes = []
    for patcher in patchers:
        src, changed = patcher(src)
        if changed:
            changes.append(patcher.__name__)

    if src == original:
        print(f"{path}: already patched")
        return True

    try:
        validate_source(path, src)
    except py_compile.PyCompileError as exc:
        print(f"{path}: syntax validation failed: {exc}", file=sys.stderr)
        return False

    backup = path.with_suffix(path.suffix + ".fly-terminal-bak")
    if not backup.exists():
        backup.write_text(original)
    path.write_text(src)
    print(f"{path}: patched {', '.join(changes)}")
    return True


def main():
    paths = list(unique_existing_paths())
    if not paths:
        print("Selkies input handler not found.", file=sys.stderr)
        return 0

    ok = True
    for path in paths:
        try:
            ok = patch_file(path) and ok
        except Exception as exc:
            print(f"{path}: patch failed: {exc}", file=sys.stderr)
            ok = False

    if ok:
        Path(MARKER).write_text("ok\n")
        # Keep the legacy marker for older launch scripts/log readers, but never
        # trust it as the idempotency condition.
        Path(LEGACY_MARKER).write_text("ok\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
