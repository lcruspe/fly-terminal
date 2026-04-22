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
TTYD_PORT=${TTYD_PORT:-7682}
TERMINAL_BASE_PATH=${TERMINAL_BASE_PATH:-/terminal}

DEFAULT_TERMINAL_THEME='{"background":"#f7f3e8","foreground":"#28231f","cursor":"#c65f2f","selectionBackground":"#e7d6b3","black":"#28231f","red":"#b84d43","green":"#587a45","yellow":"#a9762c","blue":"#3f6f9f","magenta":"#8a5c8f","cyan":"#3f8585","white":"#f4ead8","brightBlack":"#6f665c","brightRed":"#d85f4f","brightGreen":"#6f934f","brightYellow":"#c89136","brightBlue":"#5688bf","brightMagenta":"#a775aa","brightCyan":"#56a0a0","brightWhite":"#fff8eb"}'

: "${TERMINAL_THEME:=$DEFAULT_TERMINAL_THEME}"
: "${TERMINAL_FONT_SIZE:=15}"
: "${TERMINAL_FONT_FAMILY:=JetBrains Mono, Menlo, Monaco, monospace}"
: "${TERMINAL_COMMAND:=tmux new-session -A -s fly-terminal}"

set -- \
    -i 127.0.0.1 \
    -p "$TTYD_PORT" \
    -W \
    -t "theme=${TERMINAL_THEME}" \
    -t "fontSize=${TERMINAL_FONT_SIZE}" \
    -t "fontFamily=${TERMINAL_FONT_FAMILY}" \
    -t "cursorBlink=true" \
    -t "disableLeaveAlert=true" \
    -b "$TERMINAL_BASE_PATH"

# Запуск ttyd с базовой авторизацией (если нужна)
if [ -n "$TERMINAL_USER" ] && [ -n "$TERMINAL_PASSWORD" ]; then
    set -- "$@" -c "${TERMINAL_USER}:${TERMINAL_PASSWORD}"
fi

ttyd "$@" sh -lc "$TERMINAL_COMMAND" &
TTYD_PID=$!

cat >/tmp/nginx.conf <<EOF
events {}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;

    server {
        listen ${PORT};
        server_name _;
        root /usr/share/nginx/html;
        index index.html;

        location / {
            try_files \$uri \$uri/ /index.html;
        }

        location = ${TERMINAL_BASE_PATH} {
            return 302 ${TERMINAL_BASE_PATH}/;
        }

        location ${TERMINAL_BASE_PATH}/ {
            proxy_pass http://127.0.0.1:${TTYD_PORT}${TERMINAL_BASE_PATH}/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade \$http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_read_timeout 86400;
        }
    }
}
EOF

trap 'kill "$TTYD_PID" 2>/dev/null || true' INT TERM
exec nginx -c /tmp/nginx.conf -g 'daemon off;'
