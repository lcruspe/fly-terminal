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
  assert.match(source, /\.terminal-frame-wrapper\.fullscreen \{[\s\S]*?border-radius: 14px;/);
});
test("small touch screens preserve desktop orientation preference", () => {
  assert.match(source, /const effectiveOrientation = mobile \? "horizontal" : orientation;/);
  assert.match(source, /toolbarOrientationSelect\.disabled = mobile;/);
  assert.match(source, /compactTouchLayout\.addEventListener\?\.\("change", \(\) =>[\s\S]*?applyToolbarOrientation\(preferences\.toolbarOrientation/);
  assert.match(source, /window\.visualViewport\?\.addEventListener\("resize", syncMobileVisualViewport/);
});
test("44px toolbar actions and keyboard pinned outside overflow", () => {
  assert.match(source, /\.shell #togglePanel, \.shell #openKeyboard \{[\s\S]*?min-width: 44px !important;/);
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
