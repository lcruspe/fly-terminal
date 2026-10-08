const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'index.html'), 'utf8');
const implementation = source.slice(source.indexOf('    function positionAnchoredMenu('), source.indexOf('    function positionAppsRootMenu()'));
function place(side, anchor, size, submenu = false) {
  const menu = {
    style: {}, classList: { toggle() {} },
    getBoundingClientRect() {
      const width = Math.min(620, parseFloat(this.style.maxWidth));
      // Wrapping after width constraints makes the panel taller.
      return { width, height: Math.min(width < 520 ? 560 : 320, parseFloat(this.style.maxHeight)) };
    }
  };
  const context = { window: { innerWidth: size[0], innerHeight: size[1] }, document: {},
    shellEl: { classList: { contains: name => name === `orientation-${side}` } },
    fixedPositionBaseFor: () => ({left:0,top:0}), clampNumber: (v,min,max) => Math.min(Math.max(v,min),max) };
  vm.createContext(context); vm.runInContext(implementation, context);
  context.positionAnchoredMenu(menu, anchor, {submenu});
  return menu;
}
test('left and right sidebar panels fit after content wraps on a short viewport', () => {
  for(const side of ['vertical-left','vertical-right']) {
    const anchor=side==='vertical-left'?{left:20,right:220,top:350}:{left:380,right:580,top:350};
    const menu=place(side,anchor,[600,400]); const box=menu.getBoundingClientRect();
    assert.ok(parseFloat(menu.style.left)>=10);
    assert.ok(parseFloat(menu.style.top)>=10);
    assert.ok(parseFloat(menu.style.left)+box.width<=590);
    assert.ok(parseFloat(menu.style.top)+box.height<=390);
    assert.equal(box.height,380);
  }
});
test('submenus reverse direction when their right side has no room',()=>{
  const menu=place('vertical-left',{left:680,right:950,top:680},[1000,720],true);
  const box=menu.getBoundingClientRect();
  assert.ok(parseFloat(menu.style.left)+box.width<680);
  assert.ok(parseFloat(menu.style.top)+box.height<=710);
});
