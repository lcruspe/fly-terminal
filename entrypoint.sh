#!/bin/sh
set -e

echo "Starting Tailscale daemon..."
# Запуск демона Tailscale в userspace режиме (без tun устройства)
tailscaled --tun=userspace-networking --socks5-server=localhost:1055 &

# Ждем запуска демона
sleep 2

echo "Connecting to Tailscale network..."
# Авторизация в Tailnet с эфемерным ключом
tailscale up --authkey=${TS_AUTHKEY} --hostname=fly-terminal --accept-routes

echo "Tailscale connected. Starting web terminal..."
# Railway использует переменную PORT
PORT=${PORT:-7681}

DEFAULT_TERMINAL_THEME='{"background":"#f7f3e8","foreground":"#28231f","cursor":"#c65f2f","selectionBackground":"#e7d6b3","black":"#28231f","red":"#b84d43","green":"#587a45","yellow":"#a9762c","blue":"#3f6f9f","magenta":"#8a5c8f","cyan":"#3f8585","white":"#f4ead8","brightBlack":"#6f665c","brightRed":"#d85f4f","brightGreen":"#6f934f","brightYellow":"#c89136","brightBlue":"#5688bf","brightMagenta":"#a775aa","brightCyan":"#56a0a0","brightWhite":"#fff8eb"}'

: "${TERMINAL_THEME:=$DEFAULT_TERMINAL_THEME}"
: "${TERMINAL_FONT_SIZE:=15}"
: "${TERMINAL_FONT_FAMILY:=JetBrains Mono, Menlo, Monaco, monospace}"

set -- \
    -i 0.0.0.0 \
    -p "$PORT" \
    -W \
    -t "theme=${TERMINAL_THEME}" \
    -t "fontSize=${TERMINAL_FONT_SIZE}" \
    -t "fontFamily=${TERMINAL_FONT_FAMILY}" \
    -t "cursorBlink=true" \
    -t "disableLeaveAlert=true"

# Запуск ttyd с базовой авторизацией (если нужна)
if [ -n "$TERMINAL_USER" ] && [ -n "$TERMINAL_PASSWORD" ]; then
    set -- "$@" -c "${TERMINAL_USER}:${TERMINAL_PASSWORD}"
fi

exec ttyd "$@" bash
