#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_DIR="${HOME}/.config/fly-terminal-mac"
ENV_FILE="${CONFIG_DIR}/fly-terminal.env"

if [ ! -f "${ENV_FILE}" ]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi

set -a
. "${ENV_FILE}"
set +a

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export FLY_TERMINAL_REPO_ROOT="${REPO_ROOT}"
export XDG_DATA_HOME="${HOME}/.local/share/caddy"
mkdir -p "${XDG_DATA_HOME}"

exec /opt/homebrew/bin/caddy run \
  --config "${SCRIPT_DIR}/Caddyfile" \
  --adapter caddyfile
