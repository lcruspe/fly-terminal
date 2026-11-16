# Commander Hub: публикация сервисов через отдельный Tailscale Funnel

## Архитектура

Mac mini постоянно работает с отдельной Lima VM `ts` на Mac SSD.
В одной VM запущены **два независимых** Tailscale-узла: `mac-gateway` и
`commander-hub`. Для Commander используется сокет
`/run/tailscale-commander/tailscaled.sock` и служба `tailscaled-commander.service`.
Не изменять конфигурацию основного `mac-gateway` для ремонта Commander.

| Публичный HTTPS | Назначение | Прокси внутри VM `ts` | Mac mini |
|---|---|---|---|
| `commander-hub.tail1c55c5.ts.net:443` | Commander Hub MCP | `127.0.0.1:9774`, `commander-hub-proxy.service` | `host.lima.internal:7774` |
| `:8443` | Каталог Fly Terminal, терминал по `/fly/` | `127.0.0.1:19800`, `mac-services-funnel.service` | `host.lima.internal:8080` |
| `:10000` | Sprut.Hub | `127.0.0.1:19801`, `mac-terminal-funnel.service` (историческое имя) | `host.lima.internal:8082` |

На `:8443` Caddy Mac mini переводит специальные пути `/fly/*`,
`/api/*`, `/desktop*/*` и WebSocket на внутренний порт `8081`.
Контроль доступа на обоих портах выполняет Caddy + 30-дневная cookie-сессия.
`443` не является каталогом Fly Terminal: этот origin обслуживает Commander Hub.

**Не использовать фиксированный LAN-IP Mac mini в systemd unit-файлах.**
При смене DHCP-адреса `192.168.1.201` → `192.168.1.232` порты 8443
и 10000 перестали работать, хотя Commander Hub на 443 отвечал 200.
Имя `host.lima.internal` внутри Lima VM стабильно разрешается в адрес
хостовой macOS (в текущей VM — `192.168.5.2`). Это штатный маршрут VM → Mac.

## Применённая конфигурация

Внутри VM `ts`:

```ini
# /etc/systemd/system/mac-services-funnel.service
[Unit]
Description=Mac public access TCP proxy
Requires=mac-services-funnel.socket
After=network-online.target
[Service]
ExecStart=/usr/lib/systemd/systemd-socket-proxyd host.lima.internal:8080
DynamicUser=yes
NoNewPrivileges=yes
```

```ini
# /etc/systemd/system/mac-terminal-funnel.service
[Unit]
Description=Mac public access TCP proxy
Requires=mac-terminal-funnel.socket
After=network-online.target
[Service]
ExecStart=/usr/lib/systemd/systemd-socket-proxyd host.lima.internal:8082
DynamicUser=yes
NoNewPrivileges=yes
```

Соответствующие socket units слушают `127.0.0.1:19800` и `127.0.0.1:19801`.
Они `enabled`, отдельные прокси-сервисы автоматически активируются сокетами.
После изменения unit-файлов выполнить `sudo systemctl daemon-reload`,
затем `sudo systemctl restart mac-services-funnel.service mac-terminal-funnel.service`.
Перезапуск `tailscaled-commander` и Commander Hub не требуется.

## Диагностика

Lima VM находится на внешнем SSD, а не в стандартном `~/.lima`.
Используйте уже существующий `LIMA_HOME` реальной VM:

```zsh
export LIMA_HOME='/Volumes/MacSSD — данные/Infrastructure/lima'
/opt/homebrew/bin/limactl list
/opt/homebrew/bin/limactl shell ts sudo systemctl status mac-services-funnel.service mac-terminal-funnel.service --no-pager
/opt/homebrew/bin/limactl shell ts sh -lc 'curl -s -H "Accept: text/html" -o /dev/null -w "%{http_code}\n" http://127.0.0.1:19800/'
/opt/homebrew/bin/limactl shell ts sh -lc 'curl -s -H "Accept: text/html" -o /dev/null -w "%{http_code}\n" http://127.0.0.1:19801/'
/opt/homebrew/bin/limactl shell ts sudo tailscale --socket=/run/tailscale-commander/tailscaled.sock funnel status
```

Для публичного теста с проверкой HTTPS, администратора, вторичной роли
Sprut.Hub и WebSocket (два маршрута с 101 Switching Protocols):

```zsh
cd /Users/kruspe/CodexProjects/fly-terminal-live
set -a
source "$HOME/.config/fly-terminal-mac/fly-terminal.env"
set +a
/opt/homebrew/bin/python3 tests/check_commander_funnel.py
```

Тест выдаёт **собственные временные токены** в локальной SQLite и отзывает
только их в `finally`; пользовательские сессии не трогает. Он не выводит
логины, пароли или cookie. HTTP 302 без cookie является нормальным редиректом
на форму входа, а не сбоем.

## Откат и безопасность

Единственные сохранённые исходные unit-файлы находятся на Mac mini:

`~/.config/fly-terminal-mac/rollback/commander-hub-funnel/`

Для возврата используйте `limactl copy <local-file> ts:/tmp/<file>`,
затем `limactl shell ts sudo install -m 0644 /tmp/<file> /etc/systemd/system/<file>`,
`systemctl daemon-reload` и перезапуск только двух прокси-сервисов.
Перед восстановлением проверьте целевой путь. Откат к старому IP намеренно
вернёт первоначальную ошибку, если этот IP не восстановлен.

Отдельно обнаружены ссылки на старый `192.168.1.201` в
`/etc/macgateway/Caddyfile` внутри той же VM. **Это другой узел
`mac-gateway`**. Его Caddy и авторизация в рамках исправления Commander Hub
не изменялись; они требуют отдельной проверки после входа, поскольку
простой GET без cookie может вернуть 302 до обращения к upstream.
