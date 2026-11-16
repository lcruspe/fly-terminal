const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");

test("iPhone viewport and rounded screen corners safe areas", () => {
  assert.match(source, /name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/);
  assert.match(source, /height: var\(--fly-mobile-visual-height, 100dvh\)/);
  for (const edge of ["top", "right", "bottom", "left"])
    assert.match(source, new RegExp("env\\(safe-area-inset-" + edge + "\\)"));
  assert.match(source, /\.terminal-frame-wrapper\.fullscreen \{[\s\S]*?border-radius: 0;/);
});
test("small touch screens preserve desktop orientation preference", () => {
  assert.match(source, /const effectiveOrientation = mobile \? "horizontal" : orientation;/);
  assert.match(source, /toolbarOrientationSelect\.disabled = mobile;/);
  assert.match(source, /compactTouchLayout\.addEventListener\?\.\("change", \(\) =>[\s\S]*?applyToolbarOrientation\(preferences\.toolbarOrientation/);
  assert.match(source, /window\.visualViewport\?\.addEventListener\("resize", syncMobileVisualViewport/);
});
test("44px toolbar actions and keyboard pinned outside overflow", () => {
  assert.match(source, /\.toolbar #togglePanel,\s*\.toolbar #openKeyboard,/);
  assert.match(source, /#toolbarControls > \.control-group > button,[\s\S]*?min-width: 44px !important;/);
  assert.match(source, /copySelectionBtn,\s*openKeyboardBtn,\s*settingsMenu/);
  assert.match(source, /if \(compactTouchLayout\.matches && element === openKeyboardBtn\) continue;/);
});
test("touch tab closing and new tab are keyboard accessible", () => {
  assert.match(source, /<button type="button" class="tab-close" title="Закрыть вкладку" aria-label="Закрыть вкладку">✕<\/button>/);
  assert.match(source, /newTabBtn\.setAttribute\("role", "button"\)/);
  assert.match(source, /newTabBtn\.setAttribute\("tabindex", "0"\)/);
  assert.match(source, /newTabBtn\.onkeydown = \(event\) =>/);
});
test("touch menu respects 59px notch and 21px Home indicator in landscape", () => {
  const start=source.indexOf("    function touchMenuBounds(");
  const end=source.indexOf("    function positionTouchMenuSurface(",start);
  assert.ok(start > 0 && end > start);
  const fn=vm.runInNewContext("(" + source.slice(start,end).trim() + ")");
  const out=fn(926,428,{left:59,right:59,top:0,bottom:21});
  assert.equal(out.left,67);assert.equal(out.top,8);assert.equal(out.bottom,29);
  assert.equal(out.width,792);assert.ok(out.height >= 330 && out.height <= 334);
  assert.match(source, /const bounds = touchMenuBounds\(viewportWidth, viewportHeight, readTouchSafeAreaInsets\(\)\);/);
});

test("compact touch shell removes card chrome and keeps a 44px header", () => {
  const start=source.indexOf("    /* Compact touch console. One continuous workspace");
  const end=source.indexOf("    @media (pointer: coarse) and (max-width: 360px)",start);
  assert.ok(start>0 && end>start);
  const css=source.slice(start,end);
  assert.match(css,/\.shell \{[\s\S]*?padding: env\(safe-area-inset-top\) env\(safe-area-inset-right\)/);
  assert.match(css,/\.shell \{[\s\S]*?gap: 0;/);
  assert.match(css,/\.terminal-frame-wrapper \{[^}]*border: 0;[^}]*border-radius: 0;[^}]*box-shadow: none;/s);
  assert.match(css,/\.terminal-topbar,[\s\S]*?height: 44px;[\s\S]*?min-height: 44px;/);
  assert.match(css,/\.bottom-panel \{[^}]*gap: 0;/s);
  assert.match(css,/\.tab-bar \{[^}]*height: 44px;[^}]*min-height: 44px;/s);
  assert.match(css,/\.toolbar \{[^}]*height: 48px;[^}]*min-height: 48px;/s);
});

test("flat controls retain 44px touch targets, focus and selected state", () => {
  const start=source.indexOf("    /* Compact touch console. One continuous workspace");
  const end=source.indexOf("    @media (pointer: coarse) and (max-width: 360px)",start);
  const css=source.slice(start,end);
  assert.match(css,/\.frame-control, a\.frame-control, \.frame-view-mode-btn \{[^}]*width: 44px;[^}]*min-width: 44px;[^}]*height: 44px;/s);
  assert.match(css,/\.tab \.tab-close \{[^}]*pointer-events: auto;[^}]*width: 44px;[^}]*height: 44px;/s);
  assert.match(css,/\.tab \.tab-close:focus-visible/);
  assert.match(css,/\.frame-view-mode-btn.active \{[^}]*background: var\(--accent\);/s);
  assert.match(css,/\.tab.active \{[^}]*border-bottom: 2px solid var\(--accent\);/s);
  assert.match(css,/\.toolbar #openKeyboard,[\s\S]*?min-width: 44px !important;/);
});

test("mobile flat selectors are scoped to coarse pointers only", () => {
  assert.match(source,/\/\* Compact touch console\.[\s\S]*?@media \(pointer: coarse\) and \(max-width: 760px\),/);
  assert.match(source,/\(pointer: coarse\) and \(max-height: 530px\)/);
  assert.match(source,/\.terminal-frame-wrapper\.fullscreen \{[\s\S]*?inset: env\(safe-area-inset-top\) env\(safe-area-inset-right\)/);
});
