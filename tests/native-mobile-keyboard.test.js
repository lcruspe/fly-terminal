import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html = fs.readFileSync(new URL('../vendor/novnc/webrtc.html', import.meta.url), 'utf8');
function setup() {
  const messages = [];
  const document = { activeElement: null, getElementById: id => elements[id] };
  function element() {
    return { value: '', listeners: {}, attrs: {}, setSelectionRange() {},
      addEventListener(name, fn) { this.listeners[name] = fn; },
      setAttribute(key, value) { this.attrs[key] = value; },
      focus() { document.activeElement = this; this.listeners.focus?.(); },
      blur() { document.activeElement = null; this.listeners.blur?.(); }
    };
  }
  const input = element(), btn = element(), remote = element();
  const elements = { mobileKeyboardInput: input, mobileKeyboardBtn: btn };
  const context = { document, window: {}, inputLayer: remote, registerInput: msg => messages.push(JSON.parse(JSON.stringify(msg))) };
  vm.createContext(context);
  const source = html.slice(html.indexOf('      const mobileKeyboardInput ='), html.indexOf('      let socket = null;'));
  vm.runInContext(source, context);
  return { input, btn, remote, document, messages, context };
}
test('HUD opens secure keyboard synchronously and keeps focus across remote frames', () => {
  assert.match(html, /id="mobileKeyboardInput" type="password"/);
  const { input, btn, document, context } = setup();
  btn.listeners.click();
  assert.equal(document.activeElement, input);
  assert.equal(btn.attrs['aria-pressed'], 'true');
  context.focusRemoteInput();
  assert.equal(document.activeElement, input);
  btn.listeners.click();
  assert.equal(input.value, '');
  assert.equal(btn.attrs['aria-pressed'], 'false');
});
test('mobile input sends text without clipboard, and forwards deletion and Enter', () => {
  const { input, btn, messages } = setup();
  btn.listeners.click();
  const event = (props) => ({ cancelable: true, preventDefault() { this.prevented = true; }, ...props });
  input.listeners.beforeinput(event({ inputType: 'insertText', data: 'aB9!' }));
  assert.equal(input.value, ' ');
  input.listeners.beforeinput(event({ inputType: 'deleteContentBackward' }));
  input.listeners.keydown(event({ key: 'Enter' }));
  assert.deepEqual(messages.map(x => [x.type, x.text ?? x.code]), [
    ['text','aB9!'], ['keydown','Backspace'], ['keyup','Backspace'], ['keydown','Enter'], ['keyup','Enter']
  ]);
});
test('noncancelable iOS input falls back to input event without retaining text', () => {
  const { input, btn, messages } = setup();
  btn.listeners.click();
  input.value = ' z';
  input.listeners.input({ inputType: 'insertText' });
  assert.deepEqual(messages, [{ type: 'text', text: 'z' }]);
  assert.equal(input.value, ' ');
  input.value = '';
  input.listeners.input({ inputType: 'deleteContentBackward' });
  assert.equal(messages[1].code, 'Backspace');
});
