import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const client = fs.readFileSync(new URL('../vendor/novnc/webrtc.html', import.meta.url), 'utf8');
const streamer = fs.readFileSync(new URL('../macos/fly-mac-streamer.py', import.meta.url), 'utf8');
const terminal = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('collapsed Remote Desktop HUD contains only FPS', () => {
  const chip = client.match(/<button[^>]*id="hudChip"[\s\S]*?<\/button>/)?.[0] || '';
  assert.match(chip, /id="hudChipFps"/);
  assert.doesNotMatch(chip, /hudChipStatus|hudChipRes|H\.264|1920×1080/);
});

test('expanded HUD exposes live FPS, resolution and idle timeout controls', () => {
  for (const id of ['fpsLimit', 'streamResolution', 'idleTimeout']) assert.match(client, new RegExp(`id="${id}"`));
  assert.match(client, /IDLE_TIMEOUT_OPTIONS = \[60, 180, 300, 600, 900, 1800, 3600\]/);
  assert.match(client, /function applyFpsLimit\(/);
  assert.match(client, /function applyStreamResolution\(/);
  assert.match(client, /function disconnectForIdle\(/);
});

test('server enables a deep idle profile after 30 seconds and ignores bridge keepalive as activity', () => {
  assert.match(streamer, /IDLE_PROFILE_AFTER_SECONDS = .*DEFAULT_IDLE_FPS_AFTER_SECONDS/);
  assert.match(streamer, /IDLE_PROFILE_WIDTH = 640/);
  assert.match(streamer, /IDLE_PROFILE_HEIGHT = 360/);
  assert.match(streamer, /IDLE_PROFILE_FPS = 5/);
  assert.match(streamer, /IDLE_PROFILE_BITRATE = 300_000/);
  assert.match(streamer, /requestedBitrate.*self\.requested_bitrate/);
  assert.match(client, /msg\.requestedBitrate \|\| msg\.bitrate/);
  assert.match(streamer, /idle_guard\.should_reduce_fps\(IDLE_PROFILE_AFTER_SECONDS\)/);
  assert.match(streamer, /await self\.set_idle_profile\(False\)/);
  const keepalive = streamer.match(/if msg_type == "bridge_keepalive"[\s\S]{0,120}?continue/)?.[0] || '';
  assert.ok(keepalive);
  assert.doesNotMatch(keepalive, /mark_activity/);
});

test('Terminal Settings pushes FPS and resolution live instead of reloading RDC tabs', () => {
  assert.match(terminal, /postToDesktopFrames\(\{ type: "fly-desktop-set-resolution"/);
  assert.match(terminal, /postToDesktopFrames\(\{ type: "fly-desktop-set-fps"/);
  assert.match(client, /fly-desktop-set-resolution/);
  assert.match(client, /fly-desktop-set-fps/);
});
