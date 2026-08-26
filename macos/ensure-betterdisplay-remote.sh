#!/bin/zsh
set -euo pipefail

BETTERDISPLAY_BIN="/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay"
REMOTE_NAME="Fly Remote"

if [ ! -x "${BETTERDISPLAY_BIN}" ]; then
  echo "BetterDisplay is not installed; virtual remote display is unavailable." >&2
  exit 1
fi

identifiers="$(${BETTERDISPLAY_BIN} get -identifiers)"
if printf '%s' "${identifiers}" | /usr/bin/grep -q '"name" : "Fly Remote"'; then
  connected="$(${BETTERDISPLAY_BIN} get -name="${REMOTE_NAME}" -connected)"
  if [ "${connected}" != "on" ]; then
    "${BETTERDISPLAY_BIN}" set -name="${REMOTE_NAME}" -connected=on >/dev/null
  fi
else
  "${BETTERDISPLAY_BIN}" create \
    -type=VirtualScreen \
    -virtualScreenName="${REMOTE_NAME}" \
    -aspectWidth=16 \
    -aspectHeight=9 \
    -useResolutionList=on \
    -resolutionList='1280x720,1600x900,1920x1080,2560x1440' \
    -virtualScreenHiDPI=on \
    -connected=on >/dev/null
fi
