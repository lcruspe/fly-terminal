# Fly Terminal: постоянная HTTP-сессия (macOS Caddy)

## Назначение

Safari web app на iPhone не обязан использовать сохранённые Safari логины в системном окне HTTP Basic Auth. Поэтому публичные HTTP-порты теперь отдают обычную HTML-форму `/auth/login` с полями `autocomplete=username/current-password`. Существующие учётные данные не изменяются.

## Поток входа

1. Незащищённый GET HTML (`/`, `/terminal/`) перенаправляется на `/auth/login?next=<путь>`. API/WebSocket без сессии получают 401 без Basic challenge.
2. Форма выполняет POST `/auth/issue`, передавая существующий логин/пароль заголовком Authorization: Basic через HTTPS. Caddy проверяет bcrypt для `TERMINAL_USER` или `FLY_SPRUTHUB_AUTH_USER`. На 8443 разрешён только администратор.
3. Caddy передаёт в loopback-процесс `session_auth.py` подтверждённый username и отдельный внутренний секрет. Сервис создаёт криптографически случайный токен, сохраняет только его SHA-256 и username в SQLite.
4. Ответ устанавливает cookie `fly_session`: `Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000`. Нет Domain, поэтому cookie host-only и одинакова для 443, 8443 и 10000 **одного и того же имени хоста**.
5. Каждая защищённая операция на трёх портах проходит `forward_auth` к `/auth/check/any` либо `/auth/check/admin`. Процесс отвечает username; срок в БД проверяется на каждом запросе. При запросах срок не меняется.
6. По `POST /auth/logout` удаляется одна сессия. По `POST /auth/revoke-all` удаляются все сессии; этот маршрут доступен только администратору. Оба требуют Origin, совпадающий с Host; отдельно защищён `gateway-control.py` со своим CSRF.
7. При изменении основного пароля `macos/set-password.sh` очищает хранилище сессий. Смена пароля второй учётной записи вне этого скрипта требует ручного отзыва всех сессий.

## Матрица доступа

| Маршрут | Администратор | Sprut.Hub | Без сессии |
|---|---|---|---|
| 443: каталог | Полный | Только Sprut | Вход |
| 443: `/gateway-control/*` | Да, доп. авторизация backend и CSRF | 403 | Вход/401 |
| 443: `/yt-login` | Да | Да | Вход/401 |
| 8443: терминал, API, Native, Browser, WS | Да | 403 | Вход/401 |
| 10000: Sprut.Hub | Да | Да | Вход/401 |
| 443: RoomAudio, archive/media, YT UI, Yandex MCP | Собственная авторизация | Собственная авторизация | Исключены из Fly-проверки |
| 8443: Yandex MCP | Отдельная авторизация | Отдельная авторизация | Исключён из Fly-проверки |

Исключения `/roomaudio/setup/*` остаются заблокированы 404. Прямой доступ к loopback-API авторизации не даёт права выдать сессию без серверного `session-auth.secret`. Для запросов управления сервисами backend независимо проверяет cookie или прежнюю пару Basic Auth; прохождение одного Caddy недостаточно.

## Хранение и запуск

- `~/.config/fly-terminal-mac/sessions.sqlite3` — SQLite, 0600, не хранить в Git, сессии переживают перезапуск Caddy/Mac.
- `~/.config/fly-terminal-mac/session-auth.secret` — случайный серверный секрет, 0600, не хранить в Git. Секрет не является паролем пользователя.
- `ai.kruspe.fly-terminal.session-auth` — LaunchAgent, loopback `127.0.0.1:7685`. Запускается `macos/install-session-auth.sh`.
- `macos/launch-caddy.sh` читает секрет из файла и передаёт конфигурации Caddy. Устанавливать после запуска session-auth.
- `macos/gateway-control.py` использует тот же SQLite для проверки администратора и сохраняет проверку Origin+CSRF.
- `oracle/Caddyfile` не меняется: Oracle остаётся TLS proxy 443/8443/10000 → обратные SSH-порты Mac.

Сохранять ровно одну актуальную рабочую копию репозитория. Не удалять пользовательские untracked-файлы в процессе обновления.

## Проверки перед переключением

```zsh
cd /Users/kruspe/CodexProjects/fly-terminal-live
python3 -m unittest discover -s tests -p 'test_session_auth.py' -v
python3 -m unittest discover -s tests -p 'test_gateway_control.py' -v
node --test tests/gateway-links.test.js tests/gateway-mobile-layout.test.js
./tests/run-session-auth-smoke.sh
node --test tests/*.test.js
# После установки на Mac mini, из исходного env-файла:
set -a; source "$HOME/.config/fly-terminal-mac/fly-terminal.env"; set +a
python3 tests/check_live_session_auth.py
```

`run-session-auth-smoke.sh` создаёт временные экземпляры Caddy, session-auth и gateway-control на отдельных портах 18080/18081/18082/17685/17684 и временную SQLite. Рабочий шлюз и сессии не изменяет. Проверяются роли, HTTP, 101 WebSocket, management, отзыв и исключения.

## Переключение и откат

Перед первой активацией сохранить исходный работающий `macos/Caddyfile` в
`~/.config/fly-terminal-mac/rollback/session-auth/Caddyfile` (архивная единственная копия).
После локальной проверки установить LaunchAgent session-auth и только затем перезапустить Caddy. После рестарта тестировать `GET /auth/login = 200`, `GET / = 302` при Accept text/html на трёх портах; затем реальный HTTPS-адрес Oracle.

При проблемах выполнить:

```zsh
./macos/rollback-session-auth.sh
```

Откат восстанавливает исходный Caddyfile и перезапускает **только Caddy**, возвращая прежний Basic Auth и не затрагивая остальные сервисы, Oracle или хранилище. Файл Caddy после отката отличается от версии Git; для повторного включения потребуется вернуть обновлённый Caddyfile. После отката сессионный backend можно оставить, он остаётся loopback и не участвует в доступе.
