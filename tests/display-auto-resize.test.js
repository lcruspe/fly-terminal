import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const helper = fs.readFileSync(new URL('../vendor/novnc/display-auto-resize.js', import.meta.url), 'utf8');
const desktop = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const native = fs.readFileSync(new URL('../vendor/novnc/webrtc.html', import.meta.url), 'utf8');
const vnc = fs.readFileSync(new URL('../vendor/novnc/app/ui.js', import.meta.url), 'utf8');
const vncPage = fs.readFileSync(new URL('../vendor/novnc/vnc.html', import.meta.url), 'utf8');

test('all RDC modes receive the auto display setting', () => {
  assert.match(desktop, /id="desktopAutoResize"/);
  assert.match(desktop, /autoResize=\$\{preferences\.desktopAutoResize/);
  assert.match(native, /displayAutoResize\.schedule\(\)/);
  assert.match(native, /vncFallbackUrl\(\)/);
  assert.match(vnc, /UI\.displayAutoResize\.schedule\(\)/);
  assert.match(vncPage, /display-auto-resize\.js/);
  assert.match(vncPage, /id="noVNC_setting_fly_auto_resize"/);
});

test('auto resize sends latest window geometry and skips repeated dimensions', async () => {
  let size = { width: 1200, height: 800 };
  const timers = [];
  const requests = [];
  const context = {
    window: { addEventListener() {} },
    document: { visibilityState: 'visible', addEventListener() {} },
    ResizeObserver: class { observe() {} },
    setTimeout(callback) { timers.push(callback); return timers.length; },
    clearTimeout() {},
    fetch: async (_url, options) => {
      requests.push(JSON.parse(options.body));
      return { ok: true, json: async () => ({ ok: true, resolution: '1200x800' }) };
    }
  };
  vm.runInNewContext(helper, context);
  const resize = context.window.FlyDisplayAutoResize({
    element: { getBoundingClientRect: () => size },
    target: 'virtual', enabled: true, isConnected: () => true,
    onApplied() {}, onError: error => { throw error; }
  });
  resize.schedule();
  await timers.pop()();
  resize.schedule();
  await timers.pop()();
  size = { width: 1301, height: 901 };
  resize.schedule();
  await timers.pop()();
  size = { width: 390, height: 701 };
  resize.schedule();
  await timers.pop()();
  assert.deepEqual(requests.map(request => request.resolution), ['1200x800', '1301x901', '390x701']);
  assert.ok(requests.every(request => request.target === 'virtual' && request.automatic === true));
});

test('Native auto resize captures Fly Remote and manual mode keeps the selected display', () => {
  const source = native.match(/function configureStream\(force = false\) \{([\s\S]*?)\n      \}/)[0];
  const messages = [];
  const context = {
    autoResizeEnabled: true, requestedDisplayName: '', currentBitrate: 4500000,
    calculateCaptureSize: () => ({width: 1378, height: 846, fps: 30}),
    sendTransportMessage: message => messages.push(message)
  };
  vm.runInNewContext(source, context);
  context.configureStream(true);
  context.autoResizeEnabled = false;
  context.configureStream(true);
  assert.equal(messages[0].displayName, 'Fly Remote');
  assert.equal(messages[1].displayName, '');
});
