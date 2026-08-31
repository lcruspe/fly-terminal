# UI behavior

## Responsive toolbar

The main Fly Terminal toolbar uses two sequential degradation levels when horizontal space is reduced:

1. **Icon-only mode.** If the full toolbar no longer fits, text labels are hidden while representative icons remain visible. Tooltips and `aria-label` values remain available so actions are still identifiable.
2. **Overflow menu.** If the icon-only toolbar still does not fit, actions are moved from the right edge into the overflow menu. The overflow trigger is always represented by the three-dot icon. Items moved into the menu regain their text labels.

On touch-capable devices, every active tab exposes a **Клавиатура** action. It synchronously focuses the tab's native mobile input: ttyd's xterm helper textarea for Terminal, Selkies/noVNC's touch input for compatible Browser/Desktop frames, or the WebRTC desktop text bridge. The action is hidden on non-touch devices. Terminal, Selkies, and noVNC keystrokes flow directly to the remote session; the WebRTC bridge clears its temporary text field after sending or cancelling.

The collapse/expand-panel action stays directly accessible and switches to icon-only mode together with the rest of the toolbar, but is not moved into overflow.

Responsive layout is recalculated on toolbar/window resize and when toolbar items are shown/hidden or split-layout controls change. The implementation restores all items to their canonical DOM positions before each measurement, so widening the browser reverses the degradation automatically: overflow items return first, then labels are restored when space permits.

When adding new top-level toolbar actions, include them in the responsive toolbar item set and provide a representative icon plus a meaningful `title`/`aria-label`. Do not introduce fixed breakpoint-specific hiding for individual actions; capacity is determined from the actual rendered width.

## Edge-to-edge horizontal layout

The Fly Terminal shell has no horizontal page padding. The terminal/browser workspace, tab bar, and main toolbar therefore span the full viewport width, while the 14 px vertical shell padding and 12 px vertical spacing between sections are preserved. Do not reintroduce horizontal padding on `.shell`; add any required spacing inside individual controls instead.

## Tab close controls

Tab close controls remain in the DOM but are visually hidden until the corresponding tab is hovered. This behavior is shared by horizontal tabs, regular vertical sidebars, and the compact vertical sidebar. In non-compact layouts the hidden control keeps its layout space, so tab width and label position do not jump when the close control appears.

In compact vertical sidebar mode the close control is positioned as an overlay in the tab corner instead of consuming layout space. This keeps the compact tab label centered while still allowing every tab to be closed. Do not hide compact close controls with `display: none`; use the shared hover visibility behavior instead.

## Floating menus

Settings, Tools, dropdown, responsive overflow, and Apps surfaces are positioned in viewport coordinates and then translated to the browser's actual fixed-position containing block. This matters because CSS properties such as `backdrop-filter`, `filter`, `transform`, `perspective`, and layout/paint containment can make a fixed descendant relative to an ancestor instead of the viewport. Desktop popups are measured after size constraints and clamped to the viewport.

Only one top-level menu surface remains active at a time. A transparent fixed `menuBackdrop` is placed above terminal/browser frames, including frame fullscreen, and below the toolbar/menu surfaces. Its `pointerdown` closes all menu types through the shared `closeAllMenus()` path, so a click in iframe-covered workspace cannot be swallowed by the iframe. `Escape` uses the same close path; clicks inside the currently open menu do not dismiss it.

On coarse-pointer/touch devices, floating menus switch to a viewport bottom-sheet presentation: 8 px viewport inset, height capped at roughly 78% of the dynamic viewport, safe-area-aware bottom padding, and controls with at least 48 px touch height. Apps uses the same sheet surface but replaces desktop cascade flyouts with one level at a time; entering Mac Apps, VM Apps, or Snippets shows the selected level and an in-sheet **Назад** action restores the Apps root. These behaviors are part of the menu interaction contract and should be covered by automated and browser smoke tests whenever menu positioning or state management changes.

## Remote Desktop settings

Remote Desktop-specific controls inside Settings are grouped under a native collapsed `details.remote-desktop-settings` section. The section is closed on every page load; its expanded/collapsed state is intentionally not persisted.

The group contains desktop transport mode, RDC resolution, RDC scale mode, FPS, and both main/virtual display resolution controls. General UI controls such as density, toolbar orientation, font size/family, and window title remain outside the group. Existing control IDs and preference bindings must remain stable when the group presentation changes.
