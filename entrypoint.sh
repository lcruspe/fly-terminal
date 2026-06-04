#!/bin/sh
set -e

log_info() {
    printf '[fly-terminal] %s\n' "$*"
}

read_cgroup_memory_limit() {
    for candidate in /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory/memory.limit_in_bytes; do
        if [ -r "$candidate" ]; then
            cat "$candidate"
            return 0
        fi
    done
    return 1
}

read_cgroup_memory_current() {
    for candidate in /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory/memory.usage_in_bytes; do
        if [ -r "$candidate" ]; then
            cat "$candidate"
            return 0
        fi
    done
    return 1
}

read_meminfo_kb() {
    awk -v key="$1" '$1 == key ":" { print $2; exit }' /proc/meminfo 2>/dev/null
}

format_bytes() {
    value="$1"
    if [ -z "$value" ] || [ "$value" = "max" ]; then
        printf '%s' "${value:-unknown}"
        return 0
    fi

    awk -v bytes="$value" '
        function human(x) {
            split("B KiB MiB GiB TiB", units, " ")
            unit = 1
            while (x >= 1024 && unit < 5) {
                x /= 1024
                unit++
            }
            return sprintf("%.1f %s", x, units[unit])
        }
        BEGIN { print human(bytes) }
    '
}

log_runtime_diagnostics() {
    [ "${FLY_TERMINAL_DIAGNOSTICS:-1}" = "0" ] && return 0

    memory_limit="$(read_cgroup_memory_limit 2>/dev/null || true)"
    memory_current="$(read_cgroup_memory_current 2>/dev/null || true)"
    mem_available_kb="$(read_meminfo_kb MemAvailable)"
    swap_total_kb="$(read_meminfo_kb SwapTotal)"
    swap_free_kb="$(read_meminfo_kb SwapFree)"

    log_info "startup config: port=${PORT}, ttyd_port=${TTYD_PORT}, base_path=${TERMINAL_BASE_PATH}, tailscale=$( [ -n "${TS_AUTHKEY}" ] && printf enabled || printf disabled )"
    log_info "terminal limits: scrollback=${TERMINAL_SCROLLBACK}, histsize=${FLY_TERMINAL_HISTSIZE}, histfile=${FLY_TERMINAL_HISTFILESIZE}, tmux_history=${FLY_TERMINAL_TMUX_HISTORY_LIMIT}, session_ttl_min=${FLY_TERMINAL_SESSION_IDLE_TTL_MINUTES}"
    log_info "memory: limit=$(format_bytes "$memory_limit"), current=$(format_bytes "$memory_current"), available_kib=${mem_available_kb:-unknown}"
    log_info "swap: total_kib=${swap_total_kb:-0}, free_kib=${swap_free_kb:-0}"
    ps -A -o pid,ppid,rss,stat,comm 2>/dev/null | sed 's/^/[fly-terminal] process /' || true
}

if [ -n "${TS_AUTHKEY}" ]; then
    log_info "Starting Tailscale daemon..."
    # Запуск демона Tailscale в userspace режиме (без tun устройства)
    tailscaled --tun=userspace-networking --socks5-server=localhost:1055 &
    TAILSCALED_PID=$!

    # Ждем запуска демона
    sleep 2

    log_info "Connecting to Tailscale network..."
    # Авторизация в Tailnet с эфемерным ключом
    tailscale up --authkey="${TS_AUTHKEY}" --hostname=fly-terminal --accept-routes

    log_info "Tailscale connected. Starting web terminal..."
else
    rm -f /etc/ssh/ssh_config.d/tailscale.conf
    log_info "TS_AUTHKEY is not set. Starting web terminal without Tailscale..."
fi

# Railway использует переменную PORT
PORT=${PORT:-7681}
TTYD_PORT=${TTYD_PORT:-7682}
TERMINAL_BASE_PATH=${TERMINAL_BASE_PATH:-/terminal}
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export LC_CTYPE="${LC_CTYPE:-C.UTF-8}"
export TERM="${TERM:-xterm-256color}"
export FLY_TERMINAL_DIAGNOSTICS="${FLY_TERMINAL_DIAGNOSTICS:-1}"
export FLY_TERMINAL_HISTSIZE="${FLY_TERMINAL_HISTSIZE:-5000}"
export FLY_TERMINAL_HISTFILESIZE="${FLY_TERMINAL_HISTFILESIZE:-10000}"
export FLY_TERMINAL_SESSION_IDLE_TTL_MINUTES="${FLY_TERMINAL_SESSION_IDLE_TTL_MINUTES:-120}"
export FLY_TERMINAL_TMUX_HISTORY_LIMIT="${FLY_TERMINAL_TMUX_HISTORY_LIMIT:-5000}"
export FLY_TERMINAL_CONTROL_PORT="${FLY_TERMINAL_CONTROL_PORT:-7683}"
export FLY_TERMINAL_CONTROL_SCRIPT="${FLY_TERMINAL_CONTROL_SCRIPT:-/usr/local/bin/session-control.py}"
export FLY_TERMINAL_SESSION_SCRIPT="${FLY_TERMINAL_SESSION_SCRIPT:-/usr/local/bin/terminal-session.sh}"
export TTYD_BIN="${TTYD_BIN:-ttyd}"

DEFAULT_TERMINAL_THEME='{"background":"#f7f3e8","foreground":"#28231f","cursor":"#c65f2f","selectionBackground":"#e7d6b3","black":"#28231f","red":"#b84d43","green":"#587a45","yellow":"#a9762c","blue":"#3f6f9f","magenta":"#8a5c8f","cyan":"#3f8585","white":"#f4ead8","brightBlack":"#6f665c","brightRed":"#d85f4f","brightGreen":"#6f934f","brightYellow":"#c89136","brightBlue":"#5688bf","brightMagenta":"#a775aa","brightCyan":"#56a0a0","brightWhite":"#fff8eb"}'

: "${TERMINAL_THEME:=$DEFAULT_TERMINAL_THEME}"
: "${TERMINAL_FONT_SIZE:=12}"
: "${TERMINAL_FONT_FAMILY:=JetBrains Mono, Menlo, Monaco, monospace}"
: "${TERMINAL_SCROLLBACK:=4000}"

log_runtime_diagnostics

export TTYD_PORT TERMINAL_BASE_PATH TERMINAL_THEME TERMINAL_FONT_SIZE TERMINAL_FONT_FAMILY TERMINAL_SCROLLBACK TERMINAL_USER TERMINAL_PASSWORD
/usr/local/bin/run-ttyd-stack.sh &
TTYD_PID=$!

cat >/tmp/nginx.conf <<EOF
events {}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;

    server {
        listen ${PORT};
        server_name _;
        root /usr/share/nginx/html;
        index index.html;

        location / {
            try_files \$uri \$uri/ /index.html;
        }

        location = ${TERMINAL_BASE_PATH} {
            return 302 ${TERMINAL_BASE_PATH}/;
        }

        location ${TERMINAL_BASE_PATH}/ {
            proxy_pass http://127.0.0.1:${TTYD_PORT}${TERMINAL_BASE_PATH}/\$is_args\$args;
            proxy_http_version 1.1;
            proxy_set_header Upgrade \$http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_read_timeout 86400;
        }

        location /api/ {
            proxy_pass http://127.0.0.1:${FLY_TERMINAL_CONTROL_PORT};
            proxy_http_version 1.1;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
        }
    }
}
EOF

trap 'kill "$TTYD_PID" 2>/dev/null || true; [ -n "${TAILSCALED_PID:-}" ] && kill "$TAILSCALED_PID" 2>/dev/null || true' INT TERM
exec nginx -c /tmp/nginx.conf -g 'daemon off;'
