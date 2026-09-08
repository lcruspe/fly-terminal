#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${HOME}/.config/fly-terminal-mac/fly-terminal.env"
override_bind="${FLY_WEBRTC_BIND-}"
override_source="${FLY_WEBRTC_SOURCE_URL-}"

if [ -f "${ENV_FILE}" ]; then
  set -a
  . "${ENV_FILE}"
  set +a
fi

[ -n "${override_bind}" ] && FLY_WEBRTC_BIND="${override_bind}"
[ -n "${override_source}" ] && FLY_WEBRTC_SOURCE_URL="${override_source}"
[ "${FLY_DESKTOP_ENABLED:-1}" = "1" ] || exit 0

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export FLY_WEBRTC_BIND="${FLY_WEBRTC_BIND:-127.0.0.1:${FLY_WEBRTC_PORT:-5907}}"
export FLY_WEBRTC_SOURCE_URL="${FLY_WEBRTC_SOURCE_URL:-ws://127.0.0.1:${FLY_STREAMER_PORT:-5905}}"

BIN_PATH="${FLY_WEBRTC_BIN_PATH:-${HOME}/.local/share/fly-terminal/bin/fly-webrtc-bridge}"
if [ ! -x "${BIN_PATH}" ]; then
  echo "Fly WebRTC bridge binary is missing: ${BIN_PATH}. Run build-webrtc-bridge.sh first." >&2
  exit 1
fi
exec "${BIN_PATH}"
