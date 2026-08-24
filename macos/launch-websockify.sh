#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_DIR="${HOME}/.config/fly-terminal-mac"
ENV_FILE="${CONFIG_DIR}/fly-terminal.env"

if [ -f "${ENV_FILE}" ]; then
  set -a
  . "${ENV_FILE}"
  set +a
fi

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

DESKTOP_PORT="${FLY_DESKTOP_PORT:-5901}"
TARGET_VNC="${FLY_DESKTOP_TARGET:-127.0.0.1:5900}"

# Find python with websockify
PYTHON_BIN=""
if python3 -c "import websockify" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif /opt/homebrew/bin/python3 -c "import websockify" >/dev/null 2>&1; then
  PYTHON_BIN="/opt/homebrew/bin/python3"
elif which websockify >/dev/null 2>&1; then
  exec websockify "127.0.0.1:${DESKTOP_PORT}" "${TARGET_VNC}"
else
  # fallback to searching python environments
  for py in /Volumes/WD/Projects/browser-use/venv/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 /usr/bin/python3; do
    if [ -x "$py" ] && "$py" -c "import websockify" >/dev/null 2>&1; then
      PYTHON_BIN="$py"
      break
    fi
  done
fi

if [ -z "${PYTHON_BIN}" ]; then
  echo "Error: websockify not found in any Python environment." >&2
  exit 1
fi

exec "${PYTHON_BIN}" -m websockify "127.0.0.1:${DESKTOP_PORT}" "${TARGET_VNC}"
