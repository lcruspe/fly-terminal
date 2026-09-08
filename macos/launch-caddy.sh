#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
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
export FLY_TERMINAL_REPO_ROOT="${REPO_ROOT}"
export XDG_DATA_HOME="${HOME}/.local/share/caddy"
mkdir -p "${XDG_DATA_HOME}"

# YT Transcriber uses a short-lived session cookie after Caddy Basic Auth.
# Its bootstrap endpoint verifies a shared secret. Prefer the Fly-terminal env,
# but reuse the installed transcriber LaunchAgent secret so the two services
# cannot silently drift after independent reinstalls.
if [ -z "${YT_BOOTSTRAP_SECRET:-}" ]; then
  YT_PLIST="${HOME}/Library/LaunchAgents/com.kruspe.yttranscriber.plist"
  if [ -f "${YT_PLIST}" ]; then
    YT_BOOTSTRAP_SECRET="$(/usr/libexec/PlistBuddy -c 'Print :EnvironmentVariables:YT_BOOTSTRAP_SECRET' "${YT_PLIST}" 2>/dev/null || true)"
    export YT_BOOTSTRAP_SECRET
  fi
fi
if [ -z "${YT_BOOTSTRAP_SECRET:-}" ]; then
  echo "Warning: YT_BOOTSTRAP_SECRET is unavailable; /yt-login will not bootstrap a transcriber session" >&2
fi

if [ -z "${TERMINAL_USER:-}" ] || [ -z "${TERMINAL_PASSWORD:-}" ]; then
  echo "TERMINAL_USER and TERMINAL_PASSWORD are required for Caddy basic auth" >&2
  exit 1
fi

export CADDY_BASIC_AUTH_USER="${TERMINAL_USER}"
export CADDY_BASIC_AUTH_HASH="$(printf '%s\n' "${TERMINAL_PASSWORD}" | /opt/homebrew/bin/caddy hash-password --algorithm bcrypt)"

if [ "${FLY_SPRUTHUB_ENABLED:-0}" = "1" ]; then
  if [ -z "${FLY_SPRUTHUB_AUTH_USER:-}" ] || [ -z "${FLY_SPRUTHUB_AUTH_HASH_B64:-}" ]; then
    echo "FLY_SPRUTHUB_AUTH_USER, FLY_SPRUTHUB_AUTH_HASH_B64 are required when FLY_SPRUTHUB_ENABLED=1" >&2
    exit 1
  fi
  if [ "${FLY_SPRUTHUB_AUTH_USER}" = "${TERMINAL_USER}" ]; then
    echo "FLY_SPRUTHUB_AUTH_USER must differ from TERMINAL_USER" >&2
    exit 1
  fi
  export CADDY_SPRUTHUB_AUTH_USER="${FLY_SPRUTHUB_AUTH_USER}"
  export CADDY_SPRUTHUB_AUTH_HASH="$(printf '%s' "${FLY_SPRUTHUB_AUTH_HASH_B64}" | /usr/bin/base64 -D)"
else
  export CADDY_SPRUTHUB_AUTH_USER="__spruthub_disabled__"
  export CADDY_SPRUTHUB_AUTH_HASH="$(printf '%s\n' "$(/usr/bin/uuidgen)$(/usr/bin/uuidgen)" | /opt/homebrew/bin/caddy hash-password --algorithm bcrypt)"
fi


exec /opt/homebrew/bin/caddy run \
  --config "${SCRIPT_DIR}/Caddyfile" \
  --adapter caddyfile
