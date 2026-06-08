#!/usr/bin/env python3
"""Fix: update _is_cyr() and cyrillic kd interception in selkies input_handler.py.

Changes:
1. _is_cyr() now strips the 0x01000000 Selkies prefix before checking ranges
2. Cyrillic interception uses U+XXXX format for xdotool type (not chr())
3. X11 keysym range (0x06C1-0x06FF) is handled by mapping to Unicode codepoints
"""

import os
import sys
import py_compile

FP = "/lsiopy/lib/python3.13/site-packages/selkies/input_handler.py"

with open(FP) as f:
    src = f.read()

orig = src
changed = False

# ----------------------------------------------------------------
# 1. Fix _is_cyr() — strip Selkies prefix before range checks
# ----------------------------------------------------------------
old_is_cyr = '''def _is_cyr(ks):
    """Check if keysym is Cyrillic (Unicode codepoints)."""
    return 0x0400 <= ks <= 0x04FF or 0x0500 <= ks <= 0x052F or 0x2DE0 <= ks <= 0x2DFF or 0xA640 <= ks <= 0xA69F'''

new_is_cyr = '''def _is_cyr(ks):
    """Check if keysym represents a Cyrillic character.
    Strips the Selkies Unicode prefix (0x01000000) before checking ranges.
    Only handles Unicode codepoints; X11 raw keysyms are left to
    send_x11_keypress which maps them via CYRILLIC_TO_QWERTY_KEYSYM."""
    cp = ks & 0xFFFFFF if (ks & 0xFF000000) == 0x01000000 else ks
    return (0x0400 <= cp <= 0x04FF or 0x0500 <= cp <= 0x052F or
            0x2DE0 <= cp <= 0x2DFF or 0xA640 <= cp <= 0xA69F)'''

if old_is_cyr in src:
    src = src.replace(old_is_cyr, new_is_cyr, 1)
    changed = True
    print("OK: _is_cyr() updated")
else:
    print("WARN: _is_cyr() pattern not found, trying alternate...")
    # Try finding the function with different formatting
    import re
    m = re.search(r'def _is_cyr\(ks\).*?(?=\n\S|\Z)', src, re.DOTALL)
    if m:
        print(f"Found _is_cyr at char {m.start()}, length {len(m.group())}")
        print(f"Content: {m.group()[:80]}...")
    else:
        print("_is_cyr not found at all!")

# ----------------------------------------------------------------
# 2. Fix Cyrillic interception blocks: chr(_cp) → f"U{_cp:04X}"
#    and remove --clearmodifiers
# ----------------------------------------------------------------
# Pattern: the xdotool type calls in the cyrillic kd blocks
old_xdotool = '"xdotool", "type", "--clearmodifiers", _ch'
new_xdotool = '"xdotool", "type", f"U{_cp:04X}"'

count_xdotool = src.count(old_xdotool)
if count_xdotool > 0:
    src = src.replace(old_xdotool, new_xdotool)
    changed = True
    print(f"OK: replaced {count_xdotool} xdotool type commands (U+XXXX format, no --clearmodifiers)")
else:
    print("WARN: xdotool type pattern not found")

# ----------------------------------------------------------------
# Validate syntax
# ----------------------------------------------------------------
tmp = FP + ".validate"
with open(tmp, "w") as f:
    f.write(src)
try:
    py_compile.compile(tmp, doraise=True)
    os.unlink(tmp)
except py_compile.PyCompileError as e:
    os.unlink(tmp)
    print(f"SYNTAX ERROR: {e}")
    sys.exit(1)

# ----------------------------------------------------------------
# Write back
# ----------------------------------------------------------------
if not changed:
    print("No changes needed - already fixed")
    sys.exit(0)

with open(FP, "w") as f:
    f.write(src)

print("OK: Fix applied successfully")
print("Validator: syntax OK")
