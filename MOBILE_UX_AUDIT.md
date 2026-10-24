# Mobile UX audit — 2026-10-25

## Scope and method
- Repository: `lcruspe/fly-terminal`, branch `main`, initial checkout commit `57eafe4`.
- Chrome 155 headless/CDP, device and touch emulation (retested after updating to upstream 454768b): 320×568, 375×667, 390×844, 844×390 CSS px.
- Static HTTP harness served the project's own `index.html`; terminal iframe intentionally returned 404 in this harness. This is not a production service failure.
- Reviewed `UI.md`, `macos/gateway/admin.html`, `macos/gateway/gateway.css`, `manifest.json`, `mobile-keyboard.js`.
- 15/15 current menu/keyboard/position/HUD Node tests passed, but do not cover the browser-level failures.

## Confirmed issues
| Priority | Defect / evidence | Recommended resolution |
| --- | --- | --- |
| **P0** | Settings and Tools become invisible when nested in the toolbar overflow at 320–390px. Click `Ещё` then `Настройки` or `Tools`: child `details.open=true`, parent `#overflowMenu.open=false`, thus the fixed child panel is visually hidden. Root interaction is `layoutResponsiveToolbar()` relocating elements, followed by the floating-menu `toggle` handler closing all other details. | Keep floating panels outside closed parent `details` (single overlay portal), or maintain correct parent state. Add actual browser tests for this sequence. |
| **P1** | Mobile vertical toolbar can consume nearly the whole viewport: at 320px wide, sidebar 220px leaves only **70px** workspace; at 390px, 140px workspace. | Force bottom/horizontal mode on narrow screens without changing the saved desktop orientation preference. |
| **P1** | Main toolbar touch targets are approximately 32×30px; frame controls 28×26–28px. Popup menu targets alone have ≥48px overrides. | Provide ≥44×44px pointer hit boxes for touch controls; retain compact visuals. |
| **P1** | `.tab-close` relies on `:hover`, otherwise `opacity:0; pointer-events:none`; measured content 12×14px. | Expose a touch-specific close affordance or context action with adequate hit area. |
| **P2** | At 320px the keyboard action is relegated to `Ещё`; at 390px it uses 104×30px. | Pin a compact keyboard icon as a direct primary mobile action. |
| **P2** | Tabs plus toolbar occupy 175px out of a 568px mobile viewport. Redundant `Fly Terminal` heading/subtitle and duplicate Terminal title remain. | Hide verbose mobile brand/subtitle, consolidate redundant headings, expose actionable status only. |
| **P3** | `manifest.json` references missing `icon-192.png` and `icon-512.png`; `index.html` has no manifest link. | Complete PWA support or remove dead configuration. |

## Verified behavior and limits
- No root horizontal overflow at the four tested viewport sizes in default horizontal layout.
- Apps opens a viewport-contained bottom sheet; touch menu positioning and backdrop logic are present.
- Gateway catalogue was compacted in upstream 454768b: the dashboard removes the 150px minimum tile height and has dedicated mobile rules. The old gateway card size is not a current confirmed defect.
- `ResizeObserver` already automatically switches split mode back to tabs below 700px.
- Production Basic Auth, real ttyd/RDC/native browser streams and Safari on physical iPhone were **not** exercised; do not interpret static iframe 404 as a production bug.
- Still test iOS Safari `100vh`/safe-area and keyboard `visualViewport`, rotations, gesture mapping, focus through iframes, clipboard, file transfer, and session reconnection.

## Fix sequence
1. P0 overlay/overflow menu ownership.
2. Mobile orientation guard and touch hit areas.
3. Persistent keyboard action and touch-safe tab close.
4. Compact redundant header and toolbar text in the main terminal interface.
5. Browser E2E regression matrix (320/375/390px, landscape, nested menus, orientation, keyboard, touch targets) executed locally; no GitHub Actions.
