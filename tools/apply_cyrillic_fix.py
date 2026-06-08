#!/usr/bin/env python3
"""
Apply Cyrillic keyboard fix to Selkies input_handler.py.
Adds _is_cyr() helper and Cyrillic kd interception in on_message.

Usage: docker cp apply_cyrillic_fix.py <container>:/tmp/ && docker exec -u root <container> python3 /tmp/apply_cyrillic_fix.py
"""

import os, sys, py_compile

FP = "/lsiopy/lib/python3.13/site-packages/selkies/input_handler.py"

with open(FP) as f:
    src = f.read()
orig = src

# 1. Add _is_cyr helper
marker = "CYRILLIC_TO_QWERTY_KEYSYM = {"
idx = src.find(marker)
brace_cnt = 0
end_idx = None
for i in range(idx, len(src)):
    if src[i] == '{': brace_cnt += 1
    elif src[i] == '}':
        brace_cnt -= 1
        if brace_cnt == 0:
            end_idx = i
            break

insert_at = src.find('\n', end_idx) + 1

cyr_helper = '''
## fly-terminal: cyrillic check ##
def _is_cyr(ks):
    """Check if keysym is Cyrillic (Unicode or X11 keysym range)."""
    return (0x0400 <= ks <= 0x04FF or 0x0500 <= ks <= 0x052F or
            0x2DE0 <= ks <= 0x2DFF or 0xA640 <= ks <= 0xA69F or
            0x06C1 <= ks <= 0x06FF)  # X11 keysym range for Cyrillic
'''

src = src[:insert_at] + cyr_helper + src[insert_at:]

# 2. Add Cyrillic interception in on_message kd handler
lines = src.split('\n')
new_lines = []
changes = 0
i = 0

while i < len(lines):
    line = lines[i]
    
    if ('send_x11_keypress(keysym, down=True)' in line
            and '## fly-terminal' not in line):
        ctx_start = max(0, i - 10)
        ctx = '\n'.join(lines[ctx_start:i])
        if any(x in ctx for x in ['active_modifiers', 'is_printable', 'char_to_type']):
            indent = line[:len(line) - len(line.lstrip())]
            cyr_kd = f"""\
{indent}## fly-terminal: cyrillic kd -> xdotool type ##
{indent}if _is_cyr(keysym):
{indent}    try:
{indent}        _cp = keysym & 0xFFFFFF if (keysym & 0xFF000000) == 0x01000000 else keysym
{indent}        _ch = chr(_cp)
{indent}        self.atomically_typed_keys.add(keysym)
{indent}        _proc = await subprocess.create_subprocess_exec(
{indent}            "xdotool", "type", "--clearmodifiers", _ch,
{indent}            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
{indent}        await asyncio.wait_for(_proc.communicate(), timeout=0.5)
{indent}    except Exception:
{indent}        await self.send_x11_keypress(keysym, down=True)
{indent}else:
{indent}    await self.send_x11_keypress(keysym, down=True)"""
            new_lines.append(cyr_kd)
            changes += 1
            i += 1
            continue
    new_lines.append(line)
    i += 1

if changes == 0:
    print("No on_message kd calls found to patch.", file=sys.stderr)
    sys.exit(1)

src = '\n'.join(new_lines)

# Validate syntax
tmp = FP + ".validate"
with open(tmp, "w") as f:
    f.write(src)
try:
    py_compile.compile(tmp, doraise=True)
    os.unlink(tmp)
except py_compile.PyCompileError as e:
    os.unlink(tmp)
    print(f"SYNTAX ERROR: {e}", file=sys.stderr)
    sys.exit(1)

# Write
with open(FP, "w") as f:
    f.write(src)

# Create marker
open("/tmp/fly-terminal-selkies-xtest-patched", "w").close()

print(f"Patched {FP}: {changes} Cyrillic kd -> xdotool type interceptions added")
sys.exit(0)
