#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

if ! /usr/bin/curl -sS --connect-timeout 3 --max-time 5 \
  -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/ | /usr/bin/grep -q '^401$'; then
  echo "Caddy health check failed on http://127.0.0.1:8080/" >&2
  exit 1
fi

# Signed, SHA256-verified binary staged outside Homebrew while its API is unreachable.
# Use system routing: binding to the Wi-Fi source IP fails when VPN routes change.
exec "$HOME/Library/Application Support/FlyTerminal/cloudflared/2026.10.3/cloudflared" tunnel \
  --no-autoupdate \
  --metrics 127.0.0.1:49312 \
  --edge-ip-version 4 \
  --protocol http2 \
  --loglevel info \
  --url http://127.0.0.1:8080
