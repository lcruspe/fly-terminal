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

CHROME_BIN="${FLY_NATIVE_BROWSER_CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
if [ ! -x "${CHROME_BIN}" ]; then
  echo "Google Chrome is not installed at ${CHROME_BIN}" >&2
  exit 1
fi

geometry="$(${SCRIPT_DIR}/ensure-betterdisplay-browser.sh)"
placement="${geometry%%,*}"
resolution="${geometry#*,}"
window_x="${placement%x*}"
window_y="${placement#*x}"
window_width="${resolution%x*}"
window_height="${resolution#*x}"

profile_dir="${FLY_NATIVE_BROWSER_PROFILE_DIR:-${HOME}/.local/share/fly-terminal/native-browser-profile}"
home_url="${FLY_NATIVE_BROWSER_HOME_URL:-about:blank}"
mkdir -p "${profile_dir}"
exec "${CHROME_BIN}" \
  --user-data-dir="${profile_dir}" \
  --no-first-run \
  --no-default-browser-check \
  --hide-crash-restore-bubble \
  --disable-background-mode \
  --disable-features=TranslateUI \
  --window-position="${window_x},${window_y}" \
  --window-size="${window_width},${window_height}" \
  "${home_url}"