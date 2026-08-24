#!/usr/bin/env python3
from pathlib import Path

path = Path('.github/workflows/gemini-dispatch.yml')
text = path.read_text(encoding='utf-8')
start_marker = '\n# TEMP_CONTAINER_FILE_BROWSER_START\n'
end_marker = '# TEMP_CONTAINER_FILE_BROWSER_END\n'
if start_marker in text:
    start = text.index(start_marker)
    end = text.index(end_marker, start) + len(end_marker)
    text = (text[:start] + '\n' + text[end:]).rstrip('\n') + '\n'
    path.write_text(text, encoding='utf-8')
