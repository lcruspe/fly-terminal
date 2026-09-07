#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BETTERDISPLAY_BIN="/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay"
REMOTE_NAME="Fly Remote"
BROWSER_NAME="Fly Browser"

if [ ! -x "${BETTERDISPLAY_BIN}" ]; then
  echo "BetterDisplay is not installed; native browser display is unavailable." >&2
  exit 1
fi

"${SCRIPT_DIR}/ensure-betterdisplay-remote.sh"
identifiers="$(${BETTERDISPLAY_BIN} get -identifiers)"
if ! printf '%s' "${identifiers}" | /usr/bin/grep -q '"name" : "Fly Browser"'; then
  "${BETTERDISPLAY_BIN}" create \
    -type=VirtualScreen \
    -virtualScreenName="${BROWSER_NAME}" \
    -aspectWidth=16 \
    -aspectHeight=9 \
    -useResolutionList=on \
    -resolutionList='1280x720,1600x900,1920x1080,2560x1440' \
    -virtualScreenHiDPI=on \
    -connected=on >/dev/null
fi
connected="$(${BETTERDISPLAY_BIN} get -name="${BROWSER_NAME}" -connected)"
if [ "${connected}" != "on" ]; then
  "${BETTERDISPLAY_BIN}" set -name="${BROWSER_NAME}" -connected=on >/dev/null
fi

remote_placement="$(${BETTERDISPLAY_BIN} get -name="${REMOTE_NAME}" -placement)"
remote_resolution="$(${BETTERDISPLAY_BIN} get -name="${REMOTE_NAME}" -resolution)"
remote_x="${remote_placement%x*}"
remote_y="${remote_placement#*x}"
remote_width="${remote_resolution%x*}"

if ! [[ "${remote_x}" =~ '^-?[0-9]+$' && "${remote_y}" =~ '^-?[0-9]+$' && "${remote_width}" =~ '^[0-9]+$' ]]; then
  echo "Could not determine Fly Remote geometry: ${remote_placement},${remote_resolution}" >&2
  exit 1
fi

browser_x=$((remote_x + remote_width))
"${BETTERDISPLAY_BIN}" set \
  -name="${BROWSER_NAME}" \
  -connected=on \
  -resolution=1280x720 \
  -hiDPI=on \
  -placement="${browser_x}x${remote_y}" >/dev/null

printf '%s\n' "${browser_x}x${remote_y},1280x720"