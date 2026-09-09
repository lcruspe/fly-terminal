# Oracle relay

Oracle VM используется только как публичный HTTPS/TURN-ретранслятор для direct macOS Fly Terminal. Само приложение на Oracle больше не запускается.

## Схема

| Публичный Oracle URL | Caddy на Oracle | Reverse SSH | Сервис на Mac mini |
| --- | --- | --- | --- |
| `https://129-158-49-130.sslip.io/` | `127.0.0.1:18080` | `18080 -> 8080` | шлюз сервисов |
| `https://129-158-49-130.sslip.io:8443/` | `127.0.0.1:18081` | `18081 -> 8081` | Fly Terminal + Remote Desktop/Browser |
| `https://129-158-49-130.sslip.io:10000/` | `127.0.0.1:18082` | `18082 -> 8082` | Sprut.Hub |

На Mac туннель запускает `macos/launch-oracle-relay.sh` через LaunchAgent `ai.kruspe.fly-terminal.oracle-relay`. Все три remote-forward должны создаваться одной SSH-сессией с `ExitOnForwardFailure=yes`.

## Безопасность

Relay SSH-ключ на Oracle не получает shell. Запись `authorized_keys` ограничена `restrict`, `port-forwarding`, `command="/usr/bin/false"` и тремя `permitlisten`: `127.0.0.1:18080`, `127.0.0.1:18081`, `127.0.0.1:18082`.

Публичные `443/tcp`, `8443/tcp` и `10000/tcp` должны быть разрешены одновременно в двух местах: OCI Security List и `firewalld`. Caddy не снимает Basic Auth: авторизация остаётся на Caddy Mac mini за SSH-туннелем.

TURN работает отдельным `fly-turn.service` и не связан с HTTP reverse proxy.

## Конфигурация Oracle

Эталонный Caddyfile хранится в `oracle/Caddyfile`. Он проксирует только loopback-порты reverse SSH; прямого доступа Oracle к домашней сети нет.

Старый `fly-terminal.service` на Oracle должен быть `disabled/inactive`: он дублировал приложение, держал контейнер на `:80` и создавал постоянный шум Tailscale/DNS в journal. На рабочем relay остаются `caddy-oracle-relay.service`, `fly-turn.service`, `sshd.service` и `firewalld.service`.

На VM `VM.Standard.E2.1.Micro` отключены `kdump.service` и `mcelog.service`: первый не может стартовать без `crashkernel`-резерва памяти, второй не поддерживает виртуальный AMD CPU Oracle. Эти сбои не относятся к Fly Terminal и не должны оставлять `systemctl --failed` в красном состоянии.

## Диагностика

На Oracle должны слушаться `443`, `8443`, `10000` и только на loopback — `18080`, `18081`, `18082`. Если стартовая страница открывается, а карточки сервисов зависают, сначала проверять наличие всех трёх reverse-forward и OCI ingress для `8443/10000`.

Нормальный unauthenticated health-check каждого публичного HTTPS origin возвращает `401` с `WWW-Authenticate: Basic`. После Basic Auth ожидается `200` для шлюза, Terminal и Sprut.Hub; `/yt-login` штатно отвечает `302` и создаёт сессию транскрайбера.
