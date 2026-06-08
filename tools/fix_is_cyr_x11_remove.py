#!/usr/bin/env python3
"""Remove the X11 keysym range from _is_cyr() in selkies input_handler.py.

The current _is_cyr() strips the Selkies prefix (good) but ALSO checks the
X11 keysym range (0x06C1-0x06FF). When it catches those, _cp stays as the
raw X11 keysym (e.g. 0x06C1), producing f"U{_cp:04X}" = "U06C1" which maps
to an Arabic character, not Cyrillic U+0410.

We keep the prefix stripping + Unicode range check, but remove the X11 range.
"""

import os, sys, py_compile

FP = "/lsiopy/lib/python3.13/site-packages/selkies/input_handler.py"
with open(FP) as f:
    src = f.read()
orig = src

# Match the CURRENT _is_cyr() which has the X11 keysym range
old_func = '''def _is_cyr(ks):
    """Check if keysym represents a Cyrillic character.
    Handles: raw Unicode (0x0400+), X11 keysyms (0x06C1-0x06FF),
    and Selkies-prefixed Unicode (0x0100XXXX)."""
    # Strip Selkies Unicode prefix if present
    cp = ks & 0xFFFFFF if (ks & 0xFF000000) == 0x01000000 else ks
    # Unicode Cyrillic ranges
    if 0x0400 <= cp <= 0x04FF or 0x0500 <= cp <= 0x052F or        0x2DE0 <= cp <= 0x2DFF or 0xA640 <= cp <= 0xA69F:
        return True
    # X11 keysym Cyrillic range (0x06C1-0x06FF)
    if 0x06C1 <= ks <= 0x06FF and ks < 0x01000000:
        return True
    return False'''

new_func = '''def _is_cyr(ks):
    """Check if keysym represents a Cyrillic character.
    Strips Selkies prefix (0x01000000) before checking Unicode ranges.
    X11 raw keysyms (0x06C1-0x06FF) are handled by send_x11_keypress."""
    cp = ks & 0xFFFFFF if (ks & 0xFF000000) == 0x01000000 else ks
    return (0x0400 <= cp <= 0x04FF or 0x0500 <= cp <= 0x052F or
            0x2DE0 <= cp <= 0x2DFF or 0xA640 <= cp <= 0xA69F)'''

if old_func in src:
    src = src.replace(old_func, new_func, 1)
    print("OK: _is_cyr() updated - X11 range removed")
elif new_func in src:
    print("Already fixed - no changes needed")
    sys.exit(0)
else:
    print("ERROR: could not match current _is_cyr()")
    # Debug: show what's there
    import re
    m = re.search(r'def _is_cyr\(ks\).*?(?=\n\S|\Z)', src, re.DOTALL)
    if m:
        print("---MATCHED TEXT---")
        print(m.group())
        print("---END---")
    else:
        print("_is_cyr not found with regex either")
    sys.exit(1)

# Validate
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

with open(FP, "w") as f:
    f.write(src)
print("OK: Fix applied - syntax valid")
