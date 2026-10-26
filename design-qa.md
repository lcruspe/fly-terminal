# Gateway catalogue visual QA

final result: passed

- Scope: approved redesign of the existing catalogue, preserving all service links, independent RoomAudio statuses, three views and action menus.
- Source baseline: `image-20261026-184824.png`, supplied by the user; 985 × 319 pixels. The agreed target intentionally replaces the uneven cards with a uniform graphite layout, library icons, a shared status footer and blue selection accents.
- Matching capture: `output/playwright/gateway-redesign-comparison.png`, 985 × 319 CSS pixels, device scale 1. Source and implementation compared together without rescaling in `output/playwright/gateway-design-comparison.png`.
- State: authenticated live Caddy catalogue; tiles selected, menus closed, Mac available and audio source offline. Comparison concerns the approved redesign, not pixel fidelity to the rejected baseline.
- Full desktop evidence: `output/playwright/gateway-redesign-tiles.png`, 985 × 600.
- Additional evidence: `output/playwright/gateway-redesign-mobile.png` and `gateway-redesign-menu.png`, 390 × 844; `gateway-redesign-table.png`, 985 × 600, all under `output/playwright/`.

## Comparison history

1. P2: the first redesign increased card height enough to crop the second status row in the source viewport. Reduced tiles to 112 px, compact tiles to 96 px, and tightened page and grid spacing.
2. Final side-by-side comparison: all six card headers and statuses fit the source viewport; card heights, status baselines and menu positions are consistent. The final mobile and table captures were also visually inspected. No actionable P0/P1/P2 findings remain.

## Interaction verification

- Live rendered page at `http://127.0.0.1:8080/`, through Caddy and the actual status API.
- All three views checked at widths 1280, 985, 390 and 320 px: equal card heights and no page overflow or footer clipping.
- Browser, RoomAudio and OpenWrt action menus checked in each combination: visible, inside the viewport and aligned with their trigger; Escape restores the closed state.
- Status labels and separate Mac/source states update from live data. Icons are embedded Bootstrap Icons 1.11.3 assets, requiring no external font or asset requests.
- Three existing catalogue tests pass. JavaScript syntax and whitespace checks pass. Browser console: no errors or warnings.
- No service start/stop operations were issued during this visual check. External Windows Chromium appearance was not independently retested.

## Follow-up polish

None required for the approved scope. Evidence screenshots remain local verification artifacts.
