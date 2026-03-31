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

# Запуск ttyd с базовой авторизацией (если нужна)
# -i 0.0.0.0 для прослушивания всех интерфейсов
# -W для работы за прокси/load balancer
if [ -n "$TERMINAL_USER" ] && [ -n "$TERMINAL_PASSWORD" ]; then
    exec ttyd -i 0.0.0.0 -p $PORT -W -c ${TERMINAL_USER}:${TERMINAL_PASSWORD} bash
else
    exec ttyd -i 0.0.0.0 -p $PORT -W bash
fi
