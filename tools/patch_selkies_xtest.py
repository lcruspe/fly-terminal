#!/usr/bin/env python3
"""
Patches Selkies input_handler.py to eliminate Cyrillic character loss.

Problem:
  English: XTEST fast-path works (keysym_to_keycode maps to keycodes) → instant
  Cyrillic: XTEST fails (US X11 layout, keysym_to_keycode returns 0) → falls
            to xdotool keydown + keyup subprocess (10-50ms per call, 2 per char)
            → characters dropped during fast typing

Fix:
  Latin chars: XTEST fast-path (already patched, no subprocess)
  Cyrillic 'kd': use xdotool type --clearmodifiers <char> (1 subprocess per char)
                 instead of send_x11_keypress (2 subprocesses per char)
  Add to atomically_typed_keys → 'ku' handler skips the keyup automatically

Usage:
  docker cp tools/patch_selkies_xtest.py <container>:/tmp/
  docker exec -u root <container> python3 /tmp/patch_selkies_xtest.py
"""

import os, sys, re, py_compile

MARKER = "/tmp/fly-terminal-selkies-xtest-patched"
FP = None

for p in [
    "/lsiopy/lib/python3.13/site-packages/selkies/input_handler.py",
    "/lsiopy/lib/python3.12/site-packages/selkies/input_handler.py",
    "/lsiopy/lib/python3.11/site-packages/selkies/input_handler.py",
    "/usr/local/lib/python3.13/dist-packages/selkies/input_handler.py",
    "/usr/lib/python3/dist-packages/selkies/input_handler.py",
    "/usr/local/lib/python3.11/dist-packages/selkies_gstreamer/webrtc_input.py",
    "/usr/lib/python3/dist-packages/selkies_gstreamer/webrtc_input.py",
]:
    if os.path.isfile(p):
        FP = p
        break

if not FP:
    print("Selkies input handler not found.", file=sys.stderr)
    sys.exit(0)

# Inline Cyrillic check — will be added to input_handler.py
CYRILLIC_CHECK_FUNC = """
## fly-terminal: cyrillic check helper ##
def _is_cyr(ks):
    return 0x0400 <= ks <= 0x04FF or 0x0500 <= ks <= 0x052F or 0x2DE0 <= ks <= 0x2DFF or 0xA640 <= ks <= 0xA69F
"""

# XTEST fast-path template for Latin characters
XTEST_PRESS = """\
## fly-terminal: xtest fast-path ##
if hasattr(self, 'xdisplay') and self.xdisplay:
    try:
        from Xlib.ext import xtest as _xt
        import Xlib as _Xl
        _kc = self.xdisplay.keysym_to_keycode({ks})
        if _kc:
            _xt.fake_input(self.xdisplay, _Xl.KeyPress if {d} else _Xl.KeyRelease, _kc)
            self.xdisplay.sync()
            return
    except Exception:
        pass
## fallback: xdotool subprocess ##"""

# Cyrillic kd handler — single xdotool type call instead of send_x11_keypress
CYRILLIC_KD = """\
## fly-terminal: cyrillic kd -> xdotool type ##
            if _is_cyr(keysym):
                try:
                    _cp = keysym & 0xFFFFFF if (keysym & 0xFF000000) == 0x01000000 else keysym
                    _ch = chr(_cp)
                    self.atomically_typed_keys.add(keysym)
                    _proc = await subprocess.create_subprocess_exec(
                        "xdotool", "type", "--clearmodifiers", _ch,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    await asyncio.wait_for(_proc.communicate(), timeout=0.5)
                except Exception:
                    await self.send_x11_keypress(keysym, down=True)
            else"""


def patch():
    if os.path.exists(MARKER):
        print("Already patched.")
        return True

    with open(FP) as f:
        src = f.read()
    original = src

    # 1. Add _is_cyr helper function — insert after CYRILLIC_TO_QWERTY_KEYSYM dict
    mark = "CYRILLIC_TO_QWERTY_KEYSYM = {"
    idx = src.find(mark)
    if idx == -1:
        print("Cannot find CYRILLIC_TO_QWERTY_KEYSYM anchor")
        return False
    # Find the end of the dict
    dict_end = src.find("}", idx)
    if dict_end == -1:
        return False
    insert_point = src.find("\n", dict_end)
    if insert_point == -1:
        return False
    src = src[:insert_point] + "\n" + CYRILLIC_CHECK_FUNC + src[insert_point:]
    changed_1 = True

    # 2. Add XTEST before each xdotool keydown/keyup subprocess
    # Replace standalone xdotool command blocks
    lines = src.split("\n")
    new_lines = []
    i = 0
    changed_2 = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # XTEST for: command = ["xdotool", "keydown"/"keyup"/"key", ...]
        m = re.match(r'^(\s*)(?:command|proc|process)\s*=\s*\["xdotool",\s*("(?:keydown|keyup|key)")', stripped)
        if m and "## fly-terminal" not in line:
            indent = m.group(1)
            action = m.group(2)
            down_val = "True" if '"keydown"' in action or '"key"' in action else "False"

            # Find end of subprocess block
            j = i + 1
            while j < len(lines) and "communicate(" not in lines[j]:
                j += 1
            if j < len(lines):
                j += 1
            while j < len(lines) and re.match(r'^\s*(except|pass|continue|else:|logger_|#)', lines[j]):
                j += 1

            xtest = XTEST_PRESS.format(ks="keysym", d=down_val)
            new_lines.append(xtest)
            new_lines.extend(lines[i:j])
            changed_2 = True
            i = j
            continue

        # XTEST for: await self._xdotool_fallback(...)
        m = re.match(r'^(\s*)await\s+self\._xdotool_fallback\(', stripped)
        if m and "## fly-terminal" not in line:
            indent = m.group(1)
            args_str = line[line.index("_xdotool_fallback(") + len("_xdotool_fallback("):line.rindex(")")]
            args = [a.strip() for a in args_str.split(",")]
            ks_var = args[0] if len(args) > 0 else "keysym"
            d_var = args[1] if len(args) > 1 else "down"

            xtest = f"""\
{indent}## fly-terminal: xtest fast-path ##
{indent}if hasattr(self, 'xdisplay') and self.xdisplay:
{indent}    try:
{indent}        from Xlib.ext import xtest as _xt
{indent}        import Xlib as _Xl
{indent}        _kc = self.xdisplay.keysym_to_keycode({ks_var})
{indent}        if _kc:
{indent}            _xt.fake_input(self.xdisplay, _Xl.KeyPress if {d_var} else _Xl.KeyRelease, _kc)
{indent}            self.xdisplay.sync()
{indent}            return
{indent}    except Exception:
{indent}        pass
{indent}## fallback: _xdotool_fallback ##"""
            new_lines.append(xtest)
            new_lines.append(line)
            changed_2 = True
            i += 1
            continue

        new_lines.append(line)
        i += 1

    if not changed_2:
        print("No xdotool calls found to patch with XTEST")
        # Still continue — the Cyrillic fix is the important part
    else:
        src = "\n".join(new_lines)

    # 3. Add Cyrillic interception in on_message 'kd' handler
    # Find the specific line in on_message that calls send_x11_keypress for non-printable keys
    # Pattern: in the 'else:' path: await self.send_x11_keypress(keysym, down=True)
    # But we need to target the ONE in on_message, not the one in send_x11_keypress itself
    
    # Better approach: find lines like: await self.send_x11_keypress(keysym, down=True)
    # and check if they're in on_message by looking at surrounding context
    
    lines = src.split("\n")
    new_lines2 = []
    i = 0
    changed_3 = False
    
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Find: await self.send_x11_keypress(keysym, down=True) in on_message context
        m = re.match(r'^(\s*)await\s+self\.send_x11_keypress\(keysym,\s*down=True\)', stripped)
        if m and "## fly-terminal" not in line:
            indent = m.group(1)
            # Check if this is inside on_message by looking at context
            ctx_start = max(0, i - 8)
            ctx = "\n".join(lines[ctx_start:i])
            
            # on_message kd handler has: keysym = ...
            # We need to identify the SECOND send_x11_keypress call (for non-printable)
            # The first one is for printable alpha chars, the second for non-printable
            # Both need Cyrillic handling, so we wrap both
            
            # Check context clues
            is_on_msg = any(x in ctx for x in ["active_modifiers", "is_printable", "char_to_type", 'msg_type == "kd"'])
            
            if is_on_msg:
                # This is in on_message — add Cyrillic kd interception
                cyr_block = f"""\
{indent}## fly-terminal: cyrillic kd -> xdotool type ##
{indent}if _is_cyr(keysym):
{indent}    try:
{indent}        _cp = keysym & 0xFFFFFF if (keysym & 0xFF000000) == 0x01000000 else keysym
{indent}        _ch = chr(_cp)
{indent}        self.atomically_typed_keys.add(keysym)
{indent}        _p = await subprocess.create_subprocess_exec(
{indent}            "xdotool", "type", "--clearmodifiers", _ch,
{indent}            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
{indent}        await asyncio.wait_for(_p.communicate(), timeout=0.5)
{indent}    except Exception:
{indent}        await self.send_x11_keypress(keysym, down=True)
{indent}else:
{indent}    await self.send_x11_keypress(keysym, down=True)"""
                new_lines2.append(cyr_block)
                changed_3 = True
                i += 1
                continue
        
        new_lines2.append(line)
        i += 1

    if not changed_3:
        print("Warning: Could not add Cyrillic interception to on_message")
        # Still apply other changes if any
    
    src = "\n".join(new_lines2)
    
    if not (changed_1 or changed_2 or changed_3):
        print("No changes made.")
        return True
    
    # Validate syntax
    tmp = FP + ".validate"
    try:
        with open(tmp, "w") as f:
            f.write(src)
        py_compile.compile(tmp, doraise=True)
        os.unlink(tmp)
    except py_compile.PyCompileError as e:
        os.unlink(tmp)
        print(f"SYNTAX ERROR - rolled back: {e}", file=sys.stderr)
        ln = 0
        if "line " in str(e):
            try: ln = int(str(e).split("line ")[1].split(",")[0])
            except: pass
        if ln:
            ctxt = src.split("\n")
            start = max(0, ln - 5)
            end = min(len(ctxt), ln + 3)
            for n in range(start, end):
                m = ">>>" if n == ln - 1 else "   "
                print(f"  {m} {n+1}: {ctxt[n]}", file=sys.stderr)
        with open(FP, "w") as f:
            f.write(original)
        return False

    with open(FP, "w") as f:
        f.write(src)
    open(MARKER, "w").close()
    print(f"Patched {FP}: Latin=XTEST, Cyrillic=single xdotool type")
    return True


if __name__ == "__main__":
    sys.exit(0 if patch() else 1)
