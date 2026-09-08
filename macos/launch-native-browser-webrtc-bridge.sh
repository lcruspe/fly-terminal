#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${HOME}/.config/fly-terminal-mac/fly-terminal.env"
if [ -f "${ENV_FILE}" ]; then
  set -a
  . "${ENV_FILE}"
  set +a
fi

[ "${FLY_NATIVE_BROWSER_ENABLED:-1}" = "1" ] || exit 0
export FLY_WEBRTC_BIND="127.0.0.1:${FLY_NATIVE_BROWSER_WEBRTC_PORT:-5908}"
export FLY_WEBRTC_SOURCE_URL="ws://127.0.0.1:${FLY_NATIVE_BROWSER_STREAMER_PORT:-5906}"
exec "${SCRIPT_DIR}/launch-webrtc-bridge.sh"
