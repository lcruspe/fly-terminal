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

"${SCRIPT_DIR}/ensure-betterdisplay-browser.sh" >/dev/null

export FLY_DESKTOP_ENABLED=1
export FLY_STREAMER_PORT="${FLY_NATIVE_BROWSER_STREAMER_PORT:-5906}"
export FLY_STREAMER_DISPLAY_NAME="${FLY_NATIVE_BROWSER_DISPLAY_NAME:-Fly Browser}"
export FLY_STREAMER_SOCKET_PATH="${FLY_NATIVE_BROWSER_STREAMER_SOCKET_PATH:-/tmp/fly-native-browser-stream.sock}"
export FLY_STREAMER_WIDTH="${FLY_NATIVE_BROWSER_STREAMER_WIDTH:-1920}"
export FLY_STREAMER_HEIGHT="${FLY_NATIVE_BROWSER_STREAMER_HEIGHT:-1080}"
export FLY_STREAMER_FPS="${FLY_NATIVE_BROWSER_STREAMER_FPS:-60}"

exec "${SCRIPT_DIR}/launch-streamer.sh"