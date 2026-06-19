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

FLY_BROWSER_IMAGE="${FLY_BROWSER_IMAGE:-lscr.io/linuxserver/chromium:latest}"
FLY_BROWSER_HOST_PORT="${FLY_BROWSER_HOST_PORT:-7690}"
FLY_BROWSER_CONTAINER_PORT="${FLY_BROWSER_CONTAINER_PORT:-3000}"
FLY_BROWSER_PROFILE_DIR="${FLY_BROWSER_PROFILE_DIR:-${HOME}/.local/share/fly-terminal/browser-profile}"
FLY_BROWSER_CONTAINER_NAME="${FLY_BROWSER_CONTAINER_NAME:-fly-terminal-browser}"
FLY_BROWSER_PROFILE_VOLUME="${FLY_BROWSER_PROFILE_VOLUME:-fly-terminal-browser-profile}"
FLY_BROWSER_PASSWORD="${FLY_BROWSER_PASSWORD:-${TERMINAL_PASSWORD:-password}}"
FLY_BROWSER_CHROME_PROFILE_DIR="${FLY_BROWSER_CHROME_PROFILE_DIR:-/config/.config/chromium}"
FLY_BROWSER_CHROME_CLI="${FLY_BROWSER_CHROME_CLI:-${FLY_BROWSER_CHROME_PROFILE_DIR} --no-default-browser-check --disable-dev-shm-usage --disable-field-trial-config --password-store=basic}"

wait_for_docker() {
  local timeout="${FLY_BROWSER_DOCKER_WAIT_SECONDS:-180}"
  local start now
  start="$(date +%s)"

  while ! docker info >/dev/null 2>&1; do
    now="$(date +%s)"
    if [ $((now - start)) -ge "$timeout" ]; then
      echo "Docker daemon is not ready after ${timeout}s." >&2
      docker info >/dev/null
      return 1
    fi
    sleep 2
  done
}

patch_selkies_performance_profile() {
  local attempt
  for attempt in {1..30}; do
    if docker exec "${FLY_BROWSER_CONTAINER_NAME}" test -f /usr/share/selkies/web/index.html 2>/dev/null; then
      break
    fi
    sleep 1
  done
  docker exec "${FLY_BROWSER_CONTAINER_NAME}" test -f /usr/share/selkies/web/index.html || {
    echo "WARNING: Selkies HTML not ready, performance profile was not applied." >&2
    return 0
  }
  docker exec -i -u root "${FLY_BROWSER_CONTAINER_NAME}" python3 - <<'PY'
from pathlib import Path

path = Path("/usr/share/selkies/web/index.html")
html = path.read_text()
marker = "fly-terminal-performance-profile-v1"
if marker in html:
    raise SystemExit(0)

target = '<script type="module" crossorigin src="./assets/'
target_index = html.find(target)
if target_index < 0:
    raise SystemExit("Selkies module bundle tag not found")

patch = '''<script id="fly-terminal-performance-profile-v1">
(function () {
  var localHosts = { "127.0.0.1": true, "localhost": true, "::1": true };
  var isLocal = Boolean(localHosts[window.location.hostname]);
  var storagePrefix = window.location.href
    .split("#")[0]
    .replace(/[^a-zA-Z0-9.-_]/g, "_");
  var profile = isLocal ? {
    framerate: "60",
    h264_crf: "22",
    useCssScaling: "false",
    use_css_scaling: "false",
    use_browser_cursors: "false"
  } : {
    framerate: "30",
    h264_crf: "30",
    useCssScaling: "true",
    use_css_scaling: "true",
    use_browser_cursors: "true"
  };

  profile.encoder = "x264enc";
  profile.rate_control_mode = "crf";
  profile.h264_fullcolor = "false";
  profile.h264_streaming_mode = "false";
  profile.scaleLocallyManual = "true";

  Object.keys(profile).forEach(function (key) {
    window.localStorage.setItem(storagePrefix + "_" + key, profile[key]);
  });
  window.__flyTerminalBrowserProfile = isLocal ? "quality" : "speed";
})();
</script>'''

path.write_text(html[:target_index] + patch + html[target_index:])
PY
}

container_has_required_settings() {
  local env_dump
  env_dump="$(docker inspect "${FLY_BROWSER_CONTAINER_NAME}" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null)" || return 1
  grep -qx 'SELKIES_AUDIO_ENABLED=false|locked' <<<"${env_dump}" &&
    grep -qx 'SELKIES_MICROPHONE_ENABLED=false|locked' <<<"${env_dump}" &&
    grep -qx 'SELKIES_USE_BROWSER_CURSORS=true' <<<"${env_dump}" &&
    grep -qx "CHROME_CLI=${FLY_BROWSER_CHROME_CLI}" <<<"${env_dump}"
}

patch_kasmvnc_html() {
  docker exec "${FLY_BROWSER_CONTAINER_NAME}" test -f /usr/share/kasmvnc/www/index.html || return 0
  docker exec -i -u root "${FLY_BROWSER_CONTAINER_NAME}" python3 - <<'PY'
from pathlib import Path

path = Path("/usr/share/kasmvnc/www/index.html")
html = path.read_text()
marker = "fly-terminal-kasmvnc-error-suppressor"
if marker in html:
    raise SystemExit(0)

target = '<script type="module" crossorigin src="./main.bundle.js"></script>'
if target not in html:
    raise SystemExit("KasmVNC main bundle tag not found")

patch = '''<script id="fly-terminal-kasmvnc-error-suppressor">
(function () {
  function isKasmTransientError(value) {
    var text = String(value && (value.message || value.reason || value.error || value) || "");
    return text.indexOf("lastActiveAt") !== -1 ||
      text.indexOf("Cannot read properties of undefined") !== -1;
  }

  function hideKasmErrorDialog() {
    try {
      var dialog = document.getElementById("noVNC_fallback_error");
      var message = document.getElementById("noVNC_fallback_errormsg");
      if (!dialog) return;
      if (!message || isKasmTransientError(message.textContent)) {
        dialog.style.setProperty("display", "none", "important");
        dialog.setAttribute("aria-hidden", "true");
      }
    } catch (_) {}
  }

  window.addEventListener("error", function (event) {
    if (!isKasmTransientError(event && (event.error || event.message))) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    hideKasmErrorDialog();
    return true;
  }, true);

  window.addEventListener("unhandledrejection", function (event) {
    if (!isKasmTransientError(event && event.reason)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    hideKasmErrorDialog();
    return true;
  }, true);

  if (document.documentElement) {
    new MutationObserver(hideKasmErrorDialog).observe(document.documentElement, {
      childList: true,
      subtree: true
    });
  }
})();
</script>'''

path.write_text(html.replace(target, patch + target, 1))
PY
}

start_kasm_chrome() {
  docker exec "${FLY_BROWSER_CONTAINER_NAME}" test -f /usr/share/kasmvnc/www/index.html || return 0
  docker exec -d "${FLY_BROWSER_CONTAINER_NAME}" sh -lc '
export DISPLAY="${DISPLAY:-:1}"
export HOME="${HOME:-/home/kasm-user}"

for _ in $(seq 1 30); do
  xset q >/dev/null 2>&1 && break
  sleep 1
done

ps -eo pid=,args= |
  awk "/systemctl --user list-jobs/ && !/awk/ { print \$1 }" |
  xargs -r kill 2>/dev/null || true

(
  for _ in $(seq 1 30); do
    ps -eo pid=,args= |
      awk "/systemctl --user list-jobs/ && !/awk/ { print \$1 }" |
      xargs -r kill 2>/dev/null || true
    sleep 1
  done
) >/tmp/fly-terminal-systemctl-watchdog.log 2>&1 &

if ps -eo args= |
  awk "/\\/opt\\/google\\/chrome\\/chrome / && !/sh -lc/ && !/awk/ { found = 1 } END { exit found ? 0 : 1 }"; then
  exit 0
fi

exec /usr/bin/google-chrome \
  --no-first-run \
  --disable-dev-shm-usage \
  --start-maximized \
  --single-process \
  --no-zygote \
  --disable-gpu \
  --disable-software-rasterizer \
  --disable-crash-reporter \
  --disable-crashpad \
  --disable-breakpad \
  --noerrdialogs \
  >/tmp/fly-terminal-chrome.log 2>&1
'
}

unblock_linuxserver_selkies() {
  docker exec "${FLY_BROWSER_CONTAINER_NAME}" test -d /run/service/svc-selkies || return 0
  docker exec -u root "${FLY_BROWSER_CONTAINER_NAME}" sh -lc '
touch /dev/shm/audio.lock
s6-svc -r /run/service/svc-selkies 2>/dev/null || true
'
}

patch_selkies_input() {
  # Patch Selkies input_handler.py so Cyrillic text is batched and not dropped.
  # Uses tools/patch_selkies_xtest.py copied into the container.
  local script_src="${SCRIPT_DIR}/../tools/patch_selkies_xtest.py"
  if [ ! -f "$script_src" ]; then
    echo "WARNING: patch_selkies_xtest.py not found, skipping." >&2
    return 0
  fi
  docker cp "$script_src" "${FLY_BROWSER_CONTAINER_NAME}:/tmp/patch_selkies_xtest.py" 2>/dev/null || true
  if docker exec -u root "${FLY_BROWSER_CONTAINER_NAME}" python3 /tmp/patch_selkies_xtest.py 2>&1; then
    echo "selkies input: optimized handler ready"
    # Restart svc-selkies to reload the patched module
    if docker exec "${FLY_BROWSER_CONTAINER_NAME}" test -d /run/service/svc-selkies 2>/dev/null; then
      docker exec -u root "${FLY_BROWSER_CONTAINER_NAME}" s6-svc -r /run/service/svc-selkies 2>/dev/null || true
    fi
  else
    echo "WARNING: selkies input patch skipped (already patched or file not found)" >&2
  fi
}

mkdir -p "${FLY_BROWSER_PROFILE_DIR}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required for fly-terminal browser module." >&2
  exit 1
fi

wait_for_docker

if docker ps --format '{{.Names}}' | grep -qx "${FLY_BROWSER_CONTAINER_NAME}"; then
  if container_has_required_settings; then
    patch_kasmvnc_html
    patch_selkies_performance_profile
    patch_selkies_input
    start_kasm_chrome
    unblock_linuxserver_selkies
    exit 0
  fi
  docker rm -f "${FLY_BROWSER_CONTAINER_NAME}" >/dev/null
fi

if docker ps -a --format '{{.Names}}' | grep -qx "${FLY_BROWSER_CONTAINER_NAME}"; then
  docker rm -f "${FLY_BROWSER_CONTAINER_NAME}" >/dev/null
fi

docker volume create "${FLY_BROWSER_PROFILE_VOLUME}" >/dev/null

case "${FLY_BROWSER_IMAGE}" in
  lscr.io/linuxserver/chromium*|linuxserver/chromium*)
    docker run -d \
      --name "${FLY_BROWSER_CONTAINER_NAME}" \
      --shm-size=1g \
      -p "127.0.0.1:${FLY_BROWSER_HOST_PORT}:${FLY_BROWSER_CONTAINER_PORT}" \
      -e "PUID=$(id -u)" \
      -e "PGID=$(id -g)" \
      -e "TZ=${TZ:-Europe/Moscow}" \
      -e "TITLE=Chromium" \
      -e "PIXELFLUX_WAYLAND=false" \
      -e "SELKIES_AUDIO_ENABLED=false|locked" \
      -e "SELKIES_MICROPHONE_ENABLED=false|locked" \
      -e "SELKIES_USE_BROWSER_CURSORS=true" \
      -e "CHROME_CLI=${FLY_BROWSER_CHROME_CLI}" \
      -v "${FLY_BROWSER_PROFILE_VOLUME}:/config" \
      "${FLY_BROWSER_IMAGE}" >/dev/null
    ;;
  *)
    docker run -d \
      --name "${FLY_BROWSER_CONTAINER_NAME}" \
      --shm-size=1g \
      -p "127.0.0.1:${FLY_BROWSER_HOST_PORT}:6901" \
      -e "VNC_PW=${FLY_BROWSER_PASSWORD}" \
      -e "DISABLE_CUSTOM_STARTUP=1" \
      -v "${FLY_BROWSER_PROFILE_VOLUME}:/home/kasm-user" \
      "${FLY_BROWSER_IMAGE}" >/dev/null
    ;;
esac

patch_kasmvnc_html
patch_selkies_performance_profile
patch_selkies_input
start_kasm_chrome
unblock_linuxserver_selkies
