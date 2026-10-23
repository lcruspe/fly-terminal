const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'index.html'), 'utf8');

function setup(fetch) {
  function select() {
    return { value: '', disabled: false, options: [], set innerHTML(value) { this.options = []; this.value = ''; }, appendChild(option) { this.options.push(option); } };
  }
  const subscription = select(), location = select(), button = {}, status = {}, notice = {}, reconnect = {}, pingButton = {}, pingStatus = {};
  let now = 0, timerId = 0;
  const timers = new Map();
  const context = vm.createContext({ happSubscriptionSelect: subscription, happLocationSelect: location,
    refreshHappSubscriptionsBtn: button, happLocationStatus: status, happCatalogNotice: notice, reconnectHappBtn: reconnect,
    pingHappBtn: pingButton, happPingStatus: pingStatus, localApiFetch: fetch,
    performance: { now: () => now },
    setTimeout: (callback, delay) => { const id = ++timerId; timers.set(id, { callback, due: now + delay }); return id; },
    clearTimeout: id => timers.delete(id),
    Option: function(text, value) { this.text = text; this.value = value; } });
  vm.runInContext(`let happSubscriptionsLoading = false; let happSubscriptions = [];
    let happCatalogState = {}; let happPingRunning = false; let happPingResults = new Map(); let happPingExpiryTimer = null;
    ${source.slice(source.indexOf('    function happPingKey('), source.indexOf('    async function refreshHappStatus('))}
    this.load = loadHappSubscriptions; this.switchLocation = switchHappLocation; this.ping = measureHappPing; this.changeSubscription = handleHappSubscriptionChange;`, context);
  return { context, subscription, location, button, status, notice, reconnect, pingButton, pingStatus,
    advance(ms) {
      now += ms;
      for (const [id, timer] of Array.from(timers)) {
        if (timer.due <= now) { timers.delete(id); timer.callback(); }
      }
    }, get now() { return now; }
  };
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

test('latest pings appear beside locations and expire individually without losing selection', async () => {
  const data = structuredClone(payload);
  data.canPing = true;
  data.currentSubscriptionId = 'b'; data.currentLocationId = 'b2';
  data.subscriptions[1].locations[0].ping = { status: 'ok', rttMs: 12.4, expiresInMs: 1000 };
  data.subscriptions[1].locations[1].ping = { status: 'timeout', rttMs: null, expiresInMs: 3000 };
  const ui = setup(async () => ({ ok: true, json: async () => data }));
  await ui.context.load();
  assert.match(ui.location.options[1].text, /12 мс/);
  assert.match(ui.location.options[2].text, /тайм-аут/);
  ui.advance(1000);
  assert.equal(ui.location.options[1].text, 'NL');
  assert.match(ui.location.options[2].text, /тайм-аут/);
  assert.equal(ui.location.value, 'b2');
  ui.advance(2000);
  assert.equal(ui.location.options[2].text, 'US');
  assert.equal(ui.location.value, 'b2');
});

test('refreshing catalogue does not extend a ping beyond its original three minute lifetime', async () => {
  let ui;
  ui = setup(async () => {
    const data = structuredClone(payload); data.canPing = true;
    data.subscriptions[0].locations[0].ping = { status: 'ok', rttMs: 1, expiresInMs: 180000 - ui.now };
    return { ok: true, json: async () => data };
  });
  await ui.context.load();
  ui.advance(120000);
  await ui.context.load(true);
  assert.match(ui.location.options[1].text, /1 мс/);
  ui.advance(59999);
  assert.match(ui.location.options[1].text, /1 мс/);
  ui.advance(1);
  assert.equal(ui.location.options[1].text, 'DE');
});

test('ping button posts selected subscription, prevents duplicate runs and accepts new results', async () => {
  let finish;
  const calls = [];
  const data = { ...payload, canPing: true };
  const ui = setup(async (url, options) => {
    calls.push({ url, options });
    if (options?.method === 'POST') return await new Promise(resolve => { finish = resolve; });
    return { ok: true, json: async () => data };
  });
  await ui.context.load();
  const run = ui.context.ping();
  assert.equal(ui.pingButton.disabled, true);
  assert.equal(ui.button.disabled, true);
  await ui.context.ping();
  assert.equal(calls.filter(call => call.options?.method === 'POST').length, 1);
  assert.deepEqual(JSON.parse(calls[1].options.body), { subscriptionId: 'a' });
  finish({ ok: true, json: async () => ({ ok: true, results: [
    { subscriptionId: 'a', locationId: 'a1', status: 'ok', rttMs: 33, expiresInMs: 180000 }
  ] }) });
  await run;
  assert.match(ui.location.options[1].text, /33 мс/);
  assert.equal(ui.pingButton.disabled, false);
  assert.equal(ui.button.disabled, false);
  ui.advance(180000);
  assert.equal(ui.location.options[1].text, 'DE');
  assert.equal(ui.pingStatus.textContent, '');
});

test('failed recheck keeps previous result until expiry and restores controls', async () => {
  const data = structuredClone(payload); data.canPing = true;
  data.subscriptions[0].locations[0].ping = { status: 'ok', rttMs: 14, expiresInMs: 2000 };
  const ui = setup(async (_url, options) => {
    if (options?.method === 'POST') throw new Error('offline');
    return { ok: true, json: async () => data };
  });
  await ui.context.load(); await ui.context.ping();
  assert.match(ui.location.options[1].text, /14 мс/);
  assert.match(ui.pingStatus.textContent, /offline/);
  assert.equal(ui.pingButton.disabled, false);
  ui.advance(2000);
  assert.equal(ui.location.options[1].text, 'DE');
});

test('a new result is not cleared by the previous result expiry timer', async () => {
  let count = 0;
  const data = { ...payload, canPing: true };
  const ui = setup(async (_url, options) => {
    if (options?.method === 'POST') {
      count++;
      return { ok: true, json: async () => ({ ok: true, results: [
        { subscriptionId: 'a', locationId: 'a1', status: 'ok', rttMs: count * 10, expiresInMs: 180000 }
      ] }) };
    }
    return { ok: true, json: async () => data };
  });
  await ui.context.load(); await ui.context.ping();
  ui.advance(150000); await ui.context.ping();
  ui.advance(30000);
  assert.match(ui.location.options[1].text, /20 мс/);
  ui.advance(150000);
  assert.equal(ui.location.options[1].text, 'DE');
});
