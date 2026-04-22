#!/bin/sh
set -e

SESSION_ID=${1:-default}
shift || true

case "$SESSION_ID" in
    *[!A-Za-z0-9._-]*)
        SESSION_ID=default
        ;;
esac

exec tmux -u new-session -A -s "fly-terminal-$SESSION_ID" bash
