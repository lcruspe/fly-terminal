const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const dir = path.join(__dirname, "../macos/gateway");
const html = fs.readFileSync(path.join(dir, "admin.html"), "utf8");
const css = fs.readFileSync(path.join(dir, "gateway.css"), "utf8");
const js = fs.readFileSync(path.join(dir, "gateway.js"), "utf8");

test("catalog includes header, view switch and theme control", () => {
  assert.match(html, /<header class="gateway-header">/);
  assert.match(html, /<div class="view-switch"/);
  assert.match(html, /<button type="button" class="theme-toggle" id="gatewayThemeToggle"/);
  assert.match(html, /<section class="services" aria-label="Каталог сервисов">/);
});

test("mobile cards remain compact while table has independent three-column layout", () => {
  assert.match(css, /\.catalog-message:empty\s*\{\s*display:\s*none;/);
  assert.match(css, /@media \(max-width: 650px\)/);
  assert.match(css, /body\.dashboard-page \.services \{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/s);
  assert.match(css, /body\.dashboard-page \.catalog-group-heading \{ display: none; \}/);
  assert.match(css, /body\.dashboard-page \.service-table tbody tr \{[^}]*grid-template-columns: minmax\(0, 1\.1fr\) minmax\(0, 1fr\) 44px;/s);
  assert.match(css, /body\.dashboard-page \.service-table tbody tr \{[^}]*align-items: center;/s);
  assert.match(css, /body\.dashboard-page \.action-menu-trigger \{[^}]*width: 44px;[^}]*height: 44px;/s);
});

function selectedMode({mobile, stored}) {
  // Exercise the production initialization up to action-menu setup.
  const init = js.slice(0, js.indexOf('  dashboard.querySelectorAll(".service-menu").forEach')) + "})();";
  const buttons = ["tiles", "table"].map(viewMode => ({
    dataset: {viewMode}, setAttribute(name, value) { this[name] = value; }, addEventListener() {}
  }));
  const themeToggle = {setAttribute() {}, addEventListener() {}};
  const dashboard = {
    dataset: {view: "tiles"},
    querySelector(sel) {
      if (sel === "#gatewayThemeToggle") return themeToggle;
      return sel === ".catalog-message" ? {} : null;
    },
    querySelectorAll(sel) { return sel === "[data-view-mode]" ? buttons : []; }
  };
  const document = {
    documentElement: {dataset: {gatewayTheme: "dark"}},
    querySelectorAll() { return []; },
    querySelector(sel) {
      if (sel === "[data-dashboard]") return dashboard;
      if (sel === 'meta[name="theme-color"]') return {content: "#0d1118"};
      return null;
    }
  };
  const window = {
    location: {hostname: "localhost", protocol: "http:", port: "8080"},
    matchMedia() { return {matches: mobile}; }
  };
  const localStorage = {
    getItem(key) { return key === "fly-gateway-view-v1" && stored !== undefined ? JSON.stringify(stored) : null; },
    setItem() {}
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
