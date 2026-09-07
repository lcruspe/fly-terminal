import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const caddy = fs.readFileSync(new URL('../macos/Caddyfile', import.meta.url), 'utf8');
const installer = fs.readFileSync(new URL('../macos/install-direct-mac.sh', import.meta.url), 'utf8');
const webrtc = fs.readFileSync(new URL('../vendor/novnc/webrtc.html', import.meta.url), 'utf8');

test('native Chrome is the primary browser backend and Chromium remains fallback', () => {
  assert.match(html, /nativeUrl:/);
  assert.match(html, /fallbackUrl:/);
  assert.match(html, /function browserBackendState/);
  assert.match(html, /browser-backend-toggle/);
  assert.match(html, /Chromium · fallback/);
});

test('native browser uses a dedicated H.264 stream route', () => {
  assert.match(caddy, /@nativeBrowserStreamWs path \/native-browser-stream-ws/);
  assert.match(caddy, /FLY_NATIVE_BROWSER_STREAMER_PORT:5906/);
  assert.match(webrtc, /"Fly Remote", "Fly Browser"/);
});

test('macOS installer provisions native browser and streamer launch agents', () => {
  assert.match(installer, /ai\.kruspe\.fly-terminal\.native-browser"/);
  assert.match(installer, /ai\.kruspe\.fly-terminal\.native-browser-streamer"/);
  assert.match(installer, /launch-native-browser\.sh/);
  assert.match(installer, /launch-native-browser-streamer\.sh/);
});

test('native browser permission failure can switch to Chromium fallback', () => {
  assert.match(webrtc, /fly-native-browser-unavailable/);
  assert.match(html, /setBrowserTabBackend\(tab, "chromium", true\)/);
});
test('public routing keeps Browser on 8443 and removes obsolete 9443 funnel', () => {
  assert.match(installer, /tailscale funnel --https=9443 off/);
  assert.match(installer, /tailscale funnel --https=8443 --bg --yes/);
  assert.match(installer, /tailscale funnel --https=10000 --bg --yes/);
  assert.doesNotMatch(installer, /--https=9443 --bg/);
});
