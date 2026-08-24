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
