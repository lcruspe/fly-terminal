const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const script = fs.readFileSync(path.join(__dirname, "../macos/gateway/gateway.js"), "utf8");

function mount(fetch) {
  const cards = ["terminal", "native", "fallback", "roomaudio", "yt", "spruthub"].map(key => ({
    dataset: { health: key },
    append(node) { this.indicator = node; },
    querySelector() { return { textContent: key }; }
  }));
  const timers = new Map();
  let id = 0;
  const document = {
    querySelectorAll(selector) { return selector === ".service" ? cards : []; },
    createElement() { return { dataset: {}, setAttribute(name, value) { this[name] = value; } }; }
  };
  const ctx = vm.createContext({
    document, window: { location: { hostname: "example.com" } }, fetch,
    AbortController, setTimeout(fn) { timers.set(++id, fn); return id; },
    clearTimeout(key) { timers.delete(key); }
  });
  vm.runInContext(script, ctx);
  return { cards, timers };
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test("one request updates all six indicator states", async () => {
  const urls = [];
  const { cards, timers } = mount(async url => {
    urls.push(url);
    return { ok: true, json: async () => ({ ok: true, services: {
      terminal: "up", native: "down", fallback: "up", roomaudio: "down", yt: "up", spruthub: "up"
    } }) };
  });
  await settle();
  assert.deepEqual(urls, ["/gateway-status"]);
  assert.deepEqual(cards.map(card => card.indicator.dataset.state),
    ["up", "down", "up", "down", "up", "up"]);
  assert.equal(timers.size, 0);
});

test("request error is unknown, not offline", async () => {
  const { cards } = mount(async () => { throw Error("offline"); });
  await settle();
  assert.deepEqual(cards.map(card => card.indicator.dataset.state), Array(6).fill("unknown"));
});
