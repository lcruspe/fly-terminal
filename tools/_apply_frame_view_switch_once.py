#!/usr/bin/env python3
from pathlib import Path
import re

INDEX = Path("index.html")
README = Path("README.md")

html = INDEX.read_text(encoding="utf-8")
readme = README.read_text(encoding="utf-8")


def sub_once(pattern, replacement, text, *, flags=0, label="pattern"):
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"{label}: expected one replacement, got {count}")
    return updated


# 1. Remove the duplicated outer visual shell from the old bottom-toolbar layout control.
html = sub_once(
    r"    \.layout-controls \{\n      background: rgba\(255, 255, 255, 0\.16\);\n      border: 1px solid var\(--border\);\n      border-radius: var\(--control-radius\);\n      padding: 3px;\n    \}",
    """    .layout-controls {
      background: transparent;
      border: 0;
      padding: 0;
    }""",
    html,
    label="layout-controls css",
)

# Replace the old nested view-switch styling with one compact segmented control used in frame topbars.
html = sub_once(
    r"    \.view-switch \{\n      background: var\(--control\);\n      border: 1px solid var\(--border\);\n      border-radius: var\(--control-radius\);\n      display: inline-flex;\n      padding: 3px;\n    \}\n\n    \.view-switch button \{\n      border-color: transparent;\n      box-shadow: none;\n      padding: 6px 8px;\n    \}",
    """    .frame-view-switch {
      align-items: center;
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 8px;
      display: inline-flex;
      gap: 2px;
      padding: 2px;
    }

    .frame-view-mode-btn {
      align-items: center;
      background: transparent;
      border: 0;
      border-radius: 6px;
      box-shadow: none;
      color: var(--terminal-topbar-ink);
      display: inline-flex;
      height: 26px;
      justify-content: center;
      padding: 0;
      transform: none;
      width: 28px;
    }

    .frame-view-mode-btn:hover {
      background: rgba(255, 255, 255, 0.14);
      transform: none;
    }

    .frame-view-mode-btn.active {
      background: var(--accent);
      color: var(--active-btn-ink);
    }""",
    html,
    label="view switch css",
)

# 2. Keep only split-layout presets in the lower toolbar. The view mode selector moves to each frame topbar.
old_toolbar = r'''          <div class="control-group layout-controls" id="layoutControls" aria-label="Режим и компоновка">\n            <span class="control-label">Вид</span>\n            <div class="view-switch" aria-label="Режим отображения">\n              <button type="button" id="viewTabs" class="active" title="Вкладки">\n                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="12" height="8" rx="1"/><path d="M2 7h12"/></svg>\n                Вкладки\n              </button>\n              <button type="button" id="viewSplit" title="Сплит">\n                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="12" height="12" rx="1"/><path d="M8 2v12M2 8h12"/></svg>\n                Сплит\n              </button>\n            </div>\n            <div id="splitLayoutContainer" class="layout-presets-wrapper" style="display: none;">\n              <div id="splitLayoutPresets"></div>\n            </div>\n          </div>'''
new_toolbar = '''          <div class="control-group layout-controls" id="layoutControls" aria-label="Компоновка разделённого режима" hidden>
            <div id="splitLayoutContainer" class="layout-presets-wrapper" style="display: none;">
              <div id="splitLayoutPresets"></div>
            </div>
          </div>'''
html, count = re.subn(old_toolbar, new_toolbar, html, count=1)
if count != 1:
    raise SystemExit(f"toolbar view switch: expected one replacement, got {count}")

# 3. Remove global toolbar button references and responsive-toolbar handling for them.
html = html.replace('    const viewTabsBtn = document.getElementById("viewTabs");\n', '', 1)
html = html.replace('    const viewSplitBtn = document.getElementById("viewSplit");\n', '', 1)
html = html.replace('        viewTabsBtn,\n        viewSplitBtn,\n', '', 1)

# 4. Split-layout presets should only occupy toolbar space while split mode is active.
html = sub_once(
    r"    function renderSplitLayoutPresets\(\) \{\n      const N = tabs\.length;\n      if \(N <= 1\) \{\n        splitLayoutContainer\.style\.display = 'none';\n        return;\n      \}\n      \n      if \(viewMode === 'split'\) \{\n        splitLayoutContainer\.style\.display = 'inline-flex';\n      \} else \{\n        splitLayoutContainer\.style\.display = 'none';\n      \}",
    """    function renderSplitLayoutPresets() {
      const N = tabs.length;
      const showPresets = N > 1 && viewMode === 'split';
      if (layoutControls) layoutControls.hidden = !showPresets;
      splitLayoutContainer.style.display = showPresets ? 'inline-flex' : 'none';
      if (!showPresets) return;""",
    html,
    label="split presets visibility",
)

# 5. Add one-level view selector markup and a global active-state synchronizer.
marker = '    function fullscreenIcon(expanded = false) {'
if marker not in html:
    raise SystemExit('fullscreenIcon marker not found')
view_helpers = '''    function viewModeSwitchMarkup() {
      const tabsActive = viewMode === "tabs";
      const splitActive = viewMode === "split";
      return `
        <div class="frame-view-switch" role="group" aria-label="Режим отображения">
          <button type="button" class="frame-view-mode-btn${tabsActive ? " active" : ""}" data-view-mode="tabs" title="Вкладки" aria-label="Вкладки" aria-pressed="${String(tabsActive)}">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="12" height="8" rx="1"/><path d="M2 7h12"/></svg>
          </button>
          <button type="button" class="frame-view-mode-btn${splitActive ? " active" : ""}" data-view-mode="split" title="Сплит" aria-label="Сплит" aria-pressed="${String(splitActive)}">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="12" height="12" rx="1"/><path d="M8 2v12M2 8h12"/></svg>
          </button>
        </div>`;
    }

    function updateViewModeButtons() {
      document.querySelectorAll(".frame-view-mode-btn").forEach((button) => {
        const active = button.dataset.viewMode === viewMode;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
      });
    }

'''
html = html.replace(marker, view_helpers + marker, 1)

# 6. Put the selector immediately to the right of fullscreen in both terminal and browser topbars.
pattern = r'(            <button type="button" class="frame-control frame-fullscreen-btn" title="На весь экран" aria-label="На весь экран" aria-pressed="false">\n              \$\{fullscreenIcon\(false\)\}\n            </button>)'
html, count = re.subn(pattern, r'\1\n            ${viewModeSwitchMarkup()}', html)
if count != 2:
    raise SystemExit(f"fullscreen insertion: expected 2 replacements, got {count}")

# 7. View mode is now synchronized across all frame-local selectors.
html = sub_once(
    r"      viewTabsBtn\.classList\.toggle\(\"active\", mode === 'tabs'\);\n      viewSplitBtn\.classList\.toggle\(\"active\", mode === 'split'\);",
    "      updateViewModeButtons();",
    html,
    label="setViewMode buttons",
)

html = sub_once(
    r"    viewTabsBtn\.onclick = \(\) => setViewMode\('tabs'\);\n    viewSplitBtn\.onclick = \(\) => setViewMode\('split'\);",
    """    document.addEventListener("click", (event) => {
      const button = event.target.closest?.(".frame-view-mode-btn");
      if (!button) return;
      const mode = button.dataset.viewMode;
      if (mode === "tabs" || mode === "split") setViewMode(mode);
    });""",
    html,
    label="view mode click handler",
)

# 8. Documentation: record the new location and the rationale.
old_bullet = '*   **Двухпанельный интерфейс**: переключение между вкладками (Tabs) и разделением экрана (Split Screen) для параллельной работы.'
new_bullet = '*   **Двухпанельный интерфейс**: переключение между вкладками (Tabs) и разделением экрана (Split Screen) выполняется компактным одноуровневым переключателем в верхней панели каждой рабочей области, сразу справа от кнопки полноэкранного режима. Параметры компоновки Split Mode остаются в основной панели и показываются только в разделённом режиме.'
if old_bullet not in readme:
    raise SystemExit('README interface bullet not found')
readme = readme.replace(old_bullet, new_bullet, 1)

INDEX.write_text(html, encoding="utf-8")
README.write_text(readme, encoding="utf-8")
