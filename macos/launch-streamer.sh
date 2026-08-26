#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_DIR="${HOME}/.config/fly-terminal-mac"
ENV_FILE="${CONFIG_DIR}/fly-terminal.env"

if [ -f "${ENV_FILE}" ]; then
  set -a
  . "${ENV_FILE}"
  set +a
fi

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export PYTHONUNBUFFERED=1

FLY_DESKTOP_ENABLED="${FLY_DESKTOP_ENABLED:-1}"
[ "${FLY_DESKTOP_ENABLED}" = "1" ] || exit 0

if [ -x "${SCRIPT_DIR}/ensure-betterdisplay-remote.sh" ]; then
  "${SCRIPT_DIR}/ensure-betterdisplay-remote.sh" || echo "WARNING: BetterDisplay virtual screen is unavailable." >&2
fi

export FLY_STREAMER_PORT="${FLY_STREAMER_PORT:-5905}"
export FLY_STREAMER_FPS="${FLY_STREAMER_FPS:-60}"
export FLY_STREAMER_WIDTH="${FLY_STREAMER_WIDTH:-1920}"
export FLY_STREAMER_HEIGHT="${FLY_STREAMER_HEIGHT:-1080}"

# Ensure encoder app bundle is built and signed
APP_DIR="${SCRIPT_DIR}/bin/FlyDesktopCapture.app"
ENCODER_BIN="${APP_DIR}/Contents/MacOS/FlyDesktopCapture"
ENCODER_SRC="${SCRIPT_DIR}/fly-mac-encoder.swift"

if [ ! -f "${ENCODER_BIN}" ] || [ "${ENCODER_SRC}" -nt "${ENCODER_BIN}" ]; then
  mkdir -p "${APP_DIR}/Contents/MacOS" "${APP_DIR}/Contents/Resources"
  cat >"${APP_DIR}/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>ai.kruspe.fly-terminal.capture</string>
    <key>CFBundleName</key>
    <string>Fly Desktop Capture</string>
    <key>CFBundleDisplayName</key>
    <string>Fly Desktop Capture</string>
    <key>CFBundleExecutable</key>
    <string>FlyDesktopCapture</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSScreenCaptureUsageDescription</key>
    <string>Fly Terminal captures screen frames for high FPS remote desktop access.</string>
</dict>
</plist>
EOF
  echo "Compiling FlyDesktopCapture..."
  swiftc -O "${ENCODER_SRC}" -o "${ENCODER_BIN}"
  codesign --force --deep -s - "${APP_DIR}" 2>/dev/null || true
fi

# Run the current build from the stable user Applications path so macOS keeps
# Screen Recording permission attached to the app bundle across repo updates.
USER_APP_DIR="${HOME}/Applications/FlyDesktopCapture.app"
USER_ENCODER_BIN="${USER_APP_DIR}/Contents/MacOS/FlyDesktopCapture"
if [ ! -f "${USER_ENCODER_BIN}" ] || [ "${ENCODER_BIN}" -nt "${USER_ENCODER_BIN}" ]; then
  mkdir -p "${HOME}/Applications"
  /usr/bin/ditto "${APP_DIR}" "${USER_APP_DIR}"
  codesign --force --deep -s - "${USER_APP_DIR}" 2>/dev/null || true
fi

# Find Python with websockets
PYTHON_BIN=""
for py in "${HOME}/.local/share/fly-terminal/venv/bin/python3" /Volumes/WD/Projects/browser-use/venv/bin/python3 /opt/homebrew/bin/python3 python3; do
  if [ -x "$py" ] && "$py" -c "import websockets" >/dev/null 2>&1; then
    PYTHON_BIN="$py"
    break
  fi
done

if [ -z "${PYTHON_BIN}" ]; then
  echo "Error: Python with websockets not found." >&2
  exit 1
fi

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/fly-mac-streamer.py"
