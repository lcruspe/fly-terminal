FROM debian:bookworm-slim

# Установка ttyd, Tailscale и необходимых утилит
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    iptables \
    wget \
    && wget -qO- https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 > /usr/local/bin/ttyd \
    && chmod +x /usr/local/bin/ttyd \
    && curl -fsSL https://tailscale.com/install.sh | sh \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Копируем скрипт запуска
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Railway использует переменную PORT
ENV PORT=7681
EXPOSE $PORT

ENTRYPOINT ["/entrypoint.sh"]
