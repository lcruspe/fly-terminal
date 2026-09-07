#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${HOME}/.config/fly-terminal-mac/fly-terminal.env"

if [ ! -f "${ENV_FILE}" ]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi

set -a
. "${ENV_FILE}"
set +a

if [ "${FLY_SPRUTHUB_ENABLED:-0}" != "1" ]; then
  echo "Sprut.Hub forwarder is disabled"
  exit 0
fi

exec /usr/bin/python3 "${SCRIPT_DIR}/spruthub-forwarder.py"
