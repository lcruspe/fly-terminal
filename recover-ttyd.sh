#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec /usr/bin/env python3 "${SCRIPT_DIR}/tools/recover_ttyd_funnel.py" "$@"
