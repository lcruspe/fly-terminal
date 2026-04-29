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

mkdir -p "${FLY_TERMINAL_HISTORY_DIR}"

DEFAULT_TERMINAL_THEME='{"background":"#f7f3e8","foreground":"#28231f","cursor":"#c65f2f","selectionBackground":"#e7d6b3","black":"#28231f","red":"#b84d43","green":"#587a45","yellow":"#a9762c","blue":"#3f6f9f","magenta":"#8a5c8f","cyan":"#3f8585","white":"#f4ead8","brightBlack":"#6f665c","brightRed":"#d85f4f","brightGreen":"#6f934f","brightYellow":"#c89136","brightBlue":"#5688bf","brightMagenta":"#a775aa","brightCyan":"#56a0a0","brightWhite":"#fff8eb"}'

exec /opt/homebrew/bin/ttyd \
  -i 127.0.0.1 \
  -p "${TTYD_PORT:-7682}" \
  -c "${TERMINAL_USER}:${TERMINAL_PASSWORD}" \
  -W \
  -b "/terminal" \
  -t "theme=${TERMINAL_THEME:-$DEFAULT_TERMINAL_THEME}" \
  -t "fontSize=${TERMINAL_FONT_SIZE:-12}" \
  -t "fontFamily=${TERMINAL_FONT_FAMILY:-Menlo,Monaco,monospace}" \
  -t "scrollback=${TERMINAL_SCROLLBACK:-4000}" \
  -t "cursorBlink=true" \
  -t "disableLeaveAlert=true" \
  "${REPO_ROOT}/terminal-session.sh"
