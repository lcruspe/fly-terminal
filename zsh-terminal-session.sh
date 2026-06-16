#!/bin/sh
set -eu

RAW_ID="${1:-${TTYD_QUERY_arg:-default}}"

if [ -z "$RAW_ID" ] && [ -n "${TTYD_QUERY_STRING:-}" ]; then
    RAW_ID=$(echo "$TTYD_QUERY_STRING" | sed -n 's/.*arg=\([^&]*\).*/\1/p')
fi

SESSION_ID="$(printf '%s' "${RAW_ID:-default}" | tr -dc 'A-Za-z0-9._-')"
[ -n "$SESSION_ID" ] || SESSION_ID="default"

{
    echo "--- $(date) ---"
    echo "RAW_ID: $RAW_ID"
    echo "SESSION_ID: $SESSION_ID"
    echo "All Args: $*"
} >> /tmp/terminal-session.log

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
TMUX_BIN="${TMUX_BIN:-$(command -v tmux)}"
ZSH_BIN="${ZSH_BIN:-/bin/zsh}"

"$TMUX_BIN" start-server >/dev/null 2>&1 || true
"$TMUX_BIN" set-option -g mouse on >/dev/null 2>&1 || true

exec "$TMUX_BIN" -u new-session -A -s "fly-terminal-$SESSION_ID" "$ZSH_BIN" -l
