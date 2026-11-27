## Public service gateway

The direct macOS deployment exposes a small authenticated service selector on the default HTTPS origin. Caddy must complete Basic Auth before any gateway HTML or asset is returned. The gateway never relies on a session cookie to bypass Basic Auth.

The selector is role-aware: the main `TERMINAL_USER` sees Fly Terminal (`:8443`), Remote Browser (`:10000`), and Sprut.Hub (`:9443`), while `FLY_SPRUTHUB_AUTH_USER` sees only Sprut.Hub (`:9443`). Links are built from the current hostname so the same static gateway works with the current Tailscale hostname. Direct service ports repeat Basic Auth because browser credential caches are origin-specific.

Do not expose the browser upstream (`7690`) or Sprut.Hub LAN address directly through Funnel. Public ports must terminate at Caddy so authentication is always applied first.

### Gateway identity (2026-11-27)

The catalog uses the nested-bracket silhouette with colors inherited from the active theme (surface and accent tokens). The header SVG and dynamically generated browser favicon follow both light/dark and Classic/Retro Pixel; the standalone SVG favicon follows the system color scheme before JavaScript runs. The ICO and 180/192/512 px PNG resources remain fixed fallback/install assets: once installed, home-screen icon appearance is controlled by the operating system. The dedicated gateway.webmanifest is separate from the terminal manifest. Caddy permits only these exact static branding paths without a session so browser icon retrieval also works before login; catalog HTML and all operational routes retain their existing authentication. The Commander Hub MCP service on port 443 is a separate application; the visual catalog is on port 8443.

# UI behavior

## Responsive toolbar

The main Fly Terminal toolbar uses two sequential degradation levels when horizontal space is reduced:

1. **Icon-only mode.** If the full toolbar no longer fits, text labels are hidden while representative icons remain visible. Tooltips and `aria-label` values remain available so actions are still identifiable.
2. **Overflow menu.** If the icon-only toolbar still does not fit, actions are moved from the right edge into the overflow menu. The overflow trigger is always represented by the three-dot icon. Items moved into the menu regain their text labels.

On touch-capable devices, every active tab exposes a **Клавиатура** action. It synchronously focuses the tab's native mobile input: ttyd's xterm helper textarea for Terminal, Selkies/noVNC's touch input for compatible Browser/Desktop frames, or the WebRTC desktop text bridge. The action is hidden on non-touch devices. Terminal, Selkies, and noVNC keystrokes flow directly to the remote session; the WebRTC bridge clears its temporary text field after sending or cancelling.

The collapse/expand-panel action stays directly accessible and switches to icon-only mode together with the rest of the toolbar, but is not moved into overflow.

Responsive layout is recalculated on toolbar/window resize and when toolbar items are shown/hidden or split-layout controls change. The implementation restores all items to their canonical DOM positions before each measurement, so widening the browser reverses the degradation automatically: overflow items return first, then labels are restored when space permits.

When adding new top-level toolbar actions, include them in the responsive toolbar item set and provide a representative icon plus a meaningful `title`/`aria-label`. Do not introduce fixed breakpoint-specific hiding for individual actions; capacity is determined from the actual rendered width.

## Mobile console without card framing (2026-11-17)

For the iPhone and similarly compact touch viewports, Fly Terminal uses a single full-bleed working surface. This is the successor to the first iPhone shell adaptation described below. The old separate cards (terminal frame, tab bar, and toolbar) are **not used** on compact touch screens: there are no outer borders, drop shadows, large corner radii or inter-panel gaps. A one-pixel inset divider separates the terminal header, tab strip and actions; accent color is reserved for the active view/tab and existing functional state. All colors come from existing theme variables, so user-selected light and dark themes continue to work. Desktop layout remains unchanged.

The terminal header is 44 CSS px high, tabs are 44 px and toolbar 48 px; the combined lower panel is 92 px. At 428×926 simulated viewport, terminal working wrapper increases from 785 px (the preceding card design) to **834 px**, +49 px. At 926×428 the wrapper becomes 336 px, previously 287 px. Touch controls remain at least 44×44 px and the on-screen keyboard stays directly accessible; less frequent commands automatically move into the existing overflow menu when needed. Tab close, tab add, settings and actions have unchanged behavior.

`viewport-fit=cover`, shell/fullscreen `safe-area-inset-*`, dynamic `visualViewport`, and safe floating-menu bounds remain active for the iPhone 13 Pro Max's rounded display corners, top cutout and Home indicator. The page fills only the unobstructed CSS viewport; do not reintroduce arbitrary external padding on touch layouts. Tests exercise 428×926, 926×428, 390×844 and 320×568 with a local terminal mock; these measurements are not proof of correct live Safari keyboard or RDC/video behavior.

## iPhone 13 Pro Max — mobile shell adaptation (2026-11-17)

The target mobile viewport is 428×926 CSS pixels (portrait), 926×428 (landscape). The main shell uses viewport-fit=cover plus safe-area-inset-{top,right,bottom,left}. These clearances protect interactive elements from rounded corners, display notch and Home indicator; fullscreen frames and Settings/Tools/Apps sheets honor the same insets. The layout height follows visualViewport on touch screens as the iOS keyboard opens/closes.

On small touch screens (at most 760px wide or 530px high) the effective toolbar orientation is horizontal, without changing the persisted desktop orientation preference. The bottom panel occupies 116px instead of the 159px baseline at 428×926, giving the workspace 785px instead of 727px. Primary keyboard and panel controls, frame controls, tab close and new tab have 44×44 CSS pixel touch areas. The keyboard remains directly accessible; less-used actions move into the overflow menu. Touch tab-close uses a real button and new tab supports Enter/Space.

Touch bottom sheets are positioned using computed CSS safe-area insets, including in landscape. Function touchMenuBounds is unit-tested against a 59px side notch and 21px bottom home indicator. Desktop behavior remains unchanged.

Validation: 44 Chromium CDP interaction checks with mocked terminal endpoints at 428×926, 926×428, 390×844 and 320×568. Real Safari on the physical iPhone, live ttyd, WebSocket and H.264 streams were not exercised by the mock tests.

## Edge-to-edge horizontal layout

The Fly Terminal shell has no horizontal page padding. The terminal/browser workspace, tab bar, and main toolbar therefore span the full viewport width, while the 14 px vertical shell padding and 12 px vertical spacing between sections are preserved. Do not reintroduce horizontal padding on `.shell`; add any required spacing inside individual controls instead.

## Tab close controls

Tab close controls remain in the DOM but are visually hidden until the corresponding tab is hovered. This behavior is shared by horizontal tabs, regular vertical sidebars, and the compact vertical sidebar. In non-compact layouts the hidden control keeps its layout space, so tab width and label position do not jump when the close control appears.

In compact vertical sidebar mode the close control is positioned as an overlay in the tab corner instead of consuming layout space. This keeps the compact tab label centered while still allowing every tab to be closed. Do not hide compact close controls with `display: none`; use the shared hover visibility behavior instead.

## Floating menus

Settings, Tools, dropdown, responsive overflow, and Apps surfaces are positioned in viewport coordinates and then translated to the browser's actual fixed-position containing block. This matters because CSS properties such as `backdrop-filter`, `filter`, `transform`, `perspective`, and layout/paint containment can make a fixed descendant relative to an ancestor instead of the viewport. Desktop popups are measured after size constraints and clamped to the viewport.

Only one top-level menu surface remains active at a time. A transparent fixed `menuBackdrop` is placed above terminal/browser frames, including frame fullscreen, and below the toolbar/menu surfaces. Its `pointerdown` closes all menu types through the shared `closeAllMenus()` path, so a click in iframe-covered workspace cannot be swallowed by the iframe. `Escape` uses the same close path; clicks inside the currently open menu do not dismiss it.

On coarse-pointer/touch devices, floating menus switch to a viewport bottom-sheet presentation: 8 px viewport inset, height capped at roughly 78% of the dynamic viewport, safe-area-aware bottom padding, and controls with at least 48 px touch height. Apps uses the same sheet surface but replaces desktop cascade flyouts with one level at a time; entering Mac Apps, VM Apps, or Snippets shows the selected level and an in-sheet **Назад** action restores the Apps root. These behaviors are part of the menu interaction contract and should be covered by automated and browser smoke tests whenever menu positioning or state management changes.

## Settings information architecture

The top-level menus follow a task-based boundary: **Apps** launches environments and applications, **Settings** contains user preferences, and **Tools** contains operational actions that affect the local/remote environment. Do not place operational commands in Settings merely because they have configurable parameters.

Settings is a sectioned hub with three panels: **Внешний вид** (theme, UI density, font size/family), **Рабочая область** (toolbar orientation and tab title), and **Remote Desktop** (transport, stream resolution, automatic display resize, scale mode, and FPS). Desktop uses persistent left-side section navigation inside the popup; touch/coarse-pointer layouts move the same navigation to a horizontally scrollable selector above the content. Only one section panel is visible at a time. Arrow keys plus Home/End move between section tabs.

The active Settings section is intentionally session-local UI state and is not persisted as a preference. Existing control IDs and preference bindings remain stable when controls move between sections.

## Tools information architecture

Tools is also sectioned by operation rather than rendered as one long scrolling column: **VPN**, **Файлы**, **Displays**, and **Система**. Desktop uses the same left-side section-navigation pattern as Settings; touch/coarse-pointer layouts expose a horizontal four-item selector.

Manual display resolution controls belong to **Tools → Displays** because applying them changes actual macOS display modes. `desktopResolution` remains in Settings because it controls the Remote Desktop stream; `desktopAutoResize` is the persistent opt-in for following the active RDC window, and `mainDisplayResolution` and `virtualDisplayResolution` remain manual controls under Tools.

When adding new menu functionality, classify it first: launchers go to Apps, durable presentation/behavior preferences go to Settings, and environment-changing commands go to Tools. Prefer extending an existing section over adding another top-level menu.

## Native Browser backend

On direct macOS, the **Browser** action initially uses Native Chrome as the primary backend. Manually switching Native / Chromium fallback saves the choice in UI preferences (locally and on the server) for new tabs and future sessions. Automatic fallback after a native browser failure does not overwrite that choice. Google Chrome runs with a dedicated profile on the BetterDisplay virtual display **Fly Browser**. Its display is captured by ScreenCaptureKit and encoded by VideoToolbox, then delivered through the dedicated `/native-browser-stream-ws` route.

The containerized Chromium backend remains available at `/browser/` as a fallback. Browser tabs expose a backend switch so the user can move between Native Chrome and Chromium without changing client proxy settings. If the Native Chrome stream reports a macOS screen-capture permission failure, the Browser tab switches to the Chromium fallback automatically when it is available.

Native Browser is isolated from Mac Desktop: it uses its own virtual display, streamer port `5906`, and Unix socket `/tmp/fly-native-browser-stream.sock`. Do not reuse the Mac Desktop streamer port or socket for this backend.

The public catalog must point Native Browser and Chromium fallback through the authenticated `:8443` Fly Terminal origin. Port `:10000` is reserved for Sprut.Hub in the current direct-macOS routing scheme.

## Совместимость Remote Desktop

Mac Desktop без явного выбора дисплея показывает главный дисплей macOS. Это гарантирует, что на lock screen видны пользователь и поле пароля; виртуальные `Fly Remote` и `Fly Browser` используются только при явном выборе.

Native Browser в обычном состоянии показывает `Fly Browser`. При блокировке macOS захват переключается на главный дисплей, но ScreenCaptureKit может отдавать чёрный кадр. Вкладка Native Browser показывает состояние блокировки и ссылку на RDC VNC для ввода пароля; после разблокировки тот же сеанс автоматически возвращается к `Fly Browser`. Состояние `host_locked` не является ошибкой транспорта и не переводит Browser на Chromium fallback.

H.264-клиент получает фактический RFC 6381 codec из SPS потока VideoToolbox, а не использует жёстко заданный профиль/уровень. Он проверяет эту конфигурацию через WebCodecs и следит за появлением декодированных кадров. При отсутствии поддержки или если кадры не декодируются в течение нескольких секунд Mac Desktop автоматически открывает noVNC; для Native Browser аналогичная ошибка переводит вкладку на Chromium fallback.


## Панель управления Remote Desktop

HUD поверх удалённого экрана по умолчанию находится в компактном состоянии и показывает **только фактический FPS**. Наведение или нажатие на chip раскрывает полную панель: кроме `⌘ Space`, `⌘ Tab`, вставки, масштабирования и полноэкранного режима в ней доступны ограничение FPS, разрешение H.264-потока и таймаут отключения при бездействии. Изменение FPS и разрешения отправляется в текущую WebSocket/WebRTC-сессию и не перезагружает iframe Remote Desktop; соответствующие значения синхронизируются обратно с Settings.

После 30 секунд без мыши, клавиатуры, скролла или clipboard сервер включает глубокий idle-профиль: 640×360, 5 FPS и 300 кбит/с. Первое реальное пользовательское действие возвращает сохранённые рабочие разрешение, FPS cap и bitrate. Технические `configure`, probe и WebRTC bridge keepalive не считаются пользовательской активностью. Таймаут отключения задаётся в HUD (1–60 минут), сохраняется на сервере и применяется и на сервере, и на клиенте; клиентский контроль нужен, чтобы WebRTC bridge не мог прозрачно восстановить уже завершённый по idle сеанс.

Незакреплённая панель автоматически сворачивается через 3 секунды без взаимодействия и сразу сворачивается при клике по удалённому экрану. Кнопка закрепления сохраняет постоянное раскрытое состояние в серверном профиле. Через drag-handle панель можно перенести в удобное место; позиция также сохраняется между сессиями и ограничивается границами viewport после изменения размера окна.

### Настройки Native на всех устройствах

`RDC Native` и `Browser Native` используют существующий защищённый `GET/POST /api/ui/preferences` и серверный JSON `~/.local/share/fly-terminal/ui-preferences.json` (`FLY_TERMINAL_UI_PREFERENCES_FILE` переопределяет путь). Настройки запрашиваются **до подключения видеопотока**; при временной ошибке чтение повторяется уже в фоне. Серверное хранение обеспечивает сохранность при очистке `localStorage`, смене браузера и устройства. Установка из `Settings` и из HUD сохраняется тем же API; не требуется отдельная база.

- `RDC Native` использует общие `desktopResolution`, `desktopFps`, `desktopScaleMode`, `desktopAutoResize`.
- `Browser Native` использует независимые `nativeBrowserResolution`, `nativeBrowserFps`, `nativeBrowserScaleMode`.
- Качество (`QualityMode`), тайм-аут (`IdleTimeoutSeconds`), закрепление (`HudPinned`) и положение (`HudPosition`) хранятся в отдельных полях с префиксами `nativeDesktop` и `nativeBrowser`. Это предотвращает взаимное перетирание профилей двух видов захвата.
- Если отдельный ключ ещё не сохранён на сервере, он инициализируется из текущего браузерного значения или URL. Уже сохранённые серверные ключи никогда не перезаписываются при этой миграции. POST передаёт только изменённые поля. При ошибке первичного чтения API клиент использует локальные значения, но **не отправляет** их на сервер, чтобы не затирать действующий профиль. При изменении настроек выполняется сохранение с повторными попытками при временных сбоях. Другая открытая вкладка увидит новый профиль при следующем запуске, а не через live-push.
- С 2026-11-06 основной интерфейс `index.html` также выполняет **только частичную запись** полей, которые изменены в данной вкладке относительно её предыдущего локального снимка. Ранее отправка **всего** `preferences` при любом изменении могла перезаписать устаревшими `desktopFps`/`desktopResolution` изменения из Native HUD или с другого устройства. Запросы сериализованы, ошибочные POST повторяются, при `pagehide` неотправленные изменения отправляются с `keepalive: true`. Это распространяется на все настройки основного UI, не только RDC.
- Native повторяет неудачный GET с ограниченным exponential backoff. Если серверные настройки поступили после восстановления связи, они применяются к уже подключённому видео и политике idle. Вновь загруженные значения не перезаписывают поля, которые пользователь успел изменить в текущей сессии. Для защиты от закрытия вкладки между выбором значения и 150-мс POST оставшиеся изменения также отправляются на `pagehide` с `keepalive: true`.
- Плашки `H.264 готов`, `2 fps`, `2560×1440` отражают **фактическое состояние потока**, а не пользовательский профиль; они не должны сохраняться. Сохраняются выбираемые значения (качество, ограничение FPS, разрешение потока, масштаб/Sync, таймаут, закрепление и положение панели).

### Защита от залипания клавиш-модификаторов

На `keyup` модификатора сервер очищает собственный бит `Option/Alt`, `Shift`, `Control` или `Command` в CoreGraphics-событии; раньше `reset_input` мог отправлять отпускание `Alt` с флагом `Alt=True` из первоначального нажатия. При потере фокуса, скрытии страницы и возврате фокуса клиент отправляет `reset_input`. Отпускание модификатора, которое пришло в HUD/другое поле вместо основного input, теперь тоже доставляется серверу. Перед обычным текстовым вводом сервер снимает оставшиеся модификаторы текущего клиента, не влияя на нажатую кнопку мыши.

Захват экрана не должен быть постоянным фоновым процессом. `FlyDesktopCapture` стартует при первом подключённом H.264-клиенте и завершается после отключения последнего; без активной Remote Desktop/Native Browser-сессии системный индикатор записи экрана macOS должен быть выключен.

### Нейтральные заголовки вкладок

Заголовки вкладок и окон должны быть короткими и нейтральными: только тип интерфейса и режим транспорта/backend, без названия ОС, хоста, кодека и длинных описаний. Используем `RDC Native`, `RDC WS`, `RDC VNC`, `Browser Native`, `Browser WS`, `Browser Fallback`; служебные страницы — `Gateway` и `Sprut`. При автоматическом fallback заголовок должен переключаться вместе с фактическим режимом.

## Авторизация YT Transcript

YT Transcript не принимает Basic Auth напрямую как приложение: Caddy проверяет Basic Auth на `/yt-login`, затем вызывает внутренний `/session/bootstrap` и передаёт общий bootstrap-secret. `launch-caddy.sh` берёт `YT_BOOTSTRAP_SECRET` из Fly-terminal env, а при его отсутствии — из установленного `com.kruspe.yttranscriber.plist`. Это исключает рассинхронизацию секретов после независимого перезапуска или переустановки сервисов.


## Ошибки YouTube при транскрипции

HTTP `403`/`429` при чтении автоматических субтитров не должен выводиться пользователю как окончательная ошибка. YT Transcript повторяет запрос субтитров и затем прозрачно переключается на аудиодорожку + локальный Whisper. Ошибка показывается только если не удалось и получение аудио/транскрипция.

Vertical toolbars open Settings, Tools and Apps toward the workspace, including the compact icon mode. Popups are constrained to the available side before measuring wrapped content, then kept within the viewport. Narrow Settings/Tools popups use scrollable horizontal section navigation. Sidebar scrolling repositions open menus and Apps submenus. The menu backdrop stays below the complete sidebar stacking context; styles for toolbar actions do not affect controls inside popups.

## Доступность сервисов на стартовой странице

На защищённом каталоге `macos/gateway/admin.html` в правом верхнем углу карточек показаны небольшие индикаторы: зелёный — отвечает, красный — не отвечает, серый — проверяется/не удалось проверить. Проверка выполняется однократно при загрузке страницы, без фонового опроса. Состояние и текстовое описание доступны при наведении на индикатор.

`macos/gateway/gateway.js` делает один same-origin запрос `GET /gateway-status` (Caddy Basic Auth обязателен), а `session-control.py` параллельно опрашивает локальные HTTP endpoints с таймаутом 1,5 с: ttyd `7682`, WebSocket-транспорт Native Browser `5906` (ответ 400/426 на обычный HTTP-запрос), Chromium fallback `7690`, YT Transcriber `8787`, Sprut.Hub forwarder `7693`. Проверка Native означает готовность транспортного порта, но не подтверждает наличие видеокадров. Выключенные через env сервисы считаются недоступными. При ошибке общего запроса все индикаторы остаются серыми, а не красными.

RoomAudio доступен через `/roomaudio/` (Caddy `handle_path` проксирует на `{$FLY_ROOMAUDIO_UPSTREAM:http://127.0.0.1:8766}`; префикс снимается). Маршрут `/roomaudio/` исключён только из шлюзовой Basic Auth, поскольку RoomAudio использует собственную Basic Auth (пользователь `listener`), а две независимые HTTP Basic Auth на одном origin нельзя применить к одному запросу. Caddy передаёт `Authorization` в RoomAudio, и само приложение обеспечивает защиту. Ответ `401` от upstream считается признаком живого сервера. Проверка RoomAudio выполняется через защищённый локальный маршрут шлюза; типовая HTML-страница каталога `Gateway` отвергается, чтобы отсутствие маршрута не превращалось в ложный зелёный индикатор. При отсутствии ответа индикатор красный. Проверка не обращается напрямую к другим HTTPS-портам из браузера.

## Управление запуском и перезапуском сервисов

`macos/gateway-control.py` управляет только разрешёнными сервисами и требует администраторскую сессию, CSRF и подтверждение остановки/перезапуска. Для LaunchAgent код `launchctl bootout` не означает, что остановка завершилась: прежняя регистрация может оставаться видимой через `launchctl print`, а `kickstart` вернуть 0 непосредственно перед её удалением. Поэтому Stop/Restart ждёт исчезновения регистрации (до 25 с); только после этого запускает соответствующий plist через `bootstrap`. Для группы Native Browser порядок остановки обратный порядку запуска. После Start/Restart контроллер ждёт доступности целевого сервиса до 30 с по существующим проверкам Gateway; для YT Transcript проверяется конкретный JSON ответа `GET /health` на 8787. Если переход не завершился или готовность не подтверждена, возвращается HTTP 502 с диагностическим сообщением, а не ложный успех. Проверка доступности не подменяет полный функциональный тест внешних поставщиков или распознавания.

27.11.2026: воспроизведена гонка удаления LaunchAgent на отдельной тестовой службе (bootout и kickstart оба вернули 0, через 5 с агент отсутствовал). Исправление общее для управляемых LaunchAgent, включая YT Transcript. Регрессионные тесты: `python3 tests/test_gateway_control.py`.

## Компактный мобильный каталог сервисов

В `macos/gateway/admin.html` нет декоративного заголовка и подзаголовка: верхним элементом каталога является переключатель «Плитки / Компактно / Список». На ширине до 600 px страница `body.dashboard-page` отключает вертикальное центрирование базовой страницы шлюза, оставляет минимальные безопасные отступы, уменьшает расстояния между карточками и уплотняет их внутренние поля. Пустой `.catalog-message` скрывается, но сообщение об ошибке или результате управления отображается как обычно. В мобильной версии по умолчанию выбран режим «Компактно», если пользователь ещё не сохранил своё предпочтение; явный выбор остаётся в `localStorage`. Стили страницы `spruthub.html` не должны меняться.


### Fallback Browser: скачивание файлов

Кнопка **⇩ Клиент / ⇩ Colima** в нижней правой части Selkies переключает автоматическую загрузку на клиент (по умолчанию) и штатное скачивание внутри Chromium. Выбор хранится локально в клиентском браузере. Если браузер блокирует автоматическую загрузку, рядом с кнопкой появляется ручная ссылка. Механизм доступен и при открытии Fallback отдельной вкладкой. Native Browser не изменён.
