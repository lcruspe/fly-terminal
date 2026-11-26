#!/bin/bash
# Init scripts may run before nginx has regenerated its web UI/config.
(
  for _ in $(seq 1 120); do
    if ss -ltn | grep -q ":${CUSTOM_PORT:-3000} "; then
      /bin/bash /opt/fly-terminal-downloads/start.sh
      nginx -t && nginx -s reload
      exit
    fi
    sleep 1
  done
) >>/tmp/fly-downloads-boot.log 2>&1 &
