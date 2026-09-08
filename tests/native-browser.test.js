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
  assert.match(html, /Browser Native/);
  assert.match(html, /Browser Fallback/);
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

test('desktop capture defaults to the macOS main display instead of an arbitrary virtual display', () => {
  const encoder = fs.readFileSync(new URL('../macos/fly-mac-encoder.swift', import.meta.url), 'utf8');
  assert.match(encoder, /displayName\.isEmpty[\s\S]*?CGMainDisplayID\(\)/);
  assert.match(encoder, /content\.displays\.first\(where: \{ \$0\.displayID == requestedDisplayID \}\)/);
});

test('H.264 codec metadata is derived from the encoder SPS', () => {
  const streamer = fs.readFileSync(new URL('../macos/fly-mac-streamer.py', import.meta.url), 'utf8');
  assert.match(streamer, /def detect_h264_codec/);
  assert.match(streamer, /return f"avc1\.\{nal\[1\]:02X\}\{nal\[2\]:02X\}\{nal\[3\]:02X\}"/);
  assert.match(streamer, /"type": "codec"/);
  assert.match(webrtc, /msg.type === "codec"/);
  assert.match(webrtc, /initVideoDecoder\(msg.codec/);
  assert.doesNotMatch(webrtc, /avc1\.42E01F/);
});

test('restricted clients fall back when WebCodecs H.264 cannot render frames', () => {
  assert.match(webrtc, /VideoDecoder\.isConfigSupported/);
  assert.match(webrtc, /fallbackFromH264\("webcodecs_unavailable"\)/);
  assert.match(webrtc, /fallbackFromH264\("no_decoded_frames"\)/);
  assert.match(webrtc, /NO_VNC_URL/);
});

test('native Browser follows the main display while macOS is locked', () => {
  const streamer = fs.readFileSync(new URL('../macos/fly-mac-streamer.py', import.meta.url), 'utf8');
  const launcher = fs.readFileSync(new URL('../macos/launch-native-browser-streamer.sh', import.meta.url), 'utf8');
  assert.match(streamer, /CGSSessionScreenIsLocked/);
  assert.match(streamer, /follow_main_when_locked/);
  assert.match(streamer, /return ""[\s\S]*requested_display_name/);
  assert.match(streamer, /async def monitor_lock_state/);
  assert.match(launcher, /FLY_STREAMER_FOLLOW_MAIN_WHEN_LOCKED/);
});

test('encoder restarts reuse one Unix socket server', () => {
  const streamer = fs.readFileSync(new URL('../macos/fly-mac-streamer.py', import.meta.url), 'utf8');
  assert.match(streamer, /self\.unix_server = None/);
  assert.match(streamer, /if self\.unix_server is None:/);
  assert.match(streamer, /self\.unix_server = await asyncio\.start_unix_server/);
});


test('remote access tabs use short neutral titles', () => {
  const vnc = fs.readFileSync(new URL('../vendor/novnc/vnc.html', import.meta.url), 'utf8');
  const gateway = fs.readFileSync(new URL('../macos/gateway/admin.html', import.meta.url), 'utf8');
  const sprut = fs.readFileSync(new URL('../macos/gateway/spruthub.html', import.meta.url), 'utf8');
  assert.match(webrtc, /<title>RDC Native<\/title>/);
  assert.match(webrtc, /setNeutralPageTitle\("WS"\)/);
  assert.match(webrtc, /"Browser" : "RDC"/);
  assert.match(vnc, /<title>RDC VNC<\/title>/);
  assert.match(html, /RDC Native/);
  assert.match(html, /RDC VNC/);
  assert.match(html, /Browser Native/);
  assert.match(html, /Browser Fallback/);
  assert.match(gateway, /<title>Gateway<\/title>/);
  assert.match(sprut, /<title>Sprut<\/title>/);
});

test('remote desktop HUD stays compact until explicitly opened', () => {
  assert.match(webrtc, /id="hudChip"/);
  assert.match(webrtc, /HUD_AUTOHIDE_MS = 3000/);
  assert.match(webrtc, /flyRemoteHudPinned/);
  assert.match(webrtc, /flyRemoteHudPosition/);
  assert.match(webrtc, /id="hudDragHandle"/);
  assert.match(webrtc, /function scheduleHudCollapse/);
  assert.match(webrtc, /function setHudPinned/);
  assert.doesNotMatch(webrtc, /#viewport:hover #hudBar/);
});


test('screen capture runs only while a remote desktop client is connected', () => {
  const streamer = fs.readFileSync(new URL('../macos/fly-mac-streamer.py', import.meta.url), 'utf8');
  assert.match(streamer, /if not self\.clients:[\s\S]*Encoder start skipped/);
  assert.match(streamer, /async def ensure_encoder_started/);
  assert.match(streamer, /async def stop_encoder_if_idle/);
  assert.match(streamer, /Stopping screen capture: no active stream clients/);
  assert.match(streamer, /self\.clients\[websocket\] = state[\s\S]*await self\.ensure_encoder_started\(\)/);
  assert.match(streamer, /self\.clients\.pop\(websocket, None\)[\s\S]*await self\.stop_encoder_if_idle\(\)/);
  assert.doesNotMatch(streamer, /server\.running = True\s+await server\.start_encoder\(\)/);
});
