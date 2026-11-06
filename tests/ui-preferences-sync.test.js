import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const start = html.indexOf('    function savePreferences() {');
const end = html.indexOf('    function setStatusText(message, duration = 0) {', start);
assert.ok(start > 0 && end > start, 'main UI preference controller must be present');
const controller = html.slice(start, end);

function createClient(server, local) {
  const requests = [];
  const listeners = {};
  const timers = new Map();
  let nextTimer = 0;
  let offline = false;
  let gate = null;
  const snapshot = obj => JSON.parse(JSON.stringify(obj));
  const context = {
    STORAGE_KEY: 'fly-terminal-preferences-v2',
    preferences: snapshot(local),
    lastObservedUiPreferences: snapshot(local),
    pendingUiPreferences: {},
    uiPreferencesInFlight: {},
    uiPreferencesSaving: false,
    uiPreferencesRetryDelay: 1500,
    persistPreferencesTimer: null,
    localStorage: { setItem: () => {} },
    applyAllThemes: () => {},
    applyWindowTitle: () => {},
    setTimeout: (fn, ms) => {
      const id = ++nextTimer;
      timers.set(id, { fn, ms });
      return id;
    },
    clearTimeout: id => timers.delete(id),
    window: { addEventListener: (name, cb) => { listeners[name] = cb; } },
    readPreferencesFromObject: data => snapshot(data),
    console: { warn: () => {} },
    localApiFetch: async (url, opts = {}) => {
      requests.push({ url, opts });
      if (offline) throw new Error('offline');
      if (opts.method === 'POST') {
        if (gate) await gate;
        Object.assign(server, JSON.parse(opts.body));
        return { ok: true, json: async () => ({ ok: true }) };
      }
      return { ok: true, json: async () => ({ ...server, ok: true }) };
    }
  };
  vm.createContext(context);
  vm.runInContext(controller +
    '\nthis.api = { savePreferences, persistUiPreferences, loadPersistedPreferences };', context);
  return {
    context, api: context.api, listeners, requests, timers,
    setOffline: value => { offline = value; },
    setGate: promise => { gate = promise; }
  };
}

test('stale main UI tab cannot overwrite new Native FPS when editing theme', async () => {
  const server = { theme: 'nord', desktopFps: 15, desktopResolution: '1600x900', panelCollapsed: true };
  const main = createClient(server, server);
  await main.api.loadPersistedPreferences();
  // Native HUD on another device saves this field after the parent tab loaded.
  server.desktopFps = 45;
  main.context.preferences.theme = 'paper';
  main.api.savePreferences();
  await main.api.persistUiPreferences();
  assert.equal(server.desktopFps, 45);
  assert.equal(server.theme, 'paper');
  const post = main.requests.find(item => item.opts.method === 'POST');
  assert.deepEqual(JSON.parse(post.opts.body), { theme: 'paper' });
});

test('pending main UI changes survive temporary API failure and retry', async () => {
  const server = { theme: 'nord', desktopFps: 15 };
  const main = createClient(server, server);
  await main.api.loadPersistedPreferences();
  main.setOffline(true);
  main.context.preferences.theme = 'graphite';
  main.api.savePreferences();
  await main.api.persistUiPreferences();
  assert.equal(server.theme, 'nord');
  assert.ok(main.timers.size > 0);
  main.context.preferences.desktopFps = 30;
  main.api.savePreferences();
  main.setOffline(false);
  await main.api.persistUiPreferences();
  assert.equal(server.theme, 'graphite');
  assert.equal(server.desktopFps, 30);
});

test('editing again during an in-flight main UI request preserves latest value', async () => {
  const server = { theme: 'nord', desktopFps: 15 };
  const main = createClient(server, server);
  await main.api.loadPersistedPreferences();
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  main.setGate(gate);
  main.context.preferences.desktopFps = 30;
  main.api.savePreferences();
  const first = main.api.persistUiPreferences();
  main.context.preferences.desktopFps = 45;
  main.api.savePreferences();
  release();
  await first;
  await main.api.persistUiPreferences();
  assert.equal(server.desktopFps, 45);
});

test('closing tab immediately after change sends a keepalive partial patch', async () => {
  const server = { theme: 'nord', desktopFps: 15 };
  const main = createClient(server, server);
  await main.api.loadPersistedPreferences();
  main.context.preferences.desktopFps = 30;
  main.api.savePreferences();
  main.listeners.pagehide();
  const request = main.requests.find(item => item.opts.keepalive === true);
  assert.ok(request);
  assert.deepEqual(JSON.parse(request.opts.body), { desktopFps: 30 });
  assert.equal(server.desktopFps, 30);
});

test('first-ever setup seeds durable server preferences from legacy browser values', async () => {
  const server = { theme: null };
  const main = createClient(server, { theme: 'nord', desktopFps: 45, desktopResolution: '2560x1440' });
  await main.api.loadPersistedPreferences();
  assert.equal(server.theme, 'nord');
  assert.equal(server.desktopFps, 45);
  assert.equal(server.desktopResolution, '2560x1440');
});
