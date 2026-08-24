#!/usr/bin/env python3
from pathlib import Path
import re

INDEX = Path("index.html")
DOCS = Path("TOOLS.md")

html = INDEX.read_text(encoding="utf-8")
docs = DOCS.read_text(encoding="utf-8")


def sub_once(pattern, replacement, text, *, flags=0, label="pattern"):
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"{label}: expected one replacement, got {count}")
    return updated


tools_html = '''          <details class="settings tools-menu" id="toolsMenu">
            <summary class="button">Tools</summary>
            <div class="settings-panel">
              <div class="settings-group tools-section tools-vpn-section">
                <span class="settings-label">VPN</span>
                <label class="tools-field-label" for="happSubscription">Подписка</label>
                <select id="happSubscription" aria-label="Подписка Happ"><option value="">Загрузка...</option></select>
                <label class="tools-field-label" for="happLocation">Локация</label>
                <select id="happLocation" aria-label="Локация Happ"><option value="">Сначала выберите подписку</option></select>
                <div class="settings-action-status" id="happLocationStatus"></div>
                <div class="vpn-action-row">
                  <button type="button" id="reconnectHapp" title="Отключить и снова подключить активную конфигурацию Happ Plus через macOS scutil">
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 8a6 6 0 0 1 10.2-4.2"/><path d="M12.5 1.8v3.8H8.7"/><path d="M14 8a6 6 0 0 1-10.2 4.2"/><path d="M3.5 14.2v-3.8h3.8"/></svg>
                    Переподключить
                  </button>
                  <div class="settings-action-status" id="happStatus"></div>
                </div>
              </div>

              <div class="settings-group settings-action tools-section file-transfer-section">
                <span class="settings-label">Обмен файлами</span>
                <div class="file-transfer-control">
                  <input class="file-transfer-mode-input" type="radio" name="fileTransferMode" id="fileTransferToVm" checked />
                  <input class="file-transfer-mode-input" type="radio" name="fileTransferMode" id="fileTransferToLocal" />
                  <div class="file-transfer-switch" role="tablist" aria-label="Направление передачи файлов">
                    <label for="fileTransferToVm" role="tab">На виртуальную машину</label>
                    <label for="fileTransferToLocal" role="tab">На локальный компьютер</label>
                  </div>

                  <div class="file-transfer-panel file-transfer-vm-panel">
                    <input class="file-upload-input" type="file" id="documentsUploadInput" multiple aria-label="Файлы для загрузки на виртуальную машину" />
                    <div class="file-tools-actions">
                      <button type="button" id="documentsUploadBtn" title="Загрузить выбранные файлы в Documents виртуальной машины">Загрузить</button>
                      <button type="button" id="documentsRefreshBtn" title="Обновить список файлов">Обновить</button>
                    </div>
                    <div class="settings-action-status" id="documentsStatus"></div>
                    <div class="document-file-list" id="documentsFileList" aria-live="polite"></div>
                  </div>

                  <div class="file-transfer-panel file-transfer-local-panel">
                    <button type="button" id="containerFileBrowseBtn" title="Выбрать файл на виртуальной машине и скачать его на локальный компьютер">
                      Выбрать файл на виртуальной машине
                    </button>
                    <div class="settings-action-status" id="containerFileStatus"></div>
                  </div>
                </div>
              </div>

              <div class="settings-group settings-action tools-section system-tools-section">
                <span class="settings-label">Система</span>
                <button type="button" id="recoverStack" title="Перезапустить Colima/Docker, browser-контейнер, Caddy и ttyd через штатные LaunchAgents">
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 8a6 6 0 0 1 10.2-4.2"/><path d="M12.5 1.8v3.8H8.7"/><path d="M14 8a6 6 0 0 1-10.2 4.2"/><path d="M3.5 14.2v-3.8h3.8"/></svg>
                  Восстановить Chromium
                </button>
                <div class="settings-action-status" id="recoveryStatus"></div>
                <button type="button" id="updateStack" title="Забрать последнюю версию из origin/main и перезапустить стек">
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4.5A6 6 0 0 1 13.5 3L15 4.5"/><path d="M15 1.5v3h-3"/><path d="M13 11.5A6 6 0 0 1 2.5 13L1 11.5"/><path d="M1 14.5v-3h3"/></svg>
                  Обновить Fly Terminal
                </button>
                <div class="settings-action-status" id="updateStatus"></div>
              </div>
            </div>
          </details>
'''

html = sub_once(
    r'          <details class="settings tools-menu" id="toolsMenu">.*?          </details>\n(?=          <details class="dropdown overflow-menu")',
    tools_html,
    html,
    flags=re.S,
    label="tools panel",
)

new_dialog = '''  <dialog class="container-file-dialog" id="containerFileDialog">
    <div class="container-file-picker">
      <div class="container-file-picker-header">
        <strong>Файлы виртуальной машины</strong>
        <button type="button" id="containerFileCloseBtn" title="Закрыть">✕</button>
      </div>
      <div class="container-file-picker-toolbar">
        <button type="button" id="containerFileUpBtn" title="На уровень выше">↑</button>
        <div class="container-file-picker-path" id="containerFilePath" title="Текущий путь">/config</div>
      </div>
      <div class="container-file-picker-entries" id="containerFileEntries" aria-live="polite"></div>
      <div class="container-file-picker-footer">
        <div class="settings-action-status" id="containerFilePickerStatus"></div>
        <button type="button" id="containerFileCancelBtn">Закрыть</button>
      </div>
    </div>
  </dialog>'''
html = sub_once(
    r'  <dialog class="container-file-dialog" id="containerFileDialog">.*?  </dialog>',
    new_dialog,
    html,
    flags=re.S,
    label="container dialog",
)

if ".file-transfer-switch {" not in html:
    css = '''    .tools-field-label {
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      margin-top: 2px;
    }

    .vpn-action-row {
      align-items: center;
      display: grid;
      gap: 6px;
      grid-template-columns: auto minmax(0, 1fr);
    }

    .vpn-action-row .settings-action-status {
      min-height: 0;
    }

    .file-transfer-control {
      display: grid;
      gap: 9px;
    }

    .file-transfer-mode-input {
      height: 1px;
      opacity: 0;
      pointer-events: none;
      position: absolute;
      width: 1px;
    }

    .file-transfer-switch {
      background: var(--control);
      border: 1px solid var(--border);
      border-radius: var(--control-radius);
      display: grid;
      gap: 3px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      padding: 3px;
    }

    .file-transfer-switch label {
      align-items: center;
      border-radius: 7px;
      color: var(--muted);
      cursor: pointer;
      display: flex;
      font-size: 11px;
      font-weight: 700;
      justify-content: center;
      line-height: 1.2;
      min-height: 34px;
      padding: 6px 8px;
      text-align: center;
    }

    #fileTransferToVm:checked ~ .file-transfer-switch label[for="fileTransferToVm"],
    #fileTransferToLocal:checked ~ .file-transfer-switch label[for="fileTransferToLocal"] {
      background: var(--accent);
      color: var(--active-btn-ink);
    }

    .file-transfer-panel {
      display: grid;
      gap: 8px;
    }

    #fileTransferToLocal:checked ~ .file-transfer-vm-panel,
    #fileTransferToVm:checked ~ .file-transfer-local-panel {
      display: none;
    }

    .file-transfer-local-panel > button {
      min-height: 42px;
    }

    .system-tools-section > button + .settings-action-status {
      margin-top: -2px;
    }

'''
    html = html.replace("    .container-file-dialog {", css + "    .container-file-dialog {", 1)

html = sub_once(
    r'    function renderHappState\(payload\) \{.*?\n    \}\n\n    function renderHappLocationOptions',
    '''    function renderHappState(payload) {
      const state = payload?.state || "Unknown";
      if (payload?.location && happLocationStatus) {
        happLocationStatus.textContent = payload?.subscription
          ? `Сейчас: ${payload.subscription} → ${payload.location}`
          : `Сейчас: ${payload.location}`;
      }
      if (state === "Connected") {
        setHappStatus("", "");
      } else if (state === "Connecting" || state === "Disconnecting") {
        setHappStatus("warn", `${payload?.service || "Happ Plus"}: ${state}`);
      } else {
        setHappStatus(payload?.ok === false ? "danger" : "", `${payload?.service || "Happ Plus"}: ${state}`);
      }
    }

    function renderHappLocationOptions''',
    html,
    flags=re.S,
    label="renderHappState",
)

html = sub_once(
    r'    async function openContainerFileBrowser\(\) \{.*?\n    \}\n\n    function closeContainerFileBrowser',
    '''    async function openContainerFileBrowser() {
      if (!containerFileDialog) return;
      if (!containerFileDialog.open) containerFileDialog.showModal();
      setContainerFileStatus("", "");
      containerFileCurrentPath = "/config";
      await loadContainerDirectory("/config");
    }

    function closeContainerFileBrowser''',
    html,
    flags=re.S,
    label="openContainerFileBrowser",
)

# Documentation: collapse two technical file bullets into one user-facing tool and document the new IA.
docs = docs.replace(
    '- **Файлы Documents** — загрузка произвольных файлов в `~/Documents` виртуальной машины, просмотр списка и скачивание файлов через браузер.\n- **Файлы контейнера** — ручной просмотр файловой системы Chromium-контейнера и скачивание выбранного файла напрямую на локальный компьютер.\n',
    '- **Обмен файлами** — единый интерфейс с двумя направлениями: загрузка файлов **на виртуальную машину** и выбор файла **на виртуальной машине** для скачивания на локальный компьютер.\n',
    1,
)

layout_doc = '''\n## Компоновка интерфейса Tools\n\nПользовательский интерфейс Tools организован по задачам, а не по внутренним компонентам реализации:\n\n1. **VPN** — подписка, локация, текущая активная связка и действие переподключения находятся в одном блоке. Отдельный блок `VPN Happ` не используется.\n2. **Обмен файлами** — единый блок с переключателем направления **«На виртуальную машину» / «На локальный компьютер»**. В первом режиме доступны upload и содержимое `Documents`; во втором открывается файловый браузер виртуальной машины. Термин `контейнер` в пользовательском UI не используется.\n3. **Система** — восстановление Chromium и обновление Fly Terminal собраны в отдельном административном блоке.\n\nСтатусные строки файлового обмена по умолчанию пусты и используются только для текущей операции, результата или ошибки. Файловый браузер при каждом открытии начинает навигацию с `/config`, поскольку это основной пользовательский каталог Chromium; переход выше по дереву остаётся доступным кнопкой `↑`.\n'''
if "## Компоновка интерфейса Tools" not in docs:
    docs = docs.replace("\n## Контракт ошибок Tools\n", layout_doc + "\n## Контракт ошибок Tools\n", 1)

docs = docs.replace(
    'В **Tools → Файлы контейнера** кнопка **«Выбрать файл и скачать»** открывает серверный файловый браузер Chromium-контейнера',
    'В **Tools → Обмен файлами → На локальный компьютер** кнопка **«Выбрать файл на виртуальной машине»** открывает серверный файловый браузер Chromium-контейнера',
    1,
)
docs = docs.replace(
    'Навигация начинается с `/`: пользователь вручную переходит по каталогам',
    'Навигация начинается с `/config`: пользователь вручную переходит по каталогам; кнопка `↑` позволяет подняться вплоть до `/`',
    1,
)

INDEX.write_text(html, encoding="utf-8")
DOCS.write_text(docs, encoding="utf-8")
