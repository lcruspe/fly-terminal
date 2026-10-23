const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'index.html'), 'utf8');

function setup(fetch) {
  function select() {
    return { value: '', disabled: false, options: [], set innerHTML(value) { this.options = []; this.value = ''; }, appendChild(option) { this.options.push(option); } };
  }
  const subscription = select(), location = select(), button = {}, status = {}, notice = {}, reconnect = {};
  const context = vm.createContext({ happSubscriptionSelect: subscription, happLocationSelect: location,
    refreshHappSubscriptionsBtn: button, happLocationStatus: status, happCatalogNotice: notice, reconnectHappBtn: reconnect, localApiFetch: fetch,
    Option: function(text, value) { this.text = text; this.value = value; } });
  vm.runInContext(`let happSubscriptionsLoading = false; let happSubscriptions = [];
    let happCatalogState = {};
    ${source.slice(source.indexOf('    function renderHappLocationOptions('), source.indexOf('    async function refreshHappStatus('))}
    this.load = loadHappSubscriptions; this.switchLocation = switchHappLocation;`, context);
  return { context, subscription, location, button, status, notice, reconnect };
}
const payload = { ok: true, currentSubscriptionId: 'a', currentLocationId: 'a1',
  subscriptions: [ { id: 'a', label: 'A', locations: [{ id: 'a1', label: 'DE' }] },
    { id: 'b', label: 'B', locations: [{ id: 'b1', label: 'NL' }, { id: 'b2', label: 'US' }] } ] };
const response = { ok: true, json: async () => payload };

test('manual refresh fetches fresh data and retains selected subscription and location', async () => {
  const calls = [];
  const ui = setup(async (url) => { calls.push(url); return response; });
  await ui.context.load();
  ui.subscription.value = 'b'; ui.location.value = 'b2';
  await ui.context.load(true);
  assert.equal(calls[1], '/api/vpn/happ/subscriptions?refresh=1');
  assert.equal(ui.subscription.options.length, 3);
  assert.equal(ui.subscription.value, 'b');
  assert.equal(ui.location.options.length, 3);
  assert.equal(ui.location.value, 'b2');
  assert.equal(ui.button.disabled, false);
});

test('failed refresh retains existing catalogue and restores refresh button', async () => {
  let fail = false;
  const ui = setup(async () => { if (fail) throw new Error('offline'); return response; });
  await ui.context.load(); fail = true;
  await ui.context.load(true);
  assert.equal(ui.subscription.options.length, 3);
  assert.equal(ui.location.value, 'a1');
  assert.equal(ui.subscription.disabled, false);
  assert.equal(ui.button.disabled, false);
  assert.match(ui.status.textContent, /offline/);
});

test('concurrent refresh clicks issue only one request', async () => {
  let resolve, calls = 0;
  const ui = setup(() => { calls++; return new Promise(done => { resolve = done; }); });
  const first = ui.context.load(true);
  assert.equal(ui.button.disabled, true);
  await ui.context.load(true);
  assert.equal(calls, 1);
  resolve(response); await first;
  assert.equal(ui.button.disabled, false);
});


test('Desktop catalogue remains browsable while legacy VPN actions are disabled', async () => {
  let calls = 0;
  const desktopPayload = { ...payload, canSwitch: false, canReconnect: false,
    notice: 'Для подключения выберите сервер в Happ Desktop.' };
  const ui = setup(async () => { calls++; return { ok: true, json: async () => desktopPayload }; });
  await ui.context.load(true);
  assert.equal(ui.location.disabled, false);
  assert.equal(ui.reconnect.disabled, true);
  assert.match(ui.notice.textContent, /Happ Desktop/);
  ui.location.value = 'a1';
  await ui.context.switchLocation();
  assert.equal(calls, 1);
});
