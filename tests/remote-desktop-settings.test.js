import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('Remote Desktop settings are grouped under a collapsed details block', () => {
  assert.match(html, /<details[^>]*class="[^"]*remote-desktop-settings[^"]*"[^>]*>/);
  assert.match(html, /<summary[^>]*>\s*Remote Desktop\s*<\/summary>/);
  assert.doesNotMatch(html, /<details[^>]*class="[^"]*remote-desktop-settings[^"]*"[^>]*\sopen(?:\s|>)/);
});

test('all remote desktop controls live inside the collapsed block', () => {
  const block = html.match(/<details[^>]*class="[^"]*remote-desktop-settings[^"]*"[^>]*>[\s\S]*?<\/details>/)?.[0] || '';
  for (const id of ['desktopMode','desktopResolution','desktopScaleMode','desktopFps','mainDisplayResolution','virtualDisplayResolution']) {
    assert.match(block, new RegExp(`id="${id}"`));
  }
});

test('nested Remote Desktop chevron reflects its own open state', () => {
  assert.match(html, /\.settings \.remote-desktop-settings > summary::after\s*\{[^}]*content:\s*"▾"/);
  assert.match(html, /\.settings \.remote-desktop-settings\[open\] > summary::after\s*\{[^}]*content:\s*"▴"/);
});

test('compact vertical toolbar hides only the top-level Settings chevron', () => {
  assert.match(html, /\.sidebar-compact \.settings > summary::after\s*\{\s*display:\s*none;/);
  assert.doesNotMatch(html, /\.sidebar-compact \.settings summary::after\s*\{\s*display:\s*none;/);
});
