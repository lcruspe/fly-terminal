const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");

test("global menu backdrop closes menus before iframe can consume pointerdown", () => {
  assert.match(source, /id="menuBackdrop"/);
  assert.match(source, /function closeAllMenus\(/);
  assert.match(source, /menuBackdrop\.addEventListener\("pointerdown", closeAllMenus\)/);
});

test("Escape routes floating and Apps menus through one close-all path", () => {
  assert.match(source, /function closeAllMenus\(/);
  assert.match(source, /if \(event\.key === "Escape"\) closeAllMenus/);
});

test("touch menus use a viewport bottom-sheet contract", () => {
  assert.match(source, /@media \(hover: none\), \(pointer: coarse\)/);
  assert.match(source, /body\.menu-surface-open/);
  assert.match(source, /100dvh/);
  assert.match(source, /min-height: 48px/);
});

test("touch Apps navigation exposes an in-sheet back action", () => {
  assert.match(source, /id="appsMenuBack"/);
  assert.match(source, /function showMobileAppsLevel\(/);
  assert.match(source, /data-mobile-apps-back/);
});