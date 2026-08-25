#!/usr/bin/env python3
from pathlib import Path


def replace_once(path, old, new, label):
    text = Path(path).read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"anchor not found: {label}")
    Path(path).write_text(text.replace(old, new, 1), encoding="utf-8")


# index.html: preserve the two UI fixes from the recovered local patch.
replace_once(
    "index.html",
    '''    .shell[class*="orientation-vertical-"] .toolbar {
      flex: 1 1 auto;
      flex-direction: column;
      align-items: stretch;
      justify-content: flex-start;
      padding: 10px;
      gap: 10px;
      overflow-y: auto;
      overflow-x: hidden;
    }
''',
    '''    .shell[class*="orientation-vertical-"] .toolbar {
      flex: 1 1 auto;
      flex-direction: column;
      align-items: stretch;
      justify-content: flex-start;
      padding: 10px;
      gap: 10px;
      overflow-y: auto;
      overflow-x: hidden;
      /* Keep fixed flyout menus viewport-relative instead of clipping them to
         the scrollable sidebar's backdrop-filter containing block. */
      backdrop-filter: none;
      -webkit-backdrop-filter: none;
    }
''',
    "vertical toolbar flyout fix",
)

replace_once(
    "index.html",
    '''    input[type="text"] {
''',
    '''    /* Native popup rows may ignore theme backgrounds while inheriting the
       themed foreground, leaving light text invisible until hover. */
    select option,
    select optgroup {
      background: Canvas;
      color: CanvasText;
    }

    input[type="text"] {
''',
    "native select option colors",
)

replace_once(
    "index.html",
    '''    let preferences = readPreferences();
    let statusResetTimer = null;
''',
    '''    let preferences = readPreferences();
    let persistPreferencesTimer = null;
    let statusResetTimer = null;
''',
    "preferences debounce timer",
)

old_preferences = '''    function readPreferences() {
      try {
        const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
        const validLayouts = ["grid", "columns", "rows", "master-left", "master-top"];
        return {
          theme: themes[raw.theme] ? raw.theme : "paper",
          fontSize: fontSizes.includes(Number(raw.fontSize)) ? Number(raw.fontSize) : 12,
          fontFamily: fontFamilies.some(f => f.value === raw.fontFamily) ? raw.fontFamily : fontFamilies[0].value,
          windowTitle: normalizeWindowTitle(raw.windowTitle),
          splitLayout: validLayouts.includes(raw.splitLayout) ? raw.splitLayout : "grid",
          panelCollapsed: !!raw.panelCollapsed
        };
      } catch {
        return { theme: "paper", fontSize: 12, fontFamily: fontFamilies[0].value, windowTitle: "Terminal", splitLayout: "grid", panelCollapsed: false };
      }
    }

    function savePreferences() {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
      applyAllThemes();
      applyWindowTitle();
    }

    async function persistThemePreference() {
      try {
        const response = await localApiFetch("/api/ui/preferences", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ theme: preferences.theme })
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
      } catch (error) {
        console.warn("Unable to persist Fly Terminal theme on server", error);
      }
    }

    async function loadPersistedTheme() {
      try {
        const response = await localApiFetch("/api/ui/preferences");
        if (!response.ok) return;
        const payload = await response.json().catch(() => ({}));
        if (payload?.theme && themes[payload.theme]) {
          preferences.theme = payload.theme;
          localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
          return;
        }
        if (themes[preferences.theme]) {
          await persistThemePreference();
        }
      } catch (error) {
        console.warn("Unable to load persisted Fly Terminal theme", error);
      }
    }
'''
new_preferences = '''    function readPreferencesFromObject(raw = {}) {
      const validLayouts = ["grid", "columns", "rows", "master-left", "master-top"];
      return {
        theme: themes[raw.theme] ? raw.theme : "paper",
        fontSize: fontSizes.includes(Number(raw.fontSize)) ? Number(raw.fontSize) : 12,
        fontFamily: fontFamilies.some(f => f.value === raw.fontFamily) ? raw.fontFamily : fontFamilies[0].value,
        windowTitle: normalizeWindowTitle(raw.windowTitle),
        splitLayout: validLayouts.includes(raw.splitLayout) ? raw.splitLayout : "grid",
        panelCollapsed: !!raw.panelCollapsed,
        density: ["comfortable", "compact"].includes(raw.density) ? raw.density : "comfortable",
        toolbarOrientation: ["horizontal", "vertical-left", "vertical-right"].includes(raw.toolbarOrientation) ? raw.toolbarOrientation : "horizontal"
      };
    }

    function readPreferences() {
      try {
        return readPreferencesFromObject(JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"));
      } catch {
        return readPreferencesFromObject();
      }
    }

    function savePreferences() {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
      applyAllThemes();
      applyWindowTitle();
      clearTimeout(persistPreferencesTimer);
      persistPreferencesTimer = setTimeout(persistUiPreferences, 180);
    }

    async function persistUiPreferences() {
      try {
        const response = await localApiFetch("/api/ui/preferences", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(preferences)
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
      } catch (error) {
        console.warn("Unable to persist Fly Terminal UI preferences on server", error);
      }
    }

    async function loadPersistedPreferences() {
      try {
        const response = await localApiFetch("/api/ui/preferences");
        if (!response.ok) return;
        const payload = await response.json().catch(() => ({}));
        const persistedKeys = ["theme", "fontSize", "fontFamily", "windowTitle", "splitLayout", "panelCollapsed", "density", "toolbarOrientation"];
        const hasPersistedPreferences = persistedKeys.some(key => payload?.[key] !== undefined && payload?.[key] !== null);
        if (hasPersistedPreferences) {
          preferences = readPreferencesFromObject({ ...preferences, ...payload });
          localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
          return;
        }
        await persistUiPreferences();
      } catch (error) {
        console.warn("Unable to load persisted Fly Terminal UI preferences", error);
      }
    }
'''
replace_once("index.html", old_preferences, new_preferences, "full UI preference persistence")

replace_once(
    "index.html",
    '''    themeButtons.forEach(btn => btn.onclick = () => {
      preferences.theme = btn.dataset.theme;
      savePreferences();
      persistThemePreference();
    });
''',
    '''    themeButtons.forEach(btn => btn.onclick = () => {
      preferences.theme = btn.dataset.theme;
      savePreferences();
    });
''',
    "theme persistence deduplication",
)

replace_once(
    "index.html",
    '''    async function initializeApp() {
      await loadPersistedTheme();
      applyShellTheme();
      refreshDirectLink();
''',
    '''    async function initializeApp() {
      await loadPersistedPreferences();
      fontSizeSelect.value = preferences.fontSize;
      fontFamilySelect.value = preferences.fontFamily;
      windowTitleInput.value = preferences.windowTitle;
      uiDensitySelect.value = preferences.density;
      document.body.classList.toggle("density-compact", preferences.density === "compact");
      toolbarOrientationSelect.value = preferences.toolbarOrientation;
      applyToolbarOrientation(preferences.toolbarOrientation);
      applyPanelCollapsedPref();
      applyShellTheme();
      applyWindowTitle();
      refreshDirectLink();
''',
    "startup preference restore",
)

# session-control.py: promote the whole UI preference set to backend-canonical state.
replace_once(
    "session-control.py",
    '''VALID_UI_THEMES = frozenset({
    "paper", "linen", "ledger", "harbor", "sage",
    "graphite", "ink", "midnight", "nord", "forest",
})
''',
    '''VALID_UI_THEMES = frozenset({
    "paper", "linen", "ledger", "harbor", "sage",
    "graphite", "ink", "midnight", "nord", "forest",
})
VALID_UI_DENSITIES = frozenset({"comfortable", "compact"})
VALID_TOOLBAR_ORIENTATIONS = frozenset({"horizontal", "vertical-left", "vertical-right"})
VALID_SPLIT_LAYOUTS = frozenset({"grid", "columns", "rows", "master-left", "master-top"})
VALID_FONT_SIZES = frozenset(range(8, 17))
VALID_UI_FONT_FAMILIES = frozenset({
    "Menlo, monospace",
    "Monaco, monospace",
    "Courier New, monospace",
    "Andale Mono, monospace",
    "Consolas, monospace",
    "SFMono-Regular, SF Mono, Menlo, monospace",
    "monospace",
})
''',
    "UI preference allowlists",
)

replace_once(
    "session-control.py",
    '''    "invalid_theme": "Выбрана неизвестная тема оформления.",
    "ui_preferences_write_failed": "Не удалось сохранить тему оформления.",
''',
    '''    "invalid_theme": "Выбрана неизвестная тема оформления.",
    "invalid_ui_preferences": "Переданы некорректные настройки интерфейса.",
    "ui_preferences_write_failed": "Не удалось сохранить настройки интерфейса.",
''',
    "UI preference errors",
)

old_backend = '''def read_ui_preferences():
    with UI_PREFERENCES_LOCK:
        if not UI_PREFERENCES_FILE.exists():
            return {"ok": True, "theme": None}
        try:
            payload = json.loads(UI_PREFERENCES_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"ok": True, "theme": None}

    theme = str(payload.get("theme") or "").strip()
    if theme not in VALID_UI_THEMES:
        theme = ""
    return {"ok": True, "theme": theme or None}


def write_ui_preferences(theme):
    payload = {
        "theme": theme,
        "updatedAt": datetime.now().isoformat(),
    }
    UI_PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = UI_PREFERENCES_FILE.with_name(f"{UI_PREFERENCES_FILE.name}.tmp")
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\\n"
    with UI_PREFERENCES_LOCK:
        temp_path.write_text(serialized, encoding="utf-8")
        os.replace(temp_path, UI_PREFERENCES_FILE)
'''
new_backend = '''def normalize_ui_preferences(payload):
    if not isinstance(payload, dict):
        return {}

    preferences = {}
    theme = str(payload.get("theme") or "").strip()
    if theme in VALID_UI_THEMES:
        preferences["theme"] = theme

    density = str(payload.get("density") or "").strip()
    if density in VALID_UI_DENSITIES:
        preferences["density"] = density

    orientation = str(payload.get("toolbarOrientation") or "").strip()
    if orientation in VALID_TOOLBAR_ORIENTATIONS:
        preferences["toolbarOrientation"] = orientation

    split_layout = str(payload.get("splitLayout") or "").strip()
    if split_layout in VALID_SPLIT_LAYOUTS:
        preferences["splitLayout"] = split_layout

    try:
        font_size = int(payload.get("fontSize"))
    except (TypeError, ValueError):
        font_size = 0
    if font_size in VALID_FONT_SIZES:
        preferences["fontSize"] = font_size

    font_family = str(payload.get("fontFamily") or "").strip()
    if font_family in VALID_UI_FONT_FAMILIES:
        preferences["fontFamily"] = font_family

    window_title = str(payload.get("windowTitle") or "").strip()
    if window_title:
        preferences["windowTitle"] = window_title[:80]

    if isinstance(payload.get("panelCollapsed"), bool):
        preferences["panelCollapsed"] = payload["panelCollapsed"]
    return preferences


def read_ui_preferences():
    with UI_PREFERENCES_LOCK:
        if not UI_PREFERENCES_FILE.exists():
            return {"ok": True, "theme": None}
        try:
            payload = json.loads(UI_PREFERENCES_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"ok": True, "theme": None}

    preferences = normalize_ui_preferences(payload)
    return {"ok": True, **preferences}


def write_ui_preferences(preferences):
    UI_PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = UI_PREFERENCES_FILE.with_name(f"{UI_PREFERENCES_FILE.name}.tmp")
    with UI_PREFERENCES_LOCK:
        current = {}
        if UI_PREFERENCES_FILE.exists():
            try:
                current = normalize_ui_preferences(json.loads(UI_PREFERENCES_FILE.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
        payload = {**current, **preferences, "updatedAt": datetime.now().isoformat()}
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\\n"
        temp_path.write_text(serialized, encoding="utf-8")
        os.replace(temp_path, UI_PREFERENCES_FILE)
'''
replace_once("session-control.py", old_backend, new_backend, "backend preference store")

replace_once(
    "session-control.py",
    '''        theme = str(payload.get("theme") or "").strip()
        if theme not in VALID_UI_THEMES:
            send_json(self, 400, {"ok": False, "error": "invalid_theme"})
            return

        try:
            write_ui_preferences(theme)
        except OSError as exc:
            send_json(self, 500, {"ok": False, "error": "ui_preferences_write_failed", "details": str(exc)})
            return

        send_json(self, 200, {"ok": True, "theme": theme})
''',
    '''        preferences = normalize_ui_preferences(payload)
        if not preferences:
            send_json(self, 400, {"ok": False, "error": "invalid_ui_preferences"})
            return

        try:
            write_ui_preferences(preferences)
        except OSError as exc:
            send_json(self, 500, {"ok": False, "error": "ui_preferences_write_failed", "details": str(exc)})
            return

        send_json(self, 200, {"ok": True, **preferences})
''',
    "UI preference POST handler",
)

# THEMING.md: restore the intended persistence contract, updated to match the stricter backend.
replace_once(
    "THEMING.md",
    '''The selected **theme** is persisted in two layers. The backend stores the canonical value in `~/.local/share/fly-terminal/ui-preferences.json` (override with `FLY_TERMINAL_UI_PREFERENCES_FILE`), while browser `localStorage` remains a fast cache and fallback. On startup the backend value wins; if the backend has no saved theme yet, the browser's current local theme seeds it. This keeps the theme stable across terminal sessions, browser restarts, and different browser entry origins that point to the same Fly Terminal backend.\n\nFont size, font family, window title, layout and panel state remain browser-local preferences. The selected theme continues to drive the embedded ttyd/xterm colors.\n''',
    '''UI settings are persisted in two layers. The backend stores the canonical theme, font size and family, window title, split layout, density, toolbar orientation, and panel state in `~/.local/share/fly-terminal/ui-preferences.json` (override with `FLY_TERMINAL_UI_PREFERENCES_FILE`), while browser `localStorage` remains a fast cache and fallback. On startup the backend value wins; if the backend has no saved settings yet, the browser's current local settings seed it. This keeps the interface stable across terminal sessions, browser restarts, and different browser entry origins that point to the same Fly Terminal backend. Server-side validation uses the same finite theme, font, layout, density, and orientation choices exposed by the UI; partial writes merge with the existing preference file for backward compatibility.\n''',
    "theming persistence docs",
)
