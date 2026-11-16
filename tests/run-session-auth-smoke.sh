#!/bin/zsh
# Staging-only test: never restarts or modifies the live Caddy/Oracle relay.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
set -a
source "${HOME}/.config/fly-terminal-mac/fly-terminal.env"
set +a
WORK="$(mktemp -d "${TMPDIR:-/tmp/}fly-auth-stage.XXXXXXXX")"
PIDS=()
cleanup() {
  for pid in "${PIDS[@]}"; do kill "${pid}" 2>/dev/null || true; done
  for pid in "${PIDS[@]}"; do wait "${pid}" 2>/dev/null || true; done
  rm -rf -- "${WORK}"
}
trap cleanup EXIT INT TERM
export CADDY_PORT=18080 CADDY_TERMINAL_PORT=18081 CADDY_SPRUTHUB_PORT=18082
export FLY_SESSION_AUTH_PORT=17685 FLY_GATEWAY_CONTROL_PORT=17684
export FLY_SESSION_DB="${WORK}/sessions.sqlite3"
export FLY_AUTH_SECRET="$(/opt/homebrew/bin/python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export FLY_TERMINAL_REPO_ROOT="${ROOT}"
# Prevent the staging Caddy instance from writing into the live Caddy state.
export XDG_CONFIG_HOME="${WORK}/xdg-config" XDG_DATA_HOME="${WORK}/xdg-data"
mkdir -p "${XDG_CONFIG_HOME}" "${XDG_DATA_HOME}"
export CADDY_BASIC_AUTH_USER="${TERMINAL_USER}"
export CADDY_BASIC_AUTH_HASH="$(printf '%s\n' "${TERMINAL_PASSWORD}" | /opt/homebrew/bin/caddy hash-password --algorithm bcrypt)"
if [[ "${FLY_SPRUTHUB_ENABLED:-0}" == 1 ]]; then
  export CADDY_SPRUTHUB_AUTH_USER="${FLY_SPRUTHUB_AUTH_USER}"
  export CADDY_SPRUTHUB_AUTH_HASH="$(printf '%s' "${FLY_SPRUTHUB_AUTH_HASH_B64}" | /usr/bin/base64 -D)"
else
  export CADDY_SPRUTHUB_AUTH_USER="__spruthub_disabled__"
  export CADDY_SPRUTHUB_AUTH_HASH="$(printf 'unused-%s' "${FLY_AUTH_SECRET}" | /opt/homebrew/bin/caddy hash-password --algorithm bcrypt)"
fi
for port in 18080 18081 18082 17684 17685; do
  if /usr/sbin/lsof -nP -iTCP:"${port}" -sTCP:LISTEN -t | /usr/bin/grep -q .; then
    echo "Staging port ${port} is occupied; refusing to touch it" >&2
    exit 1
  fi
done
/opt/homebrew/bin/python3 macos/session_auth.py >"${WORK}/auth.log" 2>&1 & PIDS+=($!)
/opt/homebrew/bin/python3 macos/gateway-control.py >"${WORK}/control.log" 2>&1 & PIDS+=($!)
/opt/homebrew/bin/caddy run --config macos/Caddyfile --adapter caddyfile >"${WORK}/caddy.log" 2>&1 & PIDS+=($!)
if ! /opt/homebrew/bin/python3 tests/smoke_session_auth.py; then
  echo 'Stage FAILED. Last lines of Caddy and auth logs:' >&2
  tail -25 "${WORK}/caddy.log" "${WORK}/auth.log" | sed -E 's/\$2[a-z]\$[^[:space:]]+/[redacted]/g' >&2
  exit 1
fi
