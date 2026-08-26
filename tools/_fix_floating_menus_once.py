from pathlib import Path

INDEX = Path("index.html")
UI_DOC = Path("UI.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label} not found")
    return text.replace(old, new, 1)


html = INDEX.read_text(encoding="utf-8")

old_height = """        const spaceAbove = buttonRect.top - gap - viewportPad;
        maxHeight = Math.max(120, Math.min(spaceAbove, viewportHeight - viewportPad * 2));"""
new_height = """        // Size against the viewport first, then place the measured box.
        // This avoids border/padding differences leaking a tall popup above the viewport.
        maxHeight = Math.max(1, viewportHeight - viewportPad * 2);"""
html = replace_once(html, old_height, new_height, "horizontal max-height block")

old_anchor = """        // Use bottom anchor directly: distance from bottom of screen to top of toolbar button
        const bottomDistance = viewportHeight - buttonRect.top + gap;

        menu.style.position = \"fixed\";
        menu.style.left = `${Math.round(left)}px`;
        menu.style.bottom = `${Math.round(bottomDistance)}px`;
        menu.style.top = \"auto\";
        menu.style.right = \"auto\";
        menu.style.maxHeight = `${Math.floor(maxHeight)}px`;
        menu.style.maxWidth = `${Math.floor(maxWidth)}px`;
        menu.style.zIndex = \"9999\";
        menu.style.transformOrigin = \"bottom right\";
        return;"""
new_anchor = """        menu.style.position = \"fixed\";
        menu.style.left = `${Math.round(left)}px`;
        menu.style.top = `${viewportPad}px`;
        menu.style.bottom = \"auto\";
        menu.style.right = \"auto\";
        menu.style.maxHeight = `${Math.floor(maxHeight)}px`;
        menu.style.maxWidth = `${Math.floor(maxWidth)}px`;
        menu.style.zIndex = \"9999\";
        menu.style.transformOrigin = \"bottom right\";

        // Measure after max-size constraints have been applied, then clamp both axes.
        // Top-based placement remains deterministic even if popup chrome changes height.
        const fittedRect = menu.getBoundingClientRect();
        const fittedHeight = Math.min(fittedRect.height, maxHeight);
        const fittedWidth = Math.min(fittedRect.width, maxWidth);
        left = clampNumber(
          buttonRect.right - fittedWidth,
          viewportPad,
          Math.max(viewportPad, viewportWidth - viewportPad - fittedWidth)
        );
        top = clampNumber(
          buttonRect.top - gap - fittedHeight,
          viewportPad,
          Math.max(viewportPad, viewportHeight - viewportPad - fittedHeight)
        );
        menu.style.left = `${Math.round(left)}px`;
        menu.style.top = `${Math.round(top)}px`;
        return;"""
html = replace_once(html, old_anchor, new_anchor, "horizontal anchor block")

old_bind = """    function bindFloatingMenus() {
      floatingMenuResizeObserver = new ResizeObserver(() => positionOpenFloatingMenus());
      document.querySelectorAll(\"details.settings, details.dropdown\").forEach((details) => {"""
new_bind = """    function closeFloatingMenus({ except = null } = {}) {
      document.querySelectorAll(\"details.settings[open], details.dropdown[open]\").forEach((details) => {
        if (details === except) return;
        details.removeAttribute(\"open\");
        resetFloatingMenuPosition(details);
      });
    }

    function bindFloatingMenus() {
      floatingMenuResizeObserver = new ResizeObserver(() => positionOpenFloatingMenus());

      document.addEventListener(\"pointerdown\", (event) => {
        const containingMenu = event.target.closest?.(\"details.settings, details.dropdown\") || null;
        closeFloatingMenus({ except: containingMenu });
      });

      document.addEventListener(\"keydown\", (event) => {
        if (event.key === \"Escape\") closeFloatingMenus();
      });

      document.querySelectorAll(\"details.settings, details.dropdown\").forEach((details) => {"""
html = replace_once(html, old_bind, new_bind, "floating menu binding block")

INDEX.write_text(html, encoding="utf-8")

docs = UI_DOC.read_text(encoding="utf-8")
if "## Floating menus" not in docs:
    docs = docs.rstrip() + """

## Floating menus

Settings, Tools, dropdown, and responsive overflow panels use viewport-fixed positioning. After size constraints are applied, the rendered popup is measured and both axes are clamped to a 10 px viewport inset. Do not rely on a bottom anchor alone: borders and padding can otherwise push a tall menu outside the viewport. The same positioning contract applies to horizontal and vertical toolbar orientations.

Only one top-level floating menu should remain active at a time. Clicking outside `details.settings` / `details.dropdown` closes open floating menus, and `Escape` closes them as well. Clicks inside the currently open menu must not dismiss it. These behaviors are part of the menu interaction contract and should be covered by browser smoke tests whenever positioning logic changes.
"""
    UI_DOC.write_text(docs, encoding="utf-8")
