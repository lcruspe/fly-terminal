#!/bin/sh
set -e

prune_stale_tmux_sessions() {
    ttl_minutes="${FLY_TERMINAL_SESSION_IDLE_TTL_MINUTES:-120}"

    case "$ttl_minutes" in
        ''|*[!0-9]*)
            return 0
            ;;
        0)
            return 0
            ;;
    esac

    now_epoch="$(date +%s 2>/dev/null || printf '0')"
    [ "$now_epoch" -gt 0 ] || return 0

    tmux list-sessions -F '#{session_name}|#{session_attached}|#{session_activity}' 2>/dev/null | \
    while IFS='|' read -r session_name session_attached session_activity; do
        [ -n "$session_name" ] || continue
        [ "$session_attached" = "0" ] || continue
        case "$session_activity" in
            ''|*[!0-9]*)
                continue
                ;;
        esac

        session_age_seconds=$((now_epoch - session_activity))
        if [ "$session_age_seconds" -gt $((ttl_minutes * 60)) ]; then
            tmux kill-session -t "$session_name" >/dev/null 2>&1 || true
        fi
    done
}

trim_history_file() {
    history_limit="${FLY_TERMINAL_HISTFILESIZE:-10000}"

    case "$history_limit" in
        ''|*[!0-9]*)
            return 0
            ;;
        0)
            : >"$HISTORY_FILE"
            return 0
            ;;
    esac

    [ -f "$HISTORY_FILE" ] || return 0

    line_count="$(wc -l <"$HISTORY_FILE" 2>/dev/null || printf '0')"
    case "$line_count" in
        ''|*[!0-9]*)
            return 0
            ;;
    esac

    if [ "$line_count" -gt "$history_limit" ]; then
        tmp_history="${HISTORY_FILE}.tmp"
        tail -n "$history_limit" "$HISTORY_FILE" >"$tmp_history"
        mv "$tmp_history" "$HISTORY_FILE"
    fi
}

apply_tmux_runtime_limits() {
    tmux_history_limit="${FLY_TERMINAL_TMUX_HISTORY_LIMIT:-5000}"

    case "$tmux_history_limit" in
        ''|*[!0-9]*)
            return 0
            ;;
    esac

    tmux start-server >/dev/null 2>&1 || true
    tmux set-option -g history-limit "$tmux_history_limit" >/dev/null 2>&1 || true
    tmux set-option -g mouse on >/dev/null 2>&1 || true
}

# Robust SESSION_ID extraction
# 1. From command line argument
# 2. From TTYD_QUERY_arg (ttyd environment)
# 3. From TTYD_QUERY_STRING (parsing manually)
# 4. Fallback to default
RAW_ID="${1:-${TTYD_QUERY_arg:-}}"

if [ -z "$RAW_ID" ] && [ -n "${TTYD_QUERY_STRING:-}" ]; then
    RAW_ID=$(echo "$TTYD_QUERY_STRING" | sed -n 's/.*arg=\([^&]*\).*/\1/p')
fi

SESSION_ID="${RAW_ID:-default}"

# Debug logging
echo "--- $(date) ---" >> /tmp/terminal-session.log
echo "RAW_ID: $RAW_ID" >> /tmp/terminal-session.log
echo "SESSION_ID: $SESSION_ID" >> /tmp/terminal-session.log
echo "All Args: $@" >> /tmp/terminal-session.log

# Clean session ID to be safe for tmux
SESSION_ID=$(echo "$SESSION_ID" | tr -dc 'A-Za-z0-9._-')
[ -z "$SESSION_ID" ] && SESSION_ID="default"

HISTORY_ROOT=${FLY_TERMINAL_HISTORY_DIR:-/data/bash_history}

if ! mkdir -p "$HISTORY_ROOT" 2>/dev/null; then
    HISTORY_ROOT="$HOME/.fly-terminal-history"
    mkdir -p "$HISTORY_ROOT"
fi

HISTORY_FILE=${FLY_TERMINAL_HISTFILE:-$HISTORY_ROOT/shared_history}
touch "$HISTORY_FILE"
export HISTFILE="$HISTORY_FILE"

prune_stale_tmux_sessions
trim_history_file
apply_tmux_runtime_limits

exec tmux -u new-session -A -s "fly-terminal-$SESSION_ID" \
    env HISTFILE="$HISTORY_FILE" bash --rcfile /etc/fly-terminal.bashrc
