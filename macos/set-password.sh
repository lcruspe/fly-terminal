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

python3 - "$ENV_FILE" "$1" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
new_password = sys.argv[2]
lines = env_path.read_text().splitlines()
updated = False
result = []
for line in lines:
    if line.startswith("TERMINAL_PASSWORD="):
        result.append(f"TERMINAL_PASSWORD={new_password}")
        updated = True
    else:
        result.append(line)
if not updated:
    result.append(f"TERMINAL_PASSWORD={new_password}")
env_path.write_text("\n".join(result) + "\n")
PY

chmod 600 "${ENV_FILE}"
launchctl kickstart -k "gui/${UID_VALUE}/ai.kruspe.fly-terminal.ttyd"
