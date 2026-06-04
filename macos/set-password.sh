#!/bin/zsh
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <new-password>" >&2
  exit 1
fi

CONFIG_DIR="${HOME}/.config/fly-terminal-mac"
ENV_FILE="${CONFIG_DIR}/fly-terminal.env"
UID_VALUE="$(id -u)"

if [ ! -f "${ENV_FILE}" ]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi

browser_basic_auth="$(printf 'kasm_user:%s' "$1" | base64 | tr -d '\n')"

python3 - "$ENV_FILE" "$1" "$browser_basic_auth" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
new_password = sys.argv[2]
browser_basic_auth = sys.argv[3]
lines = env_path.read_text().splitlines()
password_updated = False
browser_auth_updated = False
result = []
for line in lines:
    if line.startswith("TERMINAL_PASSWORD="):
        result.append(f"TERMINAL_PASSWORD={new_password}")
        password_updated = True
    elif line.startswith("FLY_BROWSER_BASIC_AUTH="):
        result.append(f"FLY_BROWSER_BASIC_AUTH={browser_basic_auth}")
        browser_auth_updated = True
    else:
        result.append(line)
if not password_updated:
    result.append(f"TERMINAL_PASSWORD={new_password}")
if not browser_auth_updated:
    result.append(f"FLY_BROWSER_BASIC_AUTH={browser_basic_auth}")
env_path.write_text("\n".join(result) + "\n")
PY

chmod 600 "${ENV_FILE}"
launchctl kickstart -k "gui/${UID_VALUE}/ai.kruspe.fly-terminal.ttyd"
launchctl kickstart -k "gui/${UID_VALUE}/ai.kruspe.fly-terminal.caddy"
launchctl kickstart -k "gui/${UID_VALUE}/ai.kruspe.fly-terminal.browser" 2>/dev/null || true
