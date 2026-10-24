const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

test('VPN provider switch preserves Happ and adds Amnezia selector', () => {
  for (const id of ['vpnProvider', 'happVpnControls', 'amneziaVpnControls',
                    'amneziaProfile', 'connectAmneziaProfile', 'refreshAmneziaProfiles']) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /selectVpnProvider\(vpnProviderSelect\.value\)/);
  assert.match(html, /happLocationSelect\.onchange = switchHappLocation/);
});

test('Amnezia selection is explicit and asynchronous response is reconciled without retrying POST', () => {
  assert.match(html, /amneziaProfileSelect\.onchange = updateAmneziaAction/);
  assert.match(html, /connectAmneziaProfileBtn\.onclick = connectAmneziaProfile/);
  assert.match(html, /\/api\/vpn\/amnezia\/select/);
  assert.match(html, /\/api\/vpn\/amnezia\/status/);
  assert.match(html, /verifyAmneziaAfterNetworkChange/);
  assert.match(html, /confirm\(`Смена профиля/);
});
