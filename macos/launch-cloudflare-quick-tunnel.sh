#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

PHYSICAL_IP="$(/usr/sbin/ipconfig getifaddr en1 2>/dev/null || true)"
if [ -z "${PHYSICAL_IP}" ]; then
  echo "Unable to determine the physical Wi-Fi address on en1" >&2
  exit 1
fi

if ! /usr/bin/curl -sS --connect-timeout 3 --max-time 5 \
  -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/ | /usr/bin/grep -q '^401$'; then
  echo "Caddy health check failed on http://127.0.0.1:8080/" >&2
  exit 1
fi

exec /opt/homebrew/bin/cloudflared tunnel \
  --no-autoupdate \
  --metrics 127.0.0.1:49312 \
  --edge-ip-version 4 \
  --edge-bind-address "${PHYSICAL_IP}" \
  --loglevel info \
  --url http://127.0.0.1:8080
