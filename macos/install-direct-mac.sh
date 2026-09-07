#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_DIR="${HOME}/.config/fly-terminal-mac"
LOG_DIR="${HOME}/Library/Logs/fly-terminal"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
ENV_FILE="${CONFIG_DIR}/fly-terminal.env"
TTYD_LABEL="ai.kruspe.fly-terminal.ttyd"
CADDY_LABEL="ai.kruspe.fly-terminal.caddy"
BROWSER_LABEL="ai.kruspe.fly-terminal.browser"
WEBSOCKIFY_LABEL="ai.kruspe.fly-terminal.websockify"
STREAMER_LABEL="ai.kruspe.fly-terminal.streamer"
NATIVE_BROWSER_LABEL="ai.kruspe.fly-terminal.native-browser"
NATIVE_BROWSER_STREAMER_LABEL="ai.kruspe.fly-terminal.native-browser-streamer"
SPRUTHUB_LABEL="ai.kruspe.fly-terminal.spruthub"
TTYD_PLIST="${LAUNCH_AGENTS_DIR}/${TTYD_LABEL}.plist"
CADDY_PLIST="${LAUNCH_AGENTS_DIR}/${CADDY_LABEL}.plist"
BROWSER_PLIST="${LAUNCH_AGENTS_DIR}/${BROWSER_LABEL}.plist"
WEBSOCKIFY_PLIST="${LAUNCH_AGENTS_DIR}/${WEBSOCKIFY_LABEL}.plist"
STREAMER_PLIST="${LAUNCH_AGENTS_DIR}/${STREAMER_LABEL}.plist"
NATIVE_BROWSER_PLIST="${LAUNCH_AGENTS_DIR}/${NATIVE_BROWSER_LABEL}.plist"
NATIVE_BROWSER_STREAMER_PLIST="${LAUNCH_AGENTS_DIR}/${NATIVE_BROWSER_STREAMER_LABEL}.plist"
SPRUTHUB_PLIST="${LAUNCH_AGENTS_DIR}/${SPRUTHUB_LABEL}.plist"
UID_VALUE="$(id -u)"

mkdir -p "${CONFIG_DIR}" "${LOG_DIR}" "${LAUNCH_AGENTS_DIR}" "${HOME}/.local/share/fly-terminal/bash_history" "${HOME}/.local/share/fly-terminal/browser-profile" "${HOME}/.local/share/fly-terminal/native-browser-profile" "${HOME}/.local/share/caddy"

if [ ! -f "${ENV_FILE}" ]; then
  cat >"${ENV_FILE}" <<'EOF'
TERMINAL_USER=admin
TERMINAL_PASSWORD=change-me
TTYD_PORT=7682
CADDY_PORT=8080
CADDY_TERMINAL_PORT=8081
CADDY_SPRUTHUB_PORT=8082
TERMINAL_SCROLLBACK=4000
TERMINAL_FONT_SIZE=12
TERMINAL_FONT_FAMILY=Menlo,Monaco,monospace
FLY_TERMINAL_HISTSIZE=5000
FLY_TERMINAL_HISTFILESIZE=10000
FLY_TERMINAL_SESSION_IDLE_TTL_MINUTES=120
FLY_TERMINAL_TMUX_HISTORY_LIMIT=5000
FLY_TERMINAL_HISTORY_DIR=$HOME/.local/share/fly-terminal/bash_history
FLY_BROWSER_ENABLED=1
FLY_BROWSER_URL=/browser/
FLY_BROWSER_IMAGE=lscr.io/linuxserver/chromium:latest
FLY_BROWSER_HOST_PORT=7690
FLY_BROWSER_CONTAINER_PORT=3000
FLY_BROWSER_UPSTREAM=http://127.0.0.1:7690
FLY_BROWSER_PROFILE_DIR=$HOME/.local/share/fly-terminal/browser-profile
FLY_BROWSER_PROFILE_VOLUME=fly-terminal-browser-profile
FLY_NATIVE_BROWSER_ENABLED=1
FLY_NATIVE_BROWSER_PROFILE_DIR=$HOME/.local/share/fly-terminal/native-browser-profile
FLY_NATIVE_BROWSER_STREAMER_PORT=5906
FLY_NATIVE_BROWSER_STREAMER_SOCKET_PATH=/tmp/fly-native-browser-stream.sock
FLY_NATIVE_BROWSER_DISPLAY_NAME=Fly\ Browser
FLY_NATIVE_BROWSER_FOLLOW_MAIN_WHEN_LOCKED=1
FLY_DESKTOP_ENABLED=1
FLY_DESKTOP_URL=/desktop/
FLY_DESKTOP_PORT=5901
FLY_DESKTOP_TARGET=127.0.0.1:5900
FLY_DESKTOP_PASSWORD=
FLY_SPRUTHUB_ENABLED=0
FLY_SPRUTHUB_AUTH_USER=
FLY_SPRUTHUB_AUTH_HASH_B64=
FLY_SPRUTHUB_FORWARD_HOST=127.0.0.1
FLY_SPRUTHUB_FORWARD_PORT=7693
FLY_SPRUTHUB_TARGET_HOST=192.168.1.100
FLY_SPRUTHUB_TARGET_PORT=80
EOF
  chmod 600 "${ENV_FILE}"
fi

ensure_env_line() {
  key="$1"
  value="$2"
  if ! grep -q "^${key}=" "${ENV_FILE}"; then
    printf '%s=%s\n' "${key}" "${value}" >>"${ENV_FILE}"
  fi
}

bootstrap_agent() {
  label="$1"
  plist="$2"
  attempt=1
  while [ "${attempt}" -le 5 ]; do
    if launchctl bootstrap "gui/${UID_VALUE}" "${plist}" 2>/dev/null; then
      return 0
    fi
    if launchctl print "gui/${UID_VALUE}/${label}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    attempt=$((attempt + 1))
  done
  echo "Failed to bootstrap ${label}: ${plist}" >&2
  return 1
}

kickstart_agent() {
  label="$1"
  plist="$2"
  attempt=1
  while [ "${attempt}" -le 5 ]; do
    if launchctl print "gui/${UID_VALUE}/${label}" >/dev/null 2>&1 \
      && launchctl kickstart -k "gui/${UID_VALUE}/${label}" 2>/dev/null; then
      return 0
    fi
    launchctl bootout "gui/${UID_VALUE}/${label}" 2>/dev/null || true
    bootstrap_agent "${label}" "${plist}"
    sleep 1
    attempt=$((attempt + 1))
  done
  echo "Failed to kickstart ${label}: ${plist}" >&2
  return 1
}

ensure_env_line "CADDY_PORT" "8080"
ensure_env_line "CADDY_TERMINAL_PORT" "8081"
ensure_env_line "CADDY_SPRUTHUB_PORT" "8082"
ensure_env_line "FLY_BROWSER_ENABLED" "1"
ensure_env_line "FLY_BROWSER_URL" "/browser/"
ensure_env_line "FLY_BROWSER_IMAGE" "lscr.io/linuxserver/chromium:latest"
ensure_env_line "FLY_BROWSER_HOST_PORT" "7690"
ensure_env_line "FLY_BROWSER_CONTAINER_PORT" "3000"
ensure_env_line "FLY_BROWSER_UPSTREAM" "http://127.0.0.1:7690"
ensure_env_line "FLY_BROWSER_PROFILE_DIR" "\$HOME/.local/share/fly-terminal/browser-profile"
ensure_env_line "FLY_BROWSER_PROFILE_VOLUME" "fly-terminal-browser-profile"
ensure_env_line "FLY_NATIVE_BROWSER_ENABLED" "1"
ensure_env_line "FLY_NATIVE_BROWSER_PROFILE_DIR" "\$HOME/.local/share/fly-terminal/native-browser-profile"
ensure_env_line "FLY_NATIVE_BROWSER_STREAMER_PORT" "5906"
ensure_env_line "FLY_NATIVE_BROWSER_STREAMER_SOCKET_PATH" "/tmp/fly-native-browser-stream.sock"
ensure_env_line "FLY_NATIVE_BROWSER_DISPLAY_NAME" "Fly\ Browser"
ensure_env_line "FLY_NATIVE_BROWSER_FOLLOW_MAIN_WHEN_LOCKED" "1"
ensure_env_line "FLY_DESKTOP_ENABLED" "1"
ensure_env_line "FLY_DESKTOP_URL" "/desktop/"
ensure_env_line "FLY_DESKTOP_PORT" "5901"
ensure_env_line "FLY_DESKTOP_TARGET" "127.0.0.1:5900"
ensure_env_line "FLY_DESKTOP_PASSWORD" ""
ensure_env_line "FLY_STREAMER_PORT" "5905"
ensure_env_line "FLY_STREAMER_FPS" "60"
ensure_env_line "FLY_SPRUTHUB_ENABLED" "0"
ensure_env_line "FLY_SPRUTHUB_AUTH_USER" ""
ensure_env_line "FLY_SPRUTHUB_AUTH_HASH_B64" ""
ensure_env_line "FLY_SPRUTHUB_FORWARD_HOST" "127.0.0.1"
ensure_env_line "FLY_SPRUTHUB_FORWARD_PORT" "7693"
ensure_env_line "FLY_SPRUTHUB_TARGET_HOST" "192.168.1.100"
ensure_env_line "FLY_SPRUTHUB_TARGET_PORT" "80"

set -a
. "${ENV_FILE}"
set +a

browser_basic_auth="$(printf 'kasm_user:%s' "${FLY_BROWSER_PASSWORD:-${TERMINAL_PASSWORD:-password}}" | base64 | tr -d '\n')"
if grep -q "^FLY_BROWSER_BASIC_AUTH=" "${ENV_FILE}"; then
  python3 - "$ENV_FILE" "$browser_basic_auth" <<'PY'
from pathlib import Path
import sys
env_path = Path(sys.argv[1])
value = sys.argv[2]
lines = env_path.read_text().splitlines()
env_path.write_text("\n".join(
    f"FLY_BROWSER_BASIC_AUTH={value}" if line.startswith("FLY_BROWSER_BASIC_AUTH=") else line
    for line in lines
) + "\n")
PY
else
  printf 'FLY_BROWSER_BASIC_AUTH=%s\n' "${browser_basic_auth}" >>"${ENV_FILE}"
fi

chmod +x "${SCRIPT_DIR}/launch-ttyd.sh" "${SCRIPT_DIR}/launch-caddy.sh" "${SCRIPT_DIR}/launch-browser.sh" "${SCRIPT_DIR}/launch-native-browser.sh" "${SCRIPT_DIR}/launch-native-browser-streamer.sh" "${SCRIPT_DIR}/launch-websockify.sh" "${SCRIPT_DIR}/launch-streamer.sh" "${SCRIPT_DIR}/launch-spruthub-forwarder.sh" "${SCRIPT_DIR}/spruthub-forwarder.py" "${SCRIPT_DIR}/ensure-betterdisplay-remote.sh" "${SCRIPT_DIR}/ensure-betterdisplay-browser.sh" "${SCRIPT_DIR}/set-password.sh"

cat >"${TTYD_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${TTYD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>${SCRIPT_DIR}/launch-ttyd.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/ttyd.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/ttyd.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
      <key>HOME</key>
      <string>${HOME}</string>
    </dict>
  </dict>
</plist>
EOF

cat >"${CADDY_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${CADDY_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>${SCRIPT_DIR}/launch-caddy.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/caddy.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/caddy.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
      <key>HOME</key>
      <string>${HOME}</string>
    </dict>
  </dict>
</plist>
EOF

cat >"${BROWSER_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${BROWSER_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>${SCRIPT_DIR}/launch-browser.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/browser.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/browser.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
      <key>HOME</key>
      <string>${HOME}</string>
    </dict>
  </dict>
</plist>
EOF

cat >"${WEBSOCKIFY_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${WEBSOCKIFY_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>${SCRIPT_DIR}/launch-websockify.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/websockify.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/websockify.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
      <key>HOME</key>
      <string>${HOME}</string>
    </dict>
  </dict>
</plist>
EOF

cat >"${STREAMER_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${STREAMER_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>${SCRIPT_DIR}/launch-streamer.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/streamer.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/streamer.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
      <key>HOME</key>
      <string>${HOME}</string>
    </dict>
  </dict>
</plist>
EOF

cat >"${NATIVE_BROWSER_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${NATIVE_BROWSER_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>${SCRIPT_DIR}/launch-native-browser.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
      <key>SuccessfulExit</key>
      <false/>
    </dict>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/native-browser.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/native-browser.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
      <key>HOME</key>
      <string>${HOME}</string>
    </dict>
  </dict>
</plist>
EOF

cat >"${NATIVE_BROWSER_STREAMER_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${NATIVE_BROWSER_STREAMER_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>${SCRIPT_DIR}/launch-native-browser-streamer.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/native-browser-streamer.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/native-browser-streamer.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
      <key>HOME</key>
      <string>${HOME}</string>
    </dict>
  </dict>
</plist>
EOF

cat >"${SPRUTHUB_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${SPRUTHUB_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>${SCRIPT_DIR}/launch-spruthub-forwarder.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
      <key>SuccessfulExit</key>
      <false/>
    </dict>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/spruthub.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/spruthub.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
      <key>HOME</key>
      <string>${HOME}</string>
    </dict>
  </dict>
</plist>
EOF

launchctl bootout "gui/${UID_VALUE}/${TTYD_LABEL}" 2>/dev/null || true
launchctl bootout "gui/${UID_VALUE}/${CADDY_LABEL}" 2>/dev/null || true
launchctl bootout "gui/${UID_VALUE}/${BROWSER_LABEL}" 2>/dev/null || true
launchctl bootout "gui/${UID_VALUE}/${WEBSOCKIFY_LABEL}" 2>/dev/null || true
launchctl bootout "gui/${UID_VALUE}/${STREAMER_LABEL}" 2>/dev/null || true
launchctl bootout "gui/${UID_VALUE}/${NATIVE_BROWSER_LABEL}" 2>/dev/null || true
launchctl bootout "gui/${UID_VALUE}/${NATIVE_BROWSER_STREAMER_LABEL}" 2>/dev/null || true
launchctl bootout "gui/${UID_VALUE}/${SPRUTHUB_LABEL}" 2>/dev/null || true

bootstrap_agent "${TTYD_LABEL}" "${TTYD_PLIST}"
bootstrap_agent "${CADDY_LABEL}" "${CADDY_PLIST}"
bootstrap_agent "${BROWSER_LABEL}" "${BROWSER_PLIST}"
bootstrap_agent "${WEBSOCKIFY_LABEL}" "${WEBSOCKIFY_PLIST}"
bootstrap_agent "${STREAMER_LABEL}" "${STREAMER_PLIST}"
bootstrap_agent "${NATIVE_BROWSER_LABEL}" "${NATIVE_BROWSER_PLIST}"
bootstrap_agent "${NATIVE_BROWSER_STREAMER_LABEL}" "${NATIVE_BROWSER_STREAMER_PLIST}"
bootstrap_agent "${SPRUTHUB_LABEL}" "${SPRUTHUB_PLIST}"
kickstart_agent "${TTYD_LABEL}" "${TTYD_PLIST}"
kickstart_agent "${CADDY_LABEL}" "${CADDY_PLIST}"
kickstart_agent "${BROWSER_LABEL}" "${BROWSER_PLIST}"
kickstart_agent "${WEBSOCKIFY_LABEL}" "${WEBSOCKIFY_PLIST}"
kickstart_agent "${STREAMER_LABEL}" "${STREAMER_PLIST}"
kickstart_agent "${NATIVE_BROWSER_LABEL}" "${NATIVE_BROWSER_PLIST}"
kickstart_agent "${NATIVE_BROWSER_STREAMER_LABEL}" "${NATIVE_BROWSER_STREAMER_PLIST}"
kickstart_agent "${SPRUTHUB_LABEL}" "${SPRUTHUB_PLIST}"

# Старый прямой порт Remote Browser больше не используется: Browser живёт внутри :8443.
tailscale funnel --https=9443 off >/dev/null 2>&1 || true

tailscale funnel --bg --yes "http://127.0.0.1:${CADDY_PORT:-8080}"
tailscale funnel --https=8443 --bg --yes "http://127.0.0.1:${CADDY_TERMINAL_PORT:-8081}"
tailscale funnel --https=10000 --bg --yes "http://127.0.0.1:${CADDY_SPRUTHUB_PORT:-8082}"

printf '\n== direct terminal ==\n'
tailscale funnel status
