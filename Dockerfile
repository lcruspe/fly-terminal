FROM debian:bookworm-slim

# Установка ttyd, Tailscale и необходимых утилит
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    iptables \
    wget \
    openssh-client \
    netcat-openbsd \
    nginx \
    tmux \
    && wget -qO- https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 > /usr/local/bin/ttyd \
    && chmod +x /usr/local/bin/ttyd \
    && curl -fsSL https://tailscale.com/install.sh | sh \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Копируем скрипт запуска, SSH конфиг и веб-оболочку
COPY entrypoint.sh /entrypoint.sh
COPY ssh_config /etc/ssh/ssh_config.d/tailscale.conf
COPY tmux.conf /etc/tmux.conf
COPY terminal-session.sh /usr/local/bin/terminal-session.sh
COPY terminal-bashrc.sh /etc/fly-terminal.bashrc
COPY index.html /usr/share/nginx/html/index.html
RUN chmod +x /entrypoint.sh
RUN chmod +x /usr/local/bin/terminal-session.sh

# Railway использует переменную PORT
ENV PORT=7681
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV LC_CTYPE=C.UTF-8
ENV TERM=xterm-256color
EXPOSE $PORT

ENTRYPOINT ["/entrypoint.sh"]
