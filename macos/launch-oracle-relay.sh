#!/bin/zsh
set -euo pipefail

CONFIG_DIR="${HOME}/.config/fly-terminal-mac"
ENV_FILE="${CONFIG_DIR}/fly-terminal.env"

if [ -f "${ENV_FILE}" ]; then
  set -a
  . "${ENV_FILE}"
  set +a
fi

: "${FLY_ORACLE_RELAY_HOST:?FLY_ORACLE_RELAY_HOST is required}"
: "${FLY_ORACLE_RELAY_USER:?FLY_ORACLE_RELAY_USER is required}"
: "${FLY_ORACLE_RELAY_KEY:?FLY_ORACLE_RELAY_KEY is required}"

exec /usr/bin/ssh -F /dev/null -NT \
  -i "${FLY_ORACLE_RELAY_KEY}" \
  -o BatchMode=yes -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  -o ConnectTimeout=10 -o StrictHostKeyChecking=yes \
  -R "127.0.0.1:${FLY_ORACLE_RELAY_GATEWAY_PORT:-18080}:127.0.0.1:${CADDY_PORT:-8080}" \
  -R "127.0.0.1:${FLY_ORACLE_RELAY_TERMINAL_PORT:-18081}:127.0.0.1:${CADDY_TERMINAL_PORT:-8081}" \
  -R "127.0.0.1:${FLY_ORACLE_RELAY_SPRUTHUB_PORT:-18082}:127.0.0.1:${CADDY_SPRUTHUB_PORT:-8082}" \
  "${FLY_ORACLE_RELAY_USER}@${FLY_ORACLE_RELAY_HOST}"
