#!/bin/zsh
# Restore the single pre-migration Caddyfile. Never change Oracle or user files.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${DIR}/.." && pwd)"
BACKUP="${HOME}/.config/fly-terminal-mac/rollback/session-auth/Caddyfile"
if [ ! -s "${BACKUP}" ]; then
  echo "Rollback Caddyfile not found: ${BACKUP}" >&2
  exit 1
fi
if ! /usr/bin/grep -q 'basic_auth @gatewayProtected' "${BACKUP}"; then
  echo "Rollback file does not contain the original Basic Auth gate; aborting" >&2
  exit 1
fi
cp "${BACKUP}" "${DIR}/Caddyfile"
launchctl kickstart -k "gui/$(id -u)/ai.kruspe.fly-terminal.caddy"
sleep 1
status="$(/usr/bin/curl --connect-timeout 3 --max-time 5 -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/ || true)"
if [ "${status}" != "401" ]; then
  echo "Rollback restarted Caddy, but expected Basic Auth 401; received ${status}" >&2
  exit 1
fi
echo "Rollback complete: prior Basic Auth is active on the gateway."
echo "The working tree now contains the restored Caddyfile; leave untracked files unchanged."
