const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('macos/gateway/session-ui.js','utf8');
async function mount(admin, confirmed = true, ok = true) {
  const calls = [], redirects = [];
  function element() {
    return { children: [], attrs: {}, events: {}, style: {}, append(...nodes) { this.children.push(...nodes); },
      setAttribute(k,v) { this.attrs[k]=v; }, addEventListener(k,v) { this.events[k]=v; } };
  }
  const host = element();
  vm.runInNewContext(source, {
    document: { querySelector: () => host, createElement: element },
    window: { addEventListener() {} },
    fetch: async (path, options) => { calls.push([path,options]); return { ok: path === '/auth/session' || ok, json: async () => ({ok:true,is_admin:admin,expires_at:1800000000}) }; },
    location: { replace: path => redirects.push(path) }, confirm: () => confirmed
  });
  await new Promise(resolve => setImmediate(resolve));
  return {host, calls, redirects, panel:host.children[1]};
}
test('one session trigger and restricted role has logout only', async () => {
  const {host,panel,calls,redirects} = await mount(false);
  assert.equal(host.children.length,2);
  assert.equal(host.children[0].attrs.popovertarget,panel.id);
  assert.equal(panel.attrs.popover,'auto');
  assert.equal(panel.children.length,3);
  await panel.children[1].events.click();
  assert.equal(calls[1][0],'/auth/logout');
  assert.equal(calls[1][1].method,'POST');
  assert.deepEqual(redirects,['/auth/login']);
});
test('admin revoke requires confirmation', async () => {
  const {panel,calls} = await mount(true,false);
  await panel.children[2].events.click();
  assert.equal(calls.length,1);
});
test('confirmed admin revoke and retry after failed request', async () => {
  const {panel,calls,redirects} = await mount(true,true,false);
  await panel.children[2].events.click();
  assert.equal(calls[1][0],'/auth/revoke-all');
  assert.equal(panel.children[1].disabled,false);
  assert.equal(panel.children[2].disabled,false);
  assert.equal(redirects.length,0);
  assert.equal(panel.children[3].textContent,'Операция не выполнена');
});
