# UI behavior

## Responsive toolbar

The main Fly Terminal toolbar uses two sequential degradation levels when horizontal space is reduced:

1. **Icon-only mode.** If the full toolbar no longer fits, text labels are hidden while representative icons remain visible. Tooltips and `aria-label` values remain available so actions are still identifiable.
2. **Overflow menu.** If the icon-only toolbar still does not fit, actions are moved from the right edge into the overflow menu. The overflow trigger is always represented by the three-dot icon. Items moved into the menu regain their text labels.

The collapse/expand-panel action stays directly accessible and switches to icon-only mode together with the rest of the toolbar, but is not moved into overflow.

Responsive layout is recalculated on toolbar/window resize and when toolbar items are shown/hidden or split-layout controls change. The implementation restores all items to their canonical DOM positions before each measurement, so widening the browser reverses the degradation automatically: overflow items return first, then labels are restored when space permits.

When adding new top-level toolbar actions, include them in the responsive toolbar item set and provide a representative icon plus a meaningful `title`/`aria-label`. Do not introduce fixed breakpoint-specific hiding for individual actions; capacity is determined from the actual rendered width.

## Edge-to-edge horizontal layout

The Fly Terminal shell has no horizontal page padding. The terminal/browser workspace, tab bar, and main toolbar therefore span the full viewport width, while the 14 px vertical shell padding and 12 px vertical spacing between sections are preserved. Do not reintroduce horizontal padding on `.shell`; add any required spacing inside individual controls instead.

## Tab close controls

Tab close controls remain in the DOM but are visually hidden until the corresponding tab is hovered. This behavior is shared by horizontal tabs, regular vertical sidebars, and the compact vertical sidebar. In non-compact layouts the hidden control keeps its layout space, so tab width and label position do not jump when the close control appears.

In compact vertical sidebar mode the close control is positioned as an overlay in the tab corner instead of consuming layout space. This keeps the compact tab label centered while still allowing every tab to be closed. Do not hide compact close controls with `display: none`; use the shared hover visibility behavior instead.

## Floating menus

Settings, Tools, dropdown, and responsive overflow panels are positioned in viewport coordinates and then translated to the browser's actual fixed-position containing block. This matters because CSS properties such as `backdrop-filter`, `filter`, `transform`, `perspective`, and layout/paint containment can make a fixed descendant relative to an ancestor instead of the viewport. After size constraints are applied, the rendered popup is measured and both axes are clamped to a 10 px viewport inset. The same positioning contract applies to horizontal and vertical toolbar orientations.

Only one top-level floating menu should remain active at a time. Clicking outside `details.settings` / `details.dropdown` closes open floating menus, and `Escape` closes them as well. Clicks inside the currently open menu must not dismiss it. These behaviors are part of the menu interaction contract and should be covered by browser smoke tests whenever positioning logic changes.
