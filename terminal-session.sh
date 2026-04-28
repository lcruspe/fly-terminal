#!/bin/sh
set -e

SESSION_ID=${1:-default}
shift || true

case "$SESSION_ID" in
    *[!A-Za-z0-9._-]*)
        SESSION_ID=default
        ;;
esac

HISTORY_ROOT=${FLY_TERMINAL_HISTORY_DIR:-/data/bash_history}

if ! mkdir -p "$HISTORY_ROOT" 2>/dev/null; then
    HISTORY_ROOT="$HOME/.fly-terminal-history"
    mkdir -p "$HISTORY_ROOT"
fi

HISTORY_FILE=${FLY_TERMINAL_HISTFILE:-$HISTORY_ROOT/shared_history}
touch "$HISTORY_FILE"
export HISTFILE="$HISTORY_FILE"

exec tmux -u new-session -A -s "fly-terminal-$SESSION_ID" \
    env HISTFILE="$HISTORY_FILE" bash --rcfile /etc/fly-terminal.bashrc
