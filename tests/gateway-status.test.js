const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../macos/gateway/gateway.js"), "utf8");

function mount(fetch) {
  const cards = ["terminal", "native", "fallback", "roomaudio", "yt", "spruthub"].map(key => ({
    dataset: { health: key }, textContent: key,
    hasAttribute() { return false; },
    append(dot) { this.indicator = dot; dot.parentElement = this; },
    querySelector() { return null; },
  }));
  const router = { textContent: "" };
  const message = { textContent: "" };
  const themeToggle = { setAttribute() {}, addEventListener() {} };
  const dashboard = {
    dataset: { view: "tiles" },
    querySelector(selector) {
      if (selector === ".catalog-message") return message;
      if (selector === ".router-status") return router;
      if (selector === "#gatewayThemeToggle") return themeToggle;
      return null;
    },
    querySelectorAll(selector) {
      if (selector === "[data-health]") return cards;
      return [];
    },
  };
  let polls = 0;
  const document = {
    documentElement: { dataset: { gatewayTheme: "dark" } },
    querySelectorAll() { return []; },
    querySelector(selector) { return selector === "[data-dashboard]" ? dashboard : null; },
    createElement() {
      return { dataset: {}, setAttribute(name, value) { this[name] = value; } };
    },
    addEventListener() {},
  };
  const ctx = vm.createContext({
    document, fetch, AbortSignal,
    localStorage: { getItem() { return null; }, setItem() {} },
    window: {
      location: { hostname: "example.com", protocol: "https:", port: "" },
      addEventListener() {},
    },
    setInterval() { polls++; },
  });
  vm.runInContext(script, ctx);
  return { cards, router, message, get polls() { return polls; } };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

test("one gateway control request populates all service indicators", async () => {
  const urls = [];
  const ui = mount(async url => {
    urls.push(url);
    if (url === "/network-map/healthz")
      return { ok: true, json: async () => ({ ok: true }) };
    return { ok: true, json: async () => ({
      ok: true, csrf: "test-csrf", actions: {}, openwrt: { reachable: true, connected: false },
      services: { terminal: "up", native: "down", fallback: "up", roomaudio: "down", yt: "up", spruthub: "up" },
    }) };
  });
  await settle();
  assert.deepEqual(urls.sort(), ["/gateway-control/status", "/network-map/healthz"].sort());
  assert.deepEqual(ui.cards.map(card => card.indicator.dataset.state),
    ["up", "down", "up", "down", "up", "up"]);
  assert.match(ui.router.textContent, /VPN отключён/);
  assert.equal(ui.polls, 1);
});

test("request error leaves service status unknown, never offline", async () => {
  const ui = mount(async () => { throw Error("offline"); });
  await settle();
  assert.deepEqual(ui.cards.map(card => card.indicator.dataset.state),
    Array(6).fill("unknown"));
  assert.equal(ui.polls, 1);
});
