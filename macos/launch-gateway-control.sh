#!/bin/zsh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
set -a
source "${HOME}/.config/fly-terminal-mac/fly-terminal.env"
set +a
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
exec /opt/homebrew/bin/python3 "${SCRIPT_DIR}/gateway-control.py"
