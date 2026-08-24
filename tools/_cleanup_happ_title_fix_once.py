#!/usr/bin/env python3
from pathlib import Path


dispatch = Path('.github/workflows/gemini-dispatch.yml')
text = dispatch.read_text(encoding='utf-8')
start_marker = '\n# TEMP_HAPP_TITLE_FIX_START\n'
end_marker = '# TEMP_HAPP_TITLE_FIX_END\n'
start = text.index(start_marker)
end = text.index(end_marker, start) + len(end_marker)
dispatch.write_text((text[:start] + '\n' + text[end:]).rstrip('\n') + '\n', encoding='utf-8')

for name in (
    '.github/workflows/fix-happ-subscription-title-once.yml',
    'tools/_fix_happ_subscription_title_once.py',
    'tools/_cleanup_happ_title_fix_once.py',
):
    Path(name).unlink(missing_ok=True)
