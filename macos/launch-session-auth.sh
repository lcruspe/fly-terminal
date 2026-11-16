#!/bin/zsh
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="${HOME}/.config/fly-terminal-mac"
set -a
source "${CONFIG_DIR}/fly-terminal.env"
set +a
SECRET_FILE="${CONFIG_DIR}/session-auth.secret"
if [ ! -s "${SECRET_FILE}" ]; then
  echo "Missing session-auth secret. Run install-session-auth.sh" >&2
  exit 1
fi
export FLY_AUTH_SECRET="$(cat "${SECRET_FILE}")"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
exec /opt/homebrew/bin/python3 "${DIR}/session_auth.py"
