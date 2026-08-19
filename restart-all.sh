#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== Killing all fly-terminal processes ==="
pkill -9 -f ttyd 2>/dev/null || true
pkill -9 -f caddy 2>/dev/null || true
pkill -9 -f session-control 2>/dev/null || true
sleep 2

# Force-clear all ports
for port in 7682 7683 8080; do
  lsof -ti:$port 2>/dev/null | xargs kill -9 2>/dev/null || true
done
sleep 2

echo "=== Checking ports ==="
for port in 7682 7683 8080; do
  if lsof -ti:$port 2>/dev/null; then
    echo "ERROR: Port $port still busy after cleanup!"
    exit 1
  fi
  echo "Port $port: FREE"
done

echo "=== Starting Caddy ==="
bash "${SCRIPT_DIR}/macos/launch-caddy.sh" &
CADDY_PID=$!
sleep 3

# Wait for Caddy to be ready
for i in {1..10}; do
  if curl -sk -o /dev/null -w '%{http_code}' http://localhost:8080/ 2>/dev/null | grep -q '401\|200'; then
    echo "Caddy ready (attempt $i)"
    break
  fi
  sleep 1
done

echo "=== Starting ttyd stack ==="
bash "${SCRIPT_DIR}/run-ttyd-stack.sh" &
TTYD_PID=$!
sleep 4

# Verify all services
echo "=== Verifying services ==="
echo -n "Caddy (8080): "
curl -sk -o /dev/null -w '%{http_code}' http://localhost:8080/ 2>/dev/null || echo "FAIL"
echo ""

echo -n "ttyd (7682): "
if lsof -ti:7682 > /dev/null 2>&1; then echo "OK"; else echo "NOT RUNNING"; fi

echo -n "session-control (7683): "
if lsof -ti:7683 > /dev/null 2>&1; then echo "OK"; else echo "NOT RUNNING"; fi

echo -n "browser upstream (7690): "
if lsof -ti:7690 > /dev/null 2>&1; then echo "OK"; else echo "NOT RUNNING"; fi

echo ""
echo "=== Done ==="
echo "Terminal: http://localhost:8080/terminal/"
echo "Browser:  http://localhost:8080/browser/"
echo "Auth: admin / dM5pozis"
