FROM ttsl0922/ttyd:latest

# Установка Tailscale и необходимых утилит
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    iptables \
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
