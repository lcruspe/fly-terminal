import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html = fs.readFileSync(new URL('../vendor/novnc/webrtc.html', import.meta.url), 'utf8');
const source = html.slice(html.indexOf('      // Touch gestures are isolated'), html.indexOf('      inputLayer.addEventListener("pointermove"'));
function setup() {
  const messages = [], btn = {}, canvas = {style:{}}, screenVideo = {style:{}};
  const ctx = vm.createContext({canvas, screenVideo, document:{getElementById:()=>btn}, window:{addEventListener(){}},
    viewport:{clientWidth:400,clientHeight:800,getBoundingClientRect:()=>({left:0,top:0,width:400,height:800})},
    inputLayer:{setPointerCapture(){},releasePointerCapture(){}},focusRemoteInput(){},
    getNormalizedCoords:e=>({x:e.clientX/400,y:e.clientY/800}),
    registerInput:msg=>messages.push(JSON.parse(JSON.stringify(msg))),sendTransportMessage:msg=>messages.push(msg)});
  vm.runInContext(source,ctx);
  const e=(pointerId,clientX,clientY)=>({pointerId,clientX,clientY,preventDefault(){}});
  return {ctx, messages,btn,canvas,e};
}
test('pinch zoom is local, does not click, and reset restores original scale',()=>{
  const {ctx,messages,btn,canvas,e}=setup();
  ctx.touchDown(e(1,100,300));ctx.touchDown(e(2,200,300));
  ctx.touchMove(e(1,50,300));ctx.touchMove(e(2,250,300));
  ctx.touchEnd(e(1,50,300));ctx.touchEnd(e(2,250,300));
  assert.match(canvas.style.transform,/scale\(2\)/);
  assert.equal(btn.textContent,'200%');
  assert.equal(messages.length,0);
  btn.onclick();assert.match(canvas.style.transform,/scale\(1\)/);
  assert.equal(btn.hidden,true);
});
test('two fingers scroll with no mouse button events',()=>{
  const {ctx,messages,e}=setup();
  ctx.touchDown(e(1,100,300));ctx.touchDown(e(2,200,300));
  ctx.touchMove(e(1,100,330));ctx.touchMove(e(2,200,330));
  ctx.touchEnd(e(1,100,330));ctx.touchEnd(e(2,200,330));
  assert.ok(messages.some(m=>m.type==='wheel'&&m.dy>0));
  assert.ok(messages.every(m=>['wheel','mousemove'].includes(m.type)));
});
test('tap clicks once and adding a second finger releases an active drag',()=>{
  const {ctx,messages,e}=setup();
  ctx.touchDown(e(1,100,300));ctx.touchEnd(e(1,100,300));
  assert.deepEqual(messages.map(m=>m.type),['mousedown','mouseup']);
  messages.length=0;
  ctx.touchDown(e(1,100,300));ctx.touchMove(e(1,120,300));ctx.touchDown(e(2,200,300));
  ctx.touchEnd(e(1,120,300));ctx.touchEnd(e(2,200,300));
  assert.deepEqual(messages.map(m=>m.type),['mousedown','mousemove','mouseup']);
});
test('one finger pans zoomed image without sending mouse events',()=>{
  const {ctx,messages,canvas,e}=setup();
  ctx.setTouchZoom(2,0,0);
  ctx.touchDown(e(1,100,300));ctx.touchMove(e(1,140,320));ctx.touchEnd(e(1,140,320));
  assert.match(canvas.style.transform,/translate\(40px, 20px\)/);
  assert.equal(messages.length,0);
});
