const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync(require('node:path').join(__dirname, '../macos/gateway/gateway.js'), 'utf8');
function links(hostname, port, protocol = 'https:') {
  const links = [{dataset:{port:'8443'}}, {dataset:{port:'8443',path:'/desktop/webrtc.html?client=browser'}}, {dataset:{port:'10000'}}];
  const router = {href:'http://192.168.1.115/'};
  const location = {hostname, port, protocol, origin:`${protocol}//${hostname}${port ? ':'+port : ''}`};
  vm.runInNewContext(script, {URL, window:{location}, document:{querySelector:()=>null, querySelectorAll:s=>s==='[data-port]'?links:s.startsWith('a[href')?[router]:[]}});
  return [...links.map(x=>x.href),router.href];
}
test('Commander fallback keeps terminal/browser on catalog origin and Sprut on its port',()=>{
  assert.deepEqual(links('commander-hub.tail1c55c5.ts.net','8443'),[
    'https://commander-hub.tail1c55c5.ts.net:8443/fly/',
    'https://commander-hub.tail1c55c5.ts.net:8443/desktop/webrtc.html?client=browser',
    'https://commander-hub.tail1c55c5.ts.net:10000/',
    'https://commander-hub.tail1c55c5.ts.net:8443/cgi-bin/luci/'
  ]);
});
test('Oracle and local port mappings stay intact',()=>{
  assert.equal(links('129-158-49-130.sslip.io','')[0], 'https://129-158-49-130.sslip.io:8443/');
  assert.equal(links('localhost','8080','http:')[0], 'http://localhost:8081/');
});

test('Browser actions include the existing main desktop VNC route',()=>{
  const html=fs.readFileSync(require('node:path').join(__dirname,'../macos/gateway/admin.html'),'utf8');
  const menu=html.slice(html.indexOf('id="actions-browser"'),html.indexOf('</article>',html.indexOf('id="actions-browser"')));
  const match=menu.match(/data-path="([^"]+)" href="#">Открыть RDC VNC<\/a>/);
  assert.ok(match);
  const url=new URL(match[1].replaceAll('&amp;','&'),'https://example.test:8443');
  assert.equal(url.pathname,'/desktop/vnc.html');
  assert.equal(url.searchParams.get('path'),'desktop-ws');
  assert.equal(url.searchParams.get('autoconnect'),'true');
});

test('Gateway Native Browser links restore the saved display',()=>{
  const html=fs.readFileSync(require('node:path').join(__dirname,'../macos/gateway/admin.html'),'utf8');
  const links=[...html.matchAll(/data-path="([^"]*native-browser-stream-ws[^"]*)"/g)];
  assert.equal(links.length,3);
  for(const link of links) assert.equal(new URL(link[1].replaceAll('&amp;','&'),'https://example.test').searchParams.has('display'),false);
});
