const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const dir = process.env.FLY_GATEWAY_DIR || path.join(__dirname, '..', 'macos', 'gateway');
const html = fs.readFileSync(path.join(dir, 'admin.html'), 'utf8');
const css = fs.readFileSync(path.join(dir, 'gateway.css'), 'utf8');
const js = fs.readFileSync(path.join(dir, 'gateway.js'), 'utf8');

test('gateway keeps all seven service targets and existing control hooks', () => {
  const order = [...html.matchAll(/<article class="service" data-service="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(order, ['terminal', 'browser', 'roomaudio', 'yt', 'networkmap', 'spruthub', 'openwrt']);
  assert.equal((html.match(/data-controls=/g) || []).length, 6);
  assert.equal((html.match(/class="action-menu-trigger"/g) || []).length, 7);
  assert.match(html, /data-port="10000"/);
  assert.match(html, /data-port="8443"/);
  assert.match(html, /data-health="roomaudio_source"/);
  assert.match(html, /data-health="fallback"/);
});

test('gateway exposes primary/infrastructure groups and a live overview', () => {
  assert.match(html, /<h1>Fly Gateway<\/h1>/);
  assert.match(html, /<h3>Рабочие сервисы<\/h3>/);
  assert.match(html, /<h3>Инфраструктура<\/h3>/);
  assert.match(html, /id="gateway-overview-text"/);
  assert.match(html, /data-overview-state="checking"/);
  assert.match(js, /function updateOverview\(/);
  assert.match(js, /overview\.dataset\.overviewState/);
});

test('gateway retains stateful tile/table switch and action safety', () => {
  assert.match(html, /data-view-mode="tiles"/);
  assert.match(html, /data-view-mode="table"/);
  assert.match(js, /fly-gateway-view-v1/);
  assert.match(js, /renderTable\(dashboard\.dataset\.view === "table"\)/);
  assert.match(js, /"\/gateway-control\/status"/);
  assert.match(js, /"\/gateway-control\/action"/);
  assert.match(js, /"X-Gateway-CSRF": csrf/);
  assert.match(js, /window\.confirm\(/);
  assert.match(js, /"\/network-map\/healthz"/);
});

test('mobile controls are reachable, and table mode stacks without horizontal scroll', () => {
  assert.match(css, /\.action-menu-trigger\s*\{[^}]*width: 44px;[^}]*height: 44px;/s);
  assert.match(css, /\.service-actions button, \.service-actions \.action-link\s*\{[^}]*min-height: 44px;/s);
  assert.match(css, /@media \(max-width: 650px\)/);
  assert.match(css, /\.service-table tbody tr\s*\{[^}]*display: grid;/s);
  assert.match(css, /\.service-table \{ display: block; min-width: 0;/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
});
