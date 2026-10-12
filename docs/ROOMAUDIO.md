# RoomAudio — публичный маршрут и плитка Fly Terminal

## Назначение

RoomAudio хранит записи с Windows Mate, предоставляет веб-архив и live-прослушивание, локальную расшифровку речи на Mac mini. Сервис обслуживается отдельным Python-процессом на Mac; **Fly Terminal не реализует собственную аудиозапись**.

## Доступ и архитектура

- Внешний вход: `https://129-158-49-130.sslip.io/roomaudio/` (HTTPS на Oracle).
- Oracle пересылает основной HTTPS gateway по SSH reverse tunnel на Caddy Mac mini (локальный порт 8080).
- `macos/Caddyfile` обслуживает `/roomaudio` → `/roomaudio/` и проксирует `/roomaudio/*` через `handle_path` на `{$FLY_ROOMAUDIO_UPSTREAM:http://127.0.0.1:8766}`. Префикс удаляется перед обращением к RoomAudio.
- Приложение RoomAudio само аутентифицирует запросы; gateway **не должен перехватывать** его `Authorization` собственной Basic Auth. Cookies сессии привязаны к `/roomaudio` и имеют `Secure; HttpOnly; SameSite=Lax`.
- Маршруты `/roomaudio/ingest/*`, `/roomaudio/client/*` и `/roomaudio/setup/*` заблокированы на публичном gateway с ответом 404. Они предназначены только для частного подключения источника. Не удалять это ограничение при синхронизации окружений.
- Отсутствие авторизации на `/roomaudio/api/status` должно давать 401; `/roomaudio/` выдаёт страницу входа (HTTP 200).
- Стартовая страница `macos/gateway/admin.html` содержит самостоятельную плитку **RoomAudio** с относительной ссылкой `/roomaudio/`, атрибутом `data-health="roomaudio"`; клиентский индикатор проверяет доступность при загрузке.

## Где что находится

- Основной Fly Terminal: `macos/Caddyfile`, `macos/gateway/admin.html`, `macos/gateway/gateway.js`.
- Отдельное приложение на Mac: `~/Library/Application Support/RoomAudio/` (`server.py`, `index.html`, `transcriber.py`, архивные API, конфигурация).
- Аудиоархив и модели — на внешнем диске WD в `/Volumes/WD/RoomAudio/`.
- Конфигурация RoomAudio содержит пароль и ключ ingest; **не коммитить её, аудиофайлы, БД и логи**.
- Автозапуск RoomAudio реализован через пользовательский `launchd`.
- Изменения в `macos/Caddyfile` могут быть локально расширены окружением (например, индивидуальными upstream-маршрутами). Синхронизация проекта должна сохранять локальные deployment overrides.

## Проверки публикации

```sh
curl -k -o /dev/null -w '%{http_code}\n' https://129-158-49-130.sslip.io/roomaudio/              # 200 (логин)
curl -k -o /dev/null -w '%{http_code}\n' https://129-158-49-130.sslip.io/roomaudio/api/status    # 401 без авторизации
curl -k -o /dev/null -w '%{http_code}\n' https://129-158-49-130.sslip.io/roomaudio/ingest/check # 404
```

Все три кода проверены 12.10.2026.

## Диагностика

Если `/roomaudio/` отдаёт 502, проверять по цепочке: `RoomAudio :8766` → `Caddy :8080` → `SSH reverse tunnel` → `Oracle HTTPS`. Если вход доступен, но проигрыватель не получает медиа, проверить сессии и media token самого RoomAudio до изменения прокси. Если нет плитки, убедиться, что Caddy отдаёт актуальную `admin.html` из `{$FLY_TERMINAL_REPO_ROOT}/macos/gateway`.
