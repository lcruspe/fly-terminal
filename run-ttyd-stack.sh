#!/bin/sh
set -eu

TTYD_BIN="${TTYD_BIN:-ttyd}"
SESSION_SCRIPT="${FLY_TERMINAL_SESSION_SCRIPT:-/usr/local/bin/terminal-session.sh}"
CONTROL_SCRIPT="${FLY_TERMINAL_CONTROL_SCRIPT:-/usr/local/bin/session-control.py}"
TTYD_PORT="${TTYD_PORT:-7682}"
TERMINAL_BASE_PATH="${TERMINAL_BASE_PATH:-/terminal}"
TERMINAL_FONT_SIZE="${TERMINAL_FONT_SIZE:-12}"
TERMINAL_FONT_FAMILY="${TERMINAL_FONT_FAMILY:-JetBrains Mono, Menlo, Monaco, monospace}"
TERMINAL_SCROLLBACK="${TERMINAL_SCROLLBACK:-4000}"
TERMINAL_TITLE="${TERMINAL_TITLE:-Terminal}"

DEFAULT_TERMINAL_THEME='{"background":"#f7f3e8","foreground":"#28231f","cursor":"#c65f2f","selectionBackground":"#e7d6b3","black":"#28231f","red":"#b84d43","green":"#587a45","yellow":"#a9762c","blue":"#3f6f9f","magenta":"#8a5c8f","cyan":"#3f8585","white":"#f4ead8","brightBlack":"#6f665c","brightRed":"#d85f4f","brightGreen":"#6f934f","brightYellow":"#c89136","brightBlue":"#5688bf","brightMagenta":"#a775aa","brightCyan":"#56a0a0","brightWhite":"#fff8eb"}'
TERMINAL_THEME="${TERMINAL_THEME:-$DEFAULT_TERMINAL_THEME}"

cleanup() {
    [ -n "${TTYD_PID:-}" ] && kill "${TTYD_PID}" 2>/dev/null || true
    [ -n "${CONTROL_PID:-}" ] && kill "${CONTROL_PID}" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

python3 "$CONTROL_SCRIPT" &
CONTROL_PID=$!

set -- \
    -6 \
    -i 127.0.0.1 \
    -p "$TTYD_PORT" \
    -W \
    -a \
    -b "$TERMINAL_BASE_PATH" \
    --ping-interval 30 \
    -t "theme=${TERMINAL_THEME}" \
    -t "fontSize=${TERMINAL_FONT_SIZE}" \
    -t "fontFamily=${TERMINAL_FONT_FAMILY}" \
    -t "scrollback=${TERMINAL_SCROLLBACK}" \
    -t "cursorBlink=true" \
    -t "disableLeaveAlert=true" \
    -t "titleFixed=${TERMINAL_TITLE}"

if [ "${FLY_TERMINAL_TTYD_AUTH:-0}" = "1" ] && [ -n "${TERMINAL_USER:-}" ] && [ -n "${TERMINAL_PASSWORD:-}" ]; then
    set -- "$@" -c "${TERMINAL_USER}:${TERMINAL_PASSWORD}"
fi

"$TTYD_BIN" "$@" "$SESSION_SCRIPT" &
TTYD_PID=$!
wait "$TTYD_PID"
TTYD_STATUS=$?
[ -n "${CONTROL_PID:-}" ] && kill "${CONTROL_PID}" 2>/dev/null || true
wait "${CONTROL_PID}" 2>/dev/null || true
exit "$TTYD_STATUS"
