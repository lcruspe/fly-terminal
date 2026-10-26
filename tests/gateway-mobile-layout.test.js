const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const dir = path.join(__dirname, "../macos/gateway");
const html = fs.readFileSync(path.join(dir, "admin.html"), "utf8");
const css = fs.readFileSync(path.join(dir, "gateway.css"), "utf8");
const js = fs.readFileSync(path.join(dir, "gateway.js"), "utf8");

test("catalog starts with the view switch and has no decorative heading", () => {
  assert.match(html, /<body class="dashboard-page">\s*<main[^>]+>\s*<div class="view-switch"/);
  assert.doesNotMatch(html, /<h1>Сервисы<\/h1>|Терминал, браузеры и управление подключениями/);
  assert.match(html, /<section class="services" aria-label="Каталог сервисов">/);
});

test("mobile cards have a top-aligned layout without an empty message gap", () => {
  assert.match(css, /\.catalog-message:empty\s*\{\s*display:none;/);
  assert.match(css, /@media\(max-width:600px\)[\s\S]*body\.dashboard-page\s*\{\s*display:block;/);
  assert.match(css, /\[data-dashboard\] \.services\s*\{\s*grid-template-columns:1fr;\s*gap:8px;\s*margin-top:8px;/);
  assert.match(css, /body:not\(\.dashboard-page\)\s*\{\s*padding:20px 12px;/);
});

function selectedMode({mobile, stored}) {
  // Exercise the production initialization up to action-menu setup.
  const init = js.slice(0, js.indexOf('  dashboard.querySelectorAll(".service-menu").forEach')) + "})();";
  const buttons = ["tiles", "table"].map(viewMode => ({
    dataset: {viewMode}, setAttribute(name, value) { this[name] = value; }, addEventListener() {}
  }));
  const dashboard = {
    dataset: {view: "tiles"},
    querySelector(sel) { return sel === ".catalog-message" ? {} : null; },
    querySelectorAll(sel) { return sel === "[data-view-mode]" ? buttons : []; }
  };
  const document = {
    querySelectorAll() { return []; },
    querySelector(sel) { return sel === "[data-dashboard]" ? dashboard : null; }
  };
  const window = {
    location: {hostname: "localhost", protocol: "http:", port: "8080"},
    matchMedia() { return {matches: mobile}; }
  };
  const localStorage = {
    getItem() { return stored === undefined ? null : JSON.stringify(stored); }
  };
  vm.runInNewContext(init, { document, window, localStorage });
  return {active: dashboard.dataset.view, pressed: buttons.filter(b => b["aria-pressed"] === "true").map(b => b.dataset.viewMode)};
}

test("tiles is the default; obsolete compact falls back and table is preserved", () => {
  assert.deepEqual(selectedMode({mobile: true}), {active: "tiles", pressed: ["tiles"]});
  assert.deepEqual(selectedMode({mobile: false}), {active: "tiles", pressed: ["tiles"]});
  assert.deepEqual(selectedMode({mobile: true, stored: "compact"}), {active: "tiles", pressed: ["tiles"]});
  assert.deepEqual(selectedMode({mobile: true, stored: "table"}), {active: "table", pressed: ["table"]});
  assert.deepEqual(selectedMode({mobile: true, stored: "list"}), {active: "table", pressed: ["table"]});
});
