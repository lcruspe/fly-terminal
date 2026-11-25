import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../vendor/novnc/webrtc.html', import.meta.url), 'utf8');

function client(search, stored = {}) {
  const values = new Map(Object.entries(stored));
  const context = {
    window: { location: { search } }, URLSearchParams,
    safeStorageGet: key => values.get(key) ?? null,
    safeStorageSet: (key, value) => values.set(key, value),
  };
  vm.createContext(context);
  const init = html.slice(html.indexOf('      const urlParams ='), html.indexOf('      const wsPath ='));
  vm.runInContext(init + '\nthis.state = { clientRole, requestedResolution, requestedFps, autoResizeEnabled };', context);
  return { ...context.state, values };
}

test('native browser and desktop restore their own stream settings, with valid URL overrides', () => {
  const stored = {
    'flyNativeStreamPreferences:browser': JSON.stringify({ resolution: '1280x720', fps: 30 }),
    'flyNativeStreamPreferences:desktop': JSON.stringify({ resolution: '1600x900', fps: 45, autoResize: true }),
  };
  const browser = client('?client=browser', stored);
  assert.equal(browser.requestedResolution, '1280x720');
  assert.equal(browser.requestedFps, 30);
  const desktop = client('?client=desktop&resolution=2560x1440&fps=15&autoResize=0', stored);
  assert.equal(desktop.requestedResolution, '2560x1440');
  assert.equal(desktop.requestedFps, 15);
  assert.equal(desktop.autoResizeEnabled, false);
  assert.equal(client('?client=desktop', stored).autoResizeEnabled, true);
});

test('explicit resolution changes configure capture at selected dimensions even with auto display', () => {
  const code = html.slice(html.indexOf('      function calculateCaptureSize()'), html.indexOf('      async function wakeDesktopDisplay()'));
  const calls = [];
  const context = {
    qualityProfile: () => ({ fps: 30 }), fitMode: 'sync', serverPixelWidth: 1920, serverPixelHeight: 1080,
    requestedWidth: 1920, requestedHeight: 1080, requestedResolution: '1920x1080',
    VALID_RESOLUTIONS: ['1280x720', '1920x1080'], streamResolutionSelect: {}, adaptiveScaleState: {},
    autoResizeEnabled: true, requestedDisplayName: '', currentBitrate: 4500000,
    resetClientIdleClock() {}, saveStreamPreferences() {}, applyFitMode() {},
    nativeScaleKey: "desktopScaleMode", nativeResolutionKey: "desktopResolution",
    queueNativePreferences: patch => calls.push({type: "preferences", ...patch}),
    sendTransportMessage: message => calls.push(message),
    window: { parent: null, location: { origin: 'https://example.test' } },
  };
  context.window.parent = context.window;
  vm.createContext(context);
  vm.runInContext(code, context);
  assert.equal(context.applyStreamResolution('1280x720'), true);
  const configure = calls.find(message => message.type === 'configure');
  assert.equal(configure.width, 1280);
  assert.equal(configure.height, 720);
  assert.equal(configure.force, true);
  assert.equal(context.fitMode, 'contain');
  assert.ok(calls.some(message => message.desktopScaleMode === 'contain'));
  assert.ok(calls.some(message => message.desktopResolution === '1280x720'));
});

test('server init does not replace the selected FPS with a previous encoder setting', () => {
  const handler = html.slice(html.indexOf('      async function handleServerText('), html.indexOf('      async function connectWebRtc('));
  assert.doesNotMatch(handler, /requestedFps\s*=\s*Number\(msg\.fpsCap\)/);
});

test('HUD exposes capture display selection and labels Sync resolution explicitly', () => {
  assert.match(html, /<select id="captureDisplay"/);
  assert.match(html, /<option value="sync" disabled>По экрану \(Sync\)/);
  assert.match(html, /streamResolutionSelect\.value = sync \? "sync" : requestedResolution/);
  assert.match(html, /captureDisplaySelect\.addEventListener\("change", \(\) => applyCaptureDisplay/);
  const code = html.slice(html.indexOf('      function applyCaptureDisplay('), html.indexOf('      captureDisplaySelect.addEventListener'));
  const calls = [];
  const ctx = {
    isBrowserClient: false, requestedDisplayName: 'Fly Remote', autoResizeEnabled: true,
    URL, window: { location: { href: 'https://example.test/desktop/webrtc.html?display=Fly%20Remote', origin: 'https://example.test' } },
    history: { replaceState: (_, __, url) => calls.push(url.search) },
    setAutoResizeEnabled: value => calls.push(value), resetClientIdleClock() {},
    sendTransportMessage: message => calls.push(message), configureStream: force => calls.push(force),
  };
  ctx.window.parent = ctx.window;
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  ctx.applyCaptureDisplay('');
  assert.equal(ctx.requestedDisplayName, '');
  assert.deepEqual(calls.slice(0, 2), [false, '']);
  ctx.applyCaptureDisplay('Fly Browser');
  assert.equal(ctx.requestedDisplayName, '');
});
