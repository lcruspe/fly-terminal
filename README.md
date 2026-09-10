# Railway.app Web Terminal with Tailscale

Веб-терминал с поддержкой вкладок, разделением экрана (Split Mode), безопасным доступом через Tailscale и синхронизацией истории команд. Проект оптимизирован для развертывания на **Railway.app** (в Docker-контейнере) или нативно на **macOS**.

## Особенности проекта

*   **Двухпанельный интерфейс**: переключение между вкладками (Tabs) и разделением экрана (Split Screen) выполняется компактным одноуровневым переключателем в верхней панели каждой рабочей области, сразу справа от кнопки полноэкранного режима. Параметры компоновки Split Mode остаются в основной панели и показываются только в разделённом режиме.
*   **Mac Desktop (Дистанционное управление macOS)**: отдельная вкладка с полнофункциональным удаленным рабочим столом Mac mini через noVNC и websockify. Оптимизировано под слабые каналы (Zlib сжатие, JPEG качество, локальный курсор, масштабирование).
*   **Remote Browser для macOS**: основным backend служит нативный Google Chrome на отдельном виртуальном дисплее `Fly Browser`; ScreenCaptureKit + VideoToolbox передают его через аппаратный H.264. Контейнерный Chromium сохранён как fallback.
*   **Умное именование вкладок**: автоматическое отслеживание текущей рабочей директории (`cwd`) каждого tmux-сеанса с обновлением заголовка. Возможность ручного переименования по двойному клику.
*   **Кастомизация UI**: 10 профессионально подобранных цветовых схем (5 светлых и 5 темных), выбор размера шрифта (8px - 16px) и шрифтового семейства с сохранением настроек в `localStorage`.
*   **Синхронизацией истории**: общая история команд bash мгновенно синхронизируется между всеми сессиями и вкладками.
*   **Оптимизация ресурсов**: автоматическая очистка неактивных tmux-сессий по таймауту (idle TTL) и ротация файла истории для предотвращения утечек памяти. Очистка выполняется централизованно `session-control.py` при старте и затем периодически, поэтому работает и в Docker, и в нативном macOS runtime.
*   **Безопасность**: поддержка базовой авторизации (Basic Auth) и шифрованного туннелирования через Tailscale Funnel.
*   **Два режима работы**: Docker (для Railway.app и локального запуска) и нативный macOS (с автозапуском служб через `launchd`).
*   **Маршрут Sprut.Hub**: отдельная Basic Auth учётная запись может открывать локальный Sprut.Hub через loopback TCP-forwarder. Forwarder нужен намеренно: на текущем macOS/VPN-стеке прямой LAN-dial из Caddy/Go получает `no route to host`, тогда как Python socket работает корректно.
*   **Публичный шлюз сервисов**: URL Mac mini без порта всегда проходит через Caddy Basic Auth и показывает каталог доступных сервисов. `:8443` открывает Fly Terminal, Native Chrome и Chromium fallback, `:10000` — Sprut.Hub. Cookie-обход авторизации не используется.

---

## Архитектура системы

Ниже представлена схема взаимодействия компонентов приложения:

```mermaid
graph TD
    User([Пользователь / Браузер]) -->|HTTPS :443| Gateway[Caddy: каталог сервисов]
    User -->|HTTPS :8443| Proxy[Caddy: Fly Terminal + Browser]
    User -->|HTTPS :10000| SprutProxy[Caddy: Sprut.Hub]
    Gateway -->|Fly Terminal / Browser| Proxy
    Gateway -->|Sprut.Hub| SprutProxy
    Proxy -->|Статический фронтенд /| IndexHtml[index.html]
    Proxy -->|Управление сессиями /api/*| ControlPy[session-control.py]
    Proxy -->|Терминальный поток /terminal/| Ttyd[ttyd]
    Proxy -->|noVNC /desktop/* & /desktop-ws| Websockify[websockify :5901]
    Websockify -->|RFB :5900| MacScreen[macOS Screen Sharing]
    Proxy -->|/native-browser-stream-ws| NativeStreamer[Native Browser H.264 :5906]
    NativeStreamer --> NativeChrome[Google Chrome / Fly Browser]
    Proxy -->|/browser/*| Browser[Chromium fallback / container]
    SprutProxy --> SprutForwarder[loopback forwarder :7693]
    SprutForwarder --> SprutHub[Sprut.Hub :80]
    ControlPy -->|tmux list-panes / kill-session| Tmux[tmux]
    Ttyd -->|Запуск сессии| SessionSh[terminal-session.sh]
    SessionSh -->|Очистка сессий / Лимиты| Tmux
    Tmux -->|Интерактивный shell| Bash[bash]
    Bash -->|Запись истории| HistFile[(shared_history)]
```

### Описание компонентов:
1.  **Frontend (`index.html`)**: Адаптивный веб-интерфейс, который управляет отображением вкладок/сетки, отправляет API-запросы для получения информации о сессиях, настраивает параметры шрифтов и тем оформления, а также встраивает терминалы и remote browser через `iframe`.
2.  **Прокси-сервер (Nginx / Caddy)**: Маршрутизирует запросы пользователя. Отдает статику фронтенда, проксирует WebSocket-соединения к `ttyd` и перенаправляет запросы к панели управления в Python API.
3.  **Python API (`session-control.py`)**: Легковесный HTTP-сервер, который управляет процессами tmux: запрашивает текущую директорию активной панели (`pane_current_path`) для отображения во вкладках и завершает сессии по запросу фронтенда.
4.  **Скрипт сессии (`terminal-session.sh`)**: Инициализирует окружение при открытии новой вкладки. Перед запуском tmux он:
    *   Проверяет и удаляет старые неактивные сессии (согласно лимиту `FLY_TERMINAL_SESSION_IDLE_TTL_MINUTES`).
    *   Обрезает файл общей истории, чтобы он не переполнял диск контейнера.
    *   Настраивает лимиты истории в tmux.
    *   Запускает `tmux new-session` с индивидуальным идентификатором вкладки и кастомным `.bashrc`.
5.  **Конфигурация Shell (`terminal-bashrc.sh`)**: Настраивает bash на моментальный сброс и чтение истории (`PROMPT_COMMAND="history -a; history -n"`), чтобы команды, введенные в одной вкладке, были сразу доступны в другой.

---

## Требования

1.  Аккаунт на [Railway.app](https://railway.app) (для облачного деплоя) или локальный Docker / macOS.
2.  Ключ авторизации (Auth Key) от [Tailscale](https://login.tailscale.com/admin/settings/keys) (для безопасного доступа без публичных IP-адресов).

---

## Установка и развертывание

### Вариант A: Деплой на Railway.app (Рекомендуется)

#### 1. Получите Tailscale Auth Key
1.  Перейдите в [Tailscale Admin Console](https://login.tailscale.com/admin/settings/keys).
2.  Создайте новый Auth Key:
    *   Включите **Ephemeral** (узел автоматически удалится из вашей сети при остановке контейнера).
    *   Включите **Reusable** (для удобства при автоматических перезапусках контейнера на Railway).
3.  Скопируйте ключ (формат: `tskey-auth-...`).

#### 2. Деплой репозитория
1.  Сделайте форк или запушьте данный проект в свой приватный GitHub-репозиторий:
    ```bash
    git init
    git add .
    git commit -m "Initial commit"
    git remote add origin https://github.com/ваш-username/fly-terminal.git
    git push -u origin main
    ```
2.  В панели [Railway.app](https://railway.app/new) выберите **Deploy from GitHub repo** и выберите ваш репозиторий.
3.  Railway автоматически обнаружит `Dockerfile` и начнет сборку.

#### 3. Настройка переменных окружения
В настройках проекта Railway (**Variables**) добавьте обязательные и опциональные переменные (полный список см. ниже).

---

### Вариант Б: Локальный запуск в Docker

Для тестирования и локальной разработки соберите образ и запустите контейнер:

```bash
# Сборка образа
docker build -t fly-terminal .

# Запуск контейнера
docker run -p 7681:7681 \
  -e TS_AUTHKEY=tskey-auth-XXXXXXXXXX \
  -e TERMINAL_USER=admin \
  -e TERMINAL_PASSWORD=secure-password \
  fly-terminal
```

После этого откройте в браузере: `http://localhost:7681`.

---

### Вариант В: Нативный запуск на macOS

Вы можете запустить веб-терминал напрямую на macOS (например, на Mac mini под сервером), полностью исключив Docker:

#### 1. Установите зависимости
```bash
brew install ttyd caddy tmux tailscale
```

#### 2. Запустите скрипт установки
```bash
cd /Users/kruspe/CodexProjects/fly-terminal-live
./macos/install-direct-mac.sh
```

Этот скрипт выполнит следующие действия:
*   Создаст директорию конфигурации `~/.config/fly-terminal-mac/fly-terminal.env`.
*   Зарегистрирует и запустит `launchd` агенты для `ttyd` + Python API, Caddy, macOS Remote Desktop, нативного Chrome и контейнерного Chromium fallback.
*   Создаст отдельный виртуальный дисплей BetterDisplay `Fly Browser` для нативного Chrome и отдельный H.264 streamer на `5906`.
*   Настроит Caddy на внутренние порты `8080` (каталог), `8081` (Fly Terminal + оба browser backend) и `8082` (Sprut.Hub).
*   Опубликует через `tailscale funnel`: каталог сервисов на стандартном HTTPS-порту, Fly Terminal на `8443`, Sprut.Hub на `10000`. Native Chrome и Chromium fallback доступны через `:8443`.

#### 3. Управление паролем на macOS
Для смены пароля доступа к терминалу на Mac выполните:
```bash
./macos/set-password.sh 'новый-пароль'
```
Скрипт автоматически обновит файл конфигурации и перезапустит агента `ttyd`.

#### Пути и логи на macOS:
*   Конфигурация: `~/.config/fly-terminal-mac/fly-terminal.env`
*   Логи работы: `~/Library/Logs/fly-terminal/` (файлы `ttyd.log`, `ttyd.err.log`, `caddy.log`, `caddy.err.log`)
*   Файлы служб (Launch Agents):
    *   `~/Library/LaunchAgents/ai.kruspe.fly-terminal.ttyd.plist`
    *   `~/Library/LaunchAgents/ai.kruspe.fly-terminal.caddy.plist`
    *   `~/Library/LaunchAgents/ai.kruspe.fly-terminal.browser.plist`
    *   `~/Library/LaunchAgents/ai.kruspe.fly-terminal.native-browser.plist`
    *   `~/Library/LaunchAgents/ai.kruspe.fly-terminal.native-browser-streamer.plist`
    *   `~/Library/LaunchAgents/ai.kruspe.fly-terminal.streamer.plist`
    *   `~/Library/LaunchAgents/ai.kruspe.fly-terminal.spruthub.plist`

---

## Таблица переменных окружения

Конфигурация задается через переменные окружения (в Railway Dashboard или в файле `fly-terminal.env` для macOS):

| Переменная | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `TS_AUTHKEY` | *Не задано* | Авторизационный ключ Tailscale. Если не задан, терминал будет работать только по локальной сети без подключения к VPN. |
| `TERMINAL_USER` | *Не задано* | Имя пользователя для Basic Auth авторизации в веб-интерфейсе. |
| `TERMINAL_PASSWORD` | *Не задано* | Пароль для Basic Auth авторизации. |
| `PORT` | `7681` | Внешний порт Docker-варианта. Для direct macOS публичная схема задаётся отдельными Caddy/Funnel портами ниже. |
| `CADDY_PORT` | `8080` | Внутренний Caddy-порт каталога сервисов, который публикуется как стандартный HTTPS `443`. |
| `CADDY_TERMINAL_PORT` | `8081` | Внутренний Caddy-порт Fly Terminal, который публикуется как HTTPS `8443`. |
| `CADDY_SPRUTHUB_PORT` | `8082` | Внутренний Caddy-порт Sprut.Hub, который публикуется как HTTPS `10000`. |
| `TTYD_PORT` | `7682` | Внутренний порт для демона `ttyd`. |
| `FLY_TERMINAL_CONTROL_PORT` | `7683` | Внутренний порт для Python API (`session-control.py`). |
| `TERMINAL_SCROLLBACK` | `4000` | Размер буфера прокрутки (количество строк) в терминале. |
| `FLY_TERMINAL_HISTSIZE` | `5000` | Лимит количества команд в оперативной памяти сессии bash (`HISTSIZE`). |
| `FLY_TERMINAL_HISTFILESIZE` | `10000` | Максимальный размер файла истории bash на диске (`HISTFILESIZE`). При превышении файл обрезается. |
| `FLY_TERMINAL_TMUX_HISTORY_LIMIT`| `5000` | Максимальная глубина истории вывода в буфере tmux. |
| `FLY_TERMINAL_SESSION_IDLE_TTL_MINUTES`| `120` | Время жизни (в минутах) неактивной (отключенной) сессии tmux. Старые сессии автоматически завершаются. `0` отключает TTL. |
| `FLY_TERMINAL_SESSION_CLEANUP_INTERVAL_SECONDS`| `300` | Интервал фоновой проверки старых tmux-сессий в `session-control.py`; минимум 60 секунд. |
| `FLY_TERMINAL_DIAGNOSTICS` | `1` | Флаг включения вывода системной диагностики (лимиты cgroup, доступная ОЗУ, swap, процессы) в лог контейнера при запуске. |
| `FLY_TERMINAL_HISTORY_DIR` | `/data/bash_history` (Docker) | Путь к директории хранения файла общей истории. |
| `FLY_BROWSER_ENABLED` | `0` | Включает контейнерный Chromium fallback. В direct macOS обычно `1`; основным backend при этом остаётся Native Chrome. |
| `FLY_SPRUTHUB_ENABLED` | `0` | Включает отдельную Basic Auth учётную запись, запросы которой целиком проксируются в локальный Sprut.Hub. |
| `FLY_SPRUTHUB_AUTH_USER` | *Не задано* | Имя отдельного пользователя для входа в Sprut.Hub через публичный адрес Fly Terminal. Должно отличаться от `TERMINAL_USER`. |
| `FLY_SPRUTHUB_AUTH_HASH_B64` | *Не задано* | Bcrypt-хеш пароля пользователя Sprut.Hub в Base64. Открытый пароль в конфигурации и репозитории не хранится. |
| `FLY_SPRUTHUB_FORWARD_HOST` | `127.0.0.1` | Loopback-адрес локального TCP-forwarder для Sprut.Hub. |
| `FLY_SPRUTHUB_FORWARD_PORT` | `7693` | Локальный порт TCP-forwarder. |
| `FLY_SPRUTHUB_TARGET_HOST` | `192.168.1.100` | LAN-адрес Sprut.Hub. |
| `FLY_SPRUTHUB_TARGET_PORT` | `80` | LAN-порт Sprut.Hub. |
| `FLY_ORACLE_RELAY_ENABLED` | `0` | Включает постоянный reverse SSH-туннель через Oracle relay. На основном Mac mini установлен `1`. |
| `FLY_ORACLE_RELAY_HOST` | `129.158.49.130` | Публичный IP Oracle relay. |
| `FLY_ORACLE_RELAY_USER` | `opc` | SSH-пользователь relay-сервера. |
| `FLY_ORACLE_RELAY_KEY` | `$HOME/.ssh/fly-terminal-oracle-relay` | Отдельный restricted SSH-ключ без shell-доступа. |
| `FLY_ORACLE_RELAY_GATEWAY_PORT` | `18080` | Loopback reverse-forward Oracle для Caddy `8080`. |
| `FLY_ORACLE_RELAY_TERMINAL_PORT` | `18081` | Loopback reverse-forward Oracle для Caddy `8081`. |
| `FLY_ORACLE_RELAY_SPRUTHUB_PORT` | `18082` | Loopback reverse-forward Oracle для Caddy `8082`. |
| `FLY_BROWSER_URL` | `/browser/` | URL remote browser внутри shell UI. Для iframe используется same-origin proxy через Caddy. |
| `FLY_BROWSER_IMAGE` | `lscr.io/linuxserver/chromium:latest` | Docker image для remote Chromium. На Apple Silicon используется arm64 image без qemu. |
| `FLY_BROWSER_HOST_PORT` | `7690` | Локальный порт Mac mini, на который проброшен web UI контейнера browser. |
| `FLY_BROWSER_CONTAINER_PORT` | `3000` | Внутренний HTTP-порт browser-контейнера. Для legacy KasmVNC image не используется. |
| `FLY_BROWSER_UPSTREAM` | `http://127.0.0.1:7690` | Upstream URL, куда Caddy проксирует `/browser/`. |
| `FLY_BROWSER_PROFILE_DIR` | `$HOME/.local/share/fly-terminal/browser-profile` | Persistent profile Chromium для cookies и настроек. |
| `FLY_BROWSER_PROFILE_VOLUME` | `fly-terminal-browser-profile` | Docker named volume с профилем Chromium. |
| `FLY_BROWSER_BASIC_AUTH` | *Вычисляется установщиком* | Base64 для upstream Basic Auth `kasm_user:<password>`, который Caddy подставляет при проксировании `/browser/`. |
| `FLY_NATIVE_BROWSER_ENABLED` | `1` | Включает Native Chrome как основной Browser backend на direct macOS. |
| `FLY_NATIVE_BROWSER_PROFILE_DIR` | `$HOME/.local/share/fly-terminal/native-browser-profile` | Отдельный профиль нативного Chrome, не смешанный с обычным профилем пользователя. |
| `FLY_NATIVE_BROWSER_DISPLAY_NAME` | `Fly Browser` | Виртуальный дисплей BetterDisplay, на котором размещается окно Native Chrome. |
| `FLY_NATIVE_BROWSER_FOLLOW_MAIN_WHEN_LOCKED` | `1` | Пока macOS заблокирован, Native Browser временно захватывает главный дисплей с полем пароля; после разблокировки автоматически возвращается на `Fly Browser`. |
| `FLY_NATIVE_BROWSER_STREAMER_PORT` | `5906` | Отдельный H.264/WebSocket streamer Native Chrome. |
| `FLY_NATIVE_BROWSER_STREAMER_SOCKET_PATH` | `/tmp/fly-native-browser-stream.sock` | Unix socket между ScreenCaptureKit/VideoToolbox encoder и browser streamer. |
| `FLY_NATIVE_BROWSER_STREAM_URL` | `/native-browser-stream-ws` | Same-origin WebSocket-маршрут Caddy для Native Chrome. |
| `FLY_DESKTOP_ENABLED` | `1` | Включает кнопку Mac Desktop в UI и endpoint `/api/desktop/config`. |
| `FLY_DESKTOP_URL` | `/desktop/` | URL noVNC веб-клиента для удаленного управления Mac mini. |
| `FLY_DESKTOP_PORT` | `5901` | Порт WebSocket-моста `websockify`. |
| `FLY_DESKTOP_IDLE_TIMEOUT_SECONDS` | `300` | Начальный таймаут бездействия H.264 Remote Desktop. В HUD его можно менять для текущей сессии от 1 до 60 минут; технические `configure`, probe и bridge keepalive не продлевают сеанс. |
| `FLY_DESKTOP_IDLE_FPS_AFTER_SECONDS` | `30` | Через сколько секунд без пользовательского ввода временно снижать H.264-поток до минимальных 15 FPS. Первое действие возвращает выбранный FPS cap. |
| `FLY_DESKTOP_TARGET` | `127.0.0.1:5900` | Внутренний целевой VNC-порт macOS Screen Sharing. |
| `FLY_DESKTOP_PASSWORD` | *Не задано* | Пароль VNC для автоматической авторизации при открытии вкладки. |

Для Remote Desktop без параметра `display` захватывается именно **главный дисплей macOS** (`CGMainDisplayID()`), а не первый дисплей из списка ScreenCaptureKit. Это важно на экране блокировки: поле ввода пароля находится на главном дисплее и остаётся доступным удалённо. Явные `display=Fly Remote` и `display=Fly Browser` по-прежнему выбирают соответствующие виртуальные дисплеи.

Native Browser следит за состоянием блокировки через `CGSessionCopyCurrentDictionary`. Если Mac заблокирован, поток временно переключается с виртуального `Fly Browser` на главный дисплей, где macOS рисует интерактивное поле пароля. После разблокировки поток без новой сессии возвращается на `Fly Browser`. Это не меняет основной дисплей системы и не переносит окна между дисплеями.

Параметр H.264 не фиксируется вручную: backend извлекает точный RFC 6381 codec (`avc1.PPCCLL`) из SPS каждого keyframe VideoToolbox и передаёт его клиенту при инициализации и при изменении профиля/уровня. Это устраняет чёрный экран в строгих WebCodecs-реализациях, когда фактический SPS не совпадает с заранее заданной строкой codec. Клиент проверяет поддержку полученной конфигурации и контролирует появление декодированных кадров; при несовместимости Mac Desktop автоматически переходит на noVNC, а Native Browser — на контейнерный Chromium fallback.

Для Remote Desktop начальный idle timeout равен 300 секундам, но в H.264 HUD его можно менять на 1, 3, 5, 10, 15, 30 или 60 минут. Значение хранится в браузере и передаётся серверу для текущей сессии. Сервер и клиент оба контролируют отключение: это особенно важно для Native/WebRTC, где постоянный bridge не должен восстанавливать уже завершённую по idle пользовательскую сессию. Технические `configure`, probe и `bridge_keepalive` не считаются активностью. Legacy noVNC сохраняет прежний отдельный механизм отключения.

Через 30 секунд без мыши, клавиатуры, скролла или clipboard H.264 streamer автоматически переключает encoder на 15 FPS, не меняя выбранный пользователем FPS cap. Первое пользовательское действие возвращает выбранную частоту. Ограничение FPS и разрешение потока можно менять прямо в HUD; те же настройки из общего Settings применяются к уже открытым H.264-вкладкам через `postMessage`/WebSocket без перезагрузки iframe. Смена разрешения использует штатный `configure_encoder`: encoder перезапускается внутри существующей транспортной сессии, поэтому вкладка и управление не разрываются.

Захват ScreenCaptureKit/VideoToolbox запускается лениво только при подключении первого H.264-клиента и останавливается сразу после отключения последнего. Сам streamer продолжает слушать WebSocket-порт, но `FlyDesktopCapture` в простое не работает, поэтому macOS не показывает индикатор наблюдения за экраном без реальной Remote Desktop-сессии.

HUD H.264-клиента по умолчанию свёрнут до chip, в котором остаётся только фактический FPS. Полная панель открывается только с самого chip, автоматически скрывается через 3 секунды без взаимодействия, может быть закреплена и перетащена; закрепление и позиция сохраняются локально в браузере.

В direct macOS Browser использует два backend. **Native Chrome** — основной: обычный Google Chrome запускается на отдельном дисплее `Fly Browser`, а изображение передаётся через ScreenCaptureKit и аппаратный H.264 VideoToolbox. **Chromium fallback** остаётся доступен через `/browser/` и используется вручную либо автоматически при недоступности нативного захвата. Оба backend работают через тот же Fly Terminal origin и не требуют настройки proxy на клиентском компьютере.

---

## Использование и возможности UI

### Сценарии использования
Основной кейс — доступ к рабочей консоли сервера прямо из браузера (например, с рабочего ПК, где заблокированы стандартные SSH-порты или запрещена установка стороннего ПО).

### Описание кнопок управления:
*   **Вкладки / Сплит**: Переключает режим отображения. Режим **Сплит** делит экран на равные области для всех открытых вкладок. Переключение фокуса в режиме Сплит происходит автоматически при наведении курсора мыши или по клику.
*   **Новая вкладка**: Запускает новый независимый сеанс tmux и добавляет его в текущее окно.
*   **Browser**: по умолчанию открывает Native Chrome на macOS через отдельный H.264 stream. В панели можно переключиться на контейнерный Chromium fallback; закрытие вкладки Fly Terminal не завершает сам browser backend.
*   **Новое окно**: Генерирует уникальный идентификатор сессии и открывает чистый терминал в новой вкладке браузера (сессии не будут пересекаться).
*   **Переподключить**: Перезагружает iframe активного терминала (полезно при сбое сетевого соединения).
*   **Фокус**: Программно возвращает фокус ввода на текстовое поле xterm (терминал готов к вводу команд).
*   **Копировать**: Копирует последний ответ Codex целиком. Отдельное выделение мышью внутри терминала автоматически копирует только выделенный фрагмент.
*   **Ещё**: Появляется, когда панели не хватает ширины, и содержит кнопки, которые не поместились в окно.
*   **Настройки**: Панель выбора тем оформления и шрифтов. Все изменения мгновенно применяются к терминалу и сохраняются в браузере.

---

## Публичный шлюз и маршрутизация

Для direct macOS стандартный URL `https://<имя-mac-mini>/` больше не открывает один из сервисов напрямую. Сначала Caddy выполняет Basic Auth, после чего показывает каталог сервисов, разрешённых текущей учётной записи.

| Публичный адрес | Результат после авторизации | Доступ |
| :--- | :--- | :--- |
| `https://<host>/` | Каталог доступных сервисов | `TERMINAL_USER` и отдельная учётная запись Sprut.Hub |
| `https://<host>:8443/` | Fly Terminal напрямую | только `TERMINAL_USER` |
| `https://<host>:8443/desktop/webrtc.html?...display=Fly%20Browser` | Native Chrome напрямую | только `TERMINAL_USER` |
| `https://<host>:8443/browser/` | Chromium fallback | только `TERMINAL_USER` |
| `https://<host>:10000/` | Sprut.Hub напрямую | `TERMINAL_USER` или `FLY_SPRUTHUB_AUTH_USER` |

Basic Auth включён отдельно на каждом публичном порту. Caddy не использует cookie для обхода авторизации: если браузер не хранит Basic Auth для конкретного origin, он получает `401` и показывает стандартный запрос логина и пароля. Кэширование самих Basic Auth credentials выполняет браузер и привязано к origin, поэтому при первом переходе на другой порт запрос может появиться повторно.

Для доступа через Oracle используется та же схема портов: `https://129-158-49-130.sslip.io/`, `:8443` и `:10000`. Oracle не запускает копию Fly Terminal: Caddy на VM проксирует три loopback-порта reverse SSH обратно на Mac mini. Полная схема, ограничения SSH-ключа и диагностика описаны в [ORACLE_RELAY.md](ORACLE_RELAY.md).

---

## Безопасность

### 1. Basic Auth
Основная учётная запись задаётся через `TERMINAL_USER` и `TERMINAL_PASSWORD`. Для Sprut.Hub используется отдельная учётная запись с bcrypt-хешем в `FLY_SPRUTHUB_AUTH_HASH_B64`; открытый пароль в репозитории не хранится. Все публичные Caddy-маршруты требуют Basic Auth до выдачи HTML, API или проксируемого сервиса.

### 2. Tailscale Funnel
Funnel публикует сервис в интернете на HTTPS-адресе Tailscale. Поэтому защита Caddy Basic Auth обязательна и не заменяется самим Funnel. Для доступа только внутри tailnet вместо Funnel следует использовать Tailscale Serve.

Для Docker/Railway сценария команда публикации остаётся:

```bash
tailscale funnel $PORT
```

---

## Мониторинг и диагностика ресурсов

По умолчанию при старте контейнера в логи выводятся параметры окружения и состояние памяти. Это помогает обнаружить нехватку ресурсов (OOM) до того, как контейнер упадет:
*   Текущие ограничения памяти cgroup.
*   Доступная оперативная память хоста (`MemAvailable`).
*   Наличие и размер Swap.
*   Список запущенных процессов с их PID и потреблением памяти (`RSS`).

Вы можете отслеживать эти показатели в панели управления Railway в вкладках **Logs** и **Metrics**.

---

## Устранение неполадок (Troubleshooting)

### Контейнер перезапускается из-за нехватки памяти
Railway на бесплатном тарифе предоставляет ограниченный объем ОЗУ.
*   Уменьшите буфер прокрутки: `TERMINAL_SCROLLBACK=2000`, `FLY_TERMINAL_TMUX_HISTORY_LIMIT=2000`.
*   Уменьшите время жизни неактивных сессий: `FLY_TERMINAL_SESSION_IDLE_TTL_MINUTES=60`, чтобы неиспользуемые процессы tmux вовремя завершались.

### Не работает прокрутка колесиком мыши
ttyd запускается внутри tmux, поэтому обычный scrollback xterm не является основным буфером. Колесико должно доходить до tmux и прокручивать историю панели, а не превращаться в стрелки вверх/вниз для shell prompt.
1.  Убедитесь, что в конфигурации tmux включен режим мыши (`set -g mouse on`). В репозитории это настроено по умолчанию в `/etc/tmux.conf`.
2.  Для уже запущенных сессий примените настройку runtime: `tmux set-option -g mouse on`.

### Новая вкладка браузера дублирует существующий терминал
Если вы открываете URL терминала в новой вкладке вручную, браузер может подключить вас к той же tmux-сессии. Для открытия изолированного сеанса:
*   Используйте кнопку **Новое окно** в интерфейсе — она сгенерирует новый `sessionId`.

### Browser-панель показывает пустой iframe
Browser-панель по умолчанию должна использовать Native Chrome через `/native-browser-stream-ws`. Контейнерный Chromium остаётся на `/browser/` как fallback. Порт `:10000` зарезервирован для Sprut.Hub; старые закладки Remote Browser на `:10000` больше не соответствуют текущей схеме.

### Внешний Browser работает рывками
Проверьте в логах browser-контейнера строку `Stream settings active`. Для внешнего URL ожидается `FPS: 30.0` и `CRF: 30`; для локального URL — `FPS: 60.0` и `CRF: 22`. После обновления сделайте hard reload. Для одновременной работы Chromium и CPU-кодирования рекомендуется выделить Docker runtime не менее 4 CPU и 4 GiB памяти (для Colima: `colima start --cpus 4 --memory 4`).

YT Transcript использует двухэтапную авторизацию: Basic Auth завершается на Caddy, после чего `/yt-login` создаёт короткоживущую cookie-сессию приложения через `/session/bootstrap`. Для проверки внутреннего вызова используется `YT_BOOTSTRAP_SECRET`; `launch-caddy.sh` сначала читает его из `fly-terminal.env`, а если переменная не задана — из LaunchAgent `com.kruspe.yttranscriber.plist`. Поэтому секрет не нужно дублировать вручную при уже установленном транскрайбере.

Если YouTube временно отвечает `403`/`429` на endpoint субтитров, это не считается фатальной ошибкой транскрипции: сервис делает короткий повтор запроса, затем автоматически переходит на загрузку аудиодорожки через `yt-dlp` и локальный Whisper. Для `yt-dlp` включены повторные попытки extractor/download/fragment запросов.
