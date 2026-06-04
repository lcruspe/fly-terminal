#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
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

FLY_BROWSER_ENABLED="${FLY_BROWSER_ENABLED:-0}"
[ "${FLY_BROWSER_ENABLED}" = "1" ] || exit 0

FLY_BROWSER_IMAGE="${FLY_BROWSER_IMAGE:-kasmweb/chrome:1.17.0}"
FLY_BROWSER_HOST_PORT="${FLY_BROWSER_HOST_PORT:-7690}"
FLY_BROWSER_PROFILE_DIR="${FLY_BROWSER_PROFILE_DIR:-${HOME}/.local/share/fly-terminal/browser-profile}"
FLY_BROWSER_CONTAINER_NAME="${FLY_BROWSER_CONTAINER_NAME:-fly-terminal-browser}"
FLY_BROWSER_PROFILE_VOLUME="${FLY_BROWSER_PROFILE_VOLUME:-fly-terminal-browser-profile}"
FLY_BROWSER_PASSWORD="${FLY_BROWSER_PASSWORD:-${TERMINAL_PASSWORD:-password}}"

mkdir -p "${FLY_BROWSER_PROFILE_DIR}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required for fly-terminal browser module." >&2
  exit 1
fi

if docker ps --format '{{.Names}}' | grep -qx "${FLY_BROWSER_CONTAINER_NAME}"; then
  exit 0
fi

if docker ps -a --format '{{.Names}}' | grep -qx "${FLY_BROWSER_CONTAINER_NAME}"; then
  docker rm -f "${FLY_BROWSER_CONTAINER_NAME}" >/dev/null
fi

docker volume create "${FLY_BROWSER_PROFILE_VOLUME}" >/dev/null

docker run -d \
  --name "${FLY_BROWSER_CONTAINER_NAME}" \
  --shm-size=1g \
  -p "127.0.0.1:${FLY_BROWSER_HOST_PORT}:6901" \
  -e "VNC_PW=${FLY_BROWSER_PASSWORD}" \
  -v "${FLY_BROWSER_PROFILE_VOLUME}:/home/kasm-user" \
  "${FLY_BROWSER_IMAGE}" >/dev/null
