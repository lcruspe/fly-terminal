const test = require("node:test");
const assert = require("node:assert/strict");

const {
  isTouchDevice,
  focusTerminalKeyboard,
} = require("../mobile-keyboard.js");

test("touch detection accepts coarse pointers and touch-point devices", () => {
  assert.equal(isTouchDevice({ matchMedia: () => ({ matches: true }), navigator: { maxTouchPoints: 0 } }), true);
  assert.equal(isTouchDevice({ matchMedia: () => ({ matches: false }), navigator: { maxTouchPoints: 2 } }), true);
  assert.equal(isTouchDevice({ matchMedia: () => ({ matches: false }), navigator: { maxTouchPoints: 0 } }), false);
});

test("keyboard action focuses the active terminal helper textarea", () => {
  let focused = 0;
  const textarea = { focus: () => { focused += 1; } };
  const tab = {
    type: "terminal",
    wrapper: {
      querySelector: () => ({
        contentDocument: { querySelector: () => textarea },
      }),
    },
  };

  assert.equal(focusTerminalKeyboard(tab), true);
  assert.equal(focused, 1);
});

test("keyboard action focuses the noVNC touch input in browser tabs", () => {
  let focused = 0;
  const tab = {
    type: "browser",
    wrapper: {
      querySelector: () => ({
        contentWindow: {},
        contentDocument: { querySelector: (selector) => selector.includes("noVNC_keyboardinput") ? { focus: () => { focused += 1; } } : null },
      }),
    },
  };
  assert.equal(focusTerminalKeyboard(tab), true);
  assert.equal(focused, 1);
});

test("keyboard action uses a remote desktop keyboard bridge when available", () => {
  let opened = 0;
  const tab = {
    type: "desktop",
    wrapper: {
      querySelector: () => ({ contentWindow: { flyOpenKeyboard: () => { opened += 1; return true; } } }),
    },
  };
  assert.equal(focusTerminalKeyboard(tab), true);
  assert.equal(opened, 1);
});
