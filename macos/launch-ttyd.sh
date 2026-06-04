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
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export LC_CTYPE="${LC_CTYPE:-C.UTF-8}"
export TERM="${TERM:-xterm-256color}"
export FLY_TERMINAL_HISTORY_DIR="${FLY_TERMINAL_HISTORY_DIR:-${HOME}/.local/share/fly-terminal/bash_history}"
export FLY_TERMINAL_CONTROL_SCRIPT="${REPO_ROOT}/session-control.py"
export FLY_TERMINAL_SESSION_SCRIPT="${REPO_ROOT}/terminal-session.sh"
export TTYD_BIN="/opt/homebrew/bin/ttyd"

mkdir -p "${FLY_TERMINAL_HISTORY_DIR}"

exec "${REPO_ROOT}/run-ttyd-stack.sh"
