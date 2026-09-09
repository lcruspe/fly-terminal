#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RELAY_USER="${FLY_ORACLE_RELAY_USER:-opc}"
KEY_COMMENT="${FLY_ORACLE_RELAY_KEY_COMMENT:-fly-terminal-oracle-relay}"
AUTH_FILE="/home/${RELAY_USER}/.ssh/authorized_keys"

if [ "$(id -u)" -ne 0 ]; then
  exec sudo -E "$0" "$@"
fi

install -o root -g caddy -m 640 "${SCRIPT_DIR}/Caddyfile" /etc/caddy/Caddyfile
python3 - "${AUTH_FILE}" "${KEY_COMMENT}" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
comment = sys.argv[2]
lines = path.read_text().splitlines()
options = 'restrict,port-forwarding,permitlisten="127.0.0.1:18080",permitlisten="127.0.0.1:18081",permitlisten="127.0.0.1:18082",command="/usr/bin/false"'
matched = False
for i, line in enumerate(lines):
    if line.rstrip().endswith(' ' + comment):
        parts = line.split()
        key_index = next((j for j, value in enumerate(parts) if value.startswith('ssh-')), None)
        if key_index is None:
            raise SystemExit('relay public key not found in authorized_keys line')
        lines[i] = options + ' ' + ' '.join(parts[key_index:])
        matched = True
if not matched:
    raise SystemExit('relay key comment not found: ' + comment)
path.write_text('\n'.join(lines) + '\n')
PY

chown "${RELAY_USER}:${RELAY_USER}" "${AUTH_FILE}"
chmod 600 "${AUTH_FILE}"

/usr/local/bin/caddy validate --config /etc/caddy/Caddyfile
firewall-cmd --permanent --add-service=https >/dev/null
firewall-cmd --permanent --add-port=8443/tcp >/dev/null
firewall-cmd --permanent --add-port=10000/tcp >/dev/null
firewall-cmd --reload >/dev/null

systemctl enable caddy-oracle-relay.service >/dev/null
systemctl restart caddy-oracle-relay.service
systemctl disable --now fly-terminal.service >/dev/null 2>&1 || true

printf 'Oracle relay configured.\n'
printf 'Caddy: %s\n' "$(systemctl is-active caddy-oracle-relay.service)"
printf 'Legacy Fly Terminal: %s\n' "$(systemctl is-active fly-terminal.service 2>/dev/null || true)"
ss -lnt | grep -E ':(443|8443|10000|18080|18081|18082)\b' || true
