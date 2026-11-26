#!/bin/bash
set -eu
python3 /opt/fly-terminal-downloads/install.py
# Restart a stale worker when the deployed bridge changes.
hash=$(sha256sum /opt/fly-terminal-downloads/bridge.py | cut -d" " -f1)
previous=$(cat /tmp/fly-downloads-version 2>/dev/null || true)
if [ "$hash" != "$previous" ]; then
  printf "%s" "$hash" > /tmp/fly-downloads-version
  pkill -TERM -f "^/lsiopy/bin/python /opt/fly-terminal-downloads/bridge.py$" || true
fi
# Protect against duplicate supervisors; the service is unprivileged and loopback-only.
if ! ss -ltn | grep -q ':8789 '; then
  flock -n /tmp/fly-downloads-supervisor.lock /bin/bash -c '
    while true; do
      s6-setuidgid abc /lsiopy/bin/python /opt/fly-terminal-downloads/bridge.py
      sleep 2
    done
  ' </dev/null >>/tmp/fly-downloads.log 2>&1 &
fi
