import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../vendor/novnc/webrtc.html', import.meta.url), 'utf8');
const start = html.indexOf('      // Native WebRTC shares the durable UI preference store');
const end = html.indexOf('      function clampHudPosition()', start);
assert.ok(start > 0 && end > start, 'Native settings controller must be present');
const controller = html.slice(start, end);

function createClient(saved, { browser = false, local = {}, failGet = false } = {}) {
  const requests = [];
  const cache = { ...local };
  const context = {
    isBrowserClient: browser,
    window: { location: { username: '', password: '' } },
    URLSearchParams, AbortController,
    fetch: async (url, options) => {
      requests.push({ url, options });
      if (options.method === 'POST') {
        return { ok: true, json: async () => ({ ok: true }) };
      }
      if (failGet) throw new Error('offline');
      return { ok: true, json: async () => ({ ok: true, ...saved }) };
    },
    setTimeout: () => 1,
    clearTimeout: () => {},
    console: { warn: () => {} },
    VALID_RESOLUTIONS: ['1280x720', '1600x900', '1920x1080', '2560x1440'],
    VALID_FPS_LIMITS: [15, 30, 45, 60],
    IDLE_TIMEOUT_OPTIONS: [60, 180, 300, 600, 900, 1800, 3600],
    HUD_POSITION_KEY: 'flyRemoteHudPosition',
    HUD_PIN_KEY: 'flyRemoteHudPinned',
    IDLE_TIMEOUT_KEY: 'flyRemoteIdleTimeoutSeconds',
    safeStorageGet: key => cache[key] ?? null,
    safeStorageSet: (key, value) => { cache[key] = value; },
    currentQualityMode: 'auto',
    qualityModeSelect: { value: '' },
    diagnostics: { qualityMode: '' },
    sessionIdleTimeoutSeconds: 300,
    idleTimeoutSelect: { value: '' },
    hudPinned: false,
    setHudPinned: value => { context.hudPinned = value; },
    hudDock: { style: { left: '12px', top: '12px' } },
    requestAnimationFrame: () => {},
    clampHudPosition: () => {},
    requestedResolution: '1920x1080',
    requestedWidth: 1920,
    requestedHeight: 1080,
    streamResolutionSelect: { value: '' },
    requestedFps: 60,
    fpsLimitSelect: { value: '' },
    fitMode: 'contain',
    autoResizeEnabled: false,
    autoResizeBtn: { setAttribute: () => {} },
    displayAutoResize: { setEnabled: () => {} },
    applyFitMode: () => {},
    savedStreamPreferences: {},
    saveStreamPreferences: () => {},
  };
  context.savedStreamPreferences = JSON.parse(cache["flyNativeStreamPreferences:" + (browser ? "browser" : "desktop")] || "{}");
  vm.createContext(context);
  vm.runInContext(controller + '\nthis.nativeApi = { loadNativePreferences, queueNativePreferences, flushNativePreferences };', context);
  return { context, cache, requests, api: context.nativeApi };
}

test('stored server configuration overrides defaults without being overwritten', async () => {
  const client = createClient({
    desktopResolution: '2560x1440', desktopFps: 45,
    desktopScaleMode: 'fill', desktopAutoResize: true,
    nativeDesktopQualityMode: 'smooth',
    nativeDesktopIdleTimeoutSeconds: 900,
    nativeDesktopHudPinned: true,
    nativeDesktopHudPosition: { x: 230, y: 88 },
  });
  await client.api.loadNativePreferences();
  assert.equal(client.context.requestedResolution, '2560x1440');
  assert.equal(client.context.requestedFps, 45);
  assert.equal(client.context.fitMode, 'fill');
  assert.equal(client.context.autoResizeEnabled, true);
  assert.equal(client.context.qualityModeSelect.value, 'smooth');
  assert.equal(client.context.sessionIdleTimeoutSeconds, 900);
  assert.equal(client.context.hudPinned, true);
  assert.equal(client.context.hudDock.style.left, '230px');
  await client.api.flushNativePreferences();
  assert.equal(client.requests.filter(x => x.options.method === 'POST').length, 0);
});

test('existing local values migrate only where server is missing preferences', async () => {
  const client = createClient({
    desktopResolution: '1600x900', desktopFps: 30, desktopScaleMode: 'sync',
    desktopAutoResize: false,
  }, { local: { flyRemoteHudPosition: '{"x":76,"y":32}' } });
  await client.api.loadNativePreferences();
  await client.api.flushNativePreferences();
  const posts = client.requests.filter(x => x.options.method === 'POST');
  assert.equal(posts.length, 1);
  const patch = JSON.parse(posts[0].options.body);
  assert.equal(patch.nativeDesktopQualityMode, 'auto');
  assert.equal(patch.nativeDesktopHudPosition.x, 76);
  assert.equal(patch.nativeDesktopIdleTimeoutSeconds, 300);
  assert.equal(Object.hasOwn(patch, 'desktopResolution'), false);
  assert.equal(client.context.requestedResolution, '1600x900');
});

test('browser and desktop native sessions read distinct profiles', async () => {
  const client = createClient({
    nativeBrowserResolution: '1280x720',
    nativeBrowserFps: 15,
    nativeBrowserScaleMode: 'sync',
    nativeBrowserQualityMode: 'text',
    nativeBrowserIdleTimeoutSeconds: 180,
    nativeBrowserHudPinned: false,
    nativeBrowserHudPosition: { x: 30, y: 60 },
    desktopResolution: '2560x1440', desktopFps: 60,
  }, { browser: true });
  await client.api.loadNativePreferences();
  assert.equal(client.context.requestedResolution, '1280x720');
  assert.equal(client.context.requestedFps, 15);
  assert.equal(client.context.fitMode, 'sync');
  assert.equal(client.context.qualityModeSelect.value, 'text');
  await client.api.flushNativePreferences();
  assert.equal(client.requests.filter(x => x.options.method === 'POST').length, 0);
});

test('server outage does not upload stale local defaults', async () => {
  const client = createClient({}, { failGet: true });
  await client.api.loadNativePreferences();
  await client.api.flushNativePreferences();
  assert.equal(client.requests.filter(x => x.options.method === 'POST').length, 0);
  client.api.queueNativePreferences({ desktopFps: 30 });
  await client.api.flushNativePreferences();
  const writes = client.requests.filter(x => x.options.method === 'POST');
  assert.equal(JSON.parse(writes[0].options.body).desktopFps, 30);
});


test('legacy stream cache wins over default URL during first server migration', async () => {
  const client = createClient({}, { browser: true, local: {
    'flyNativeStreamPreferences:browser': JSON.stringify({ resolution: '1600x900', fps: 30, scale: 'fill' })
  } });
  await client.api.loadNativePreferences();
  await client.api.flushNativePreferences();
  assert.equal(client.context.requestedResolution, '1600x900');
  assert.equal(client.context.requestedFps, 30);
  assert.equal(client.context.fitMode, 'fill');
  const post = client.requests.find(x => x.options.method === 'POST');
  const patch = JSON.parse(post.options.body);
  assert.equal(patch.nativeBrowserResolution, '1600x900');
  assert.equal(patch.nativeBrowserFps, 30);
  assert.equal(patch.nativeBrowserScaleMode, 'fill');
});
