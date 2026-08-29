(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.FlyTerminalMobileKeyboard = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  function isTouchDevice(host = root) {
    const coarsePointer = Boolean(host?.matchMedia?.("(pointer: coarse)")?.matches);
    const touchPoints = Number(host?.navigator?.maxTouchPoints) || 0;
    return coarsePointer || touchPoints > 0;
  }

  function focusTerminalKeyboard(tab) {
    if (!tab) return false;
    try {
      const iframe = tab.wrapper?.querySelector("iframe");
      if (typeof iframe?.contentWindow?.flyOpenKeyboard === "function") {
        return iframe.contentWindow.flyOpenKeyboard() !== false;
      }
      const selkiesButton = iframe?.contentDocument?.querySelector(
        'button[title="Pop Keyboard"], button[aria-label="Pop Keyboard"]'
      );
      if (selkiesButton) {
        selkiesButton.click();
        return true;
      }
      const textarea = iframe?.contentDocument?.querySelector(
        ".xterm-helper-textarea, #keyboard-input-assist, #noVNC_keyboardinput"
      );
      if (!textarea) return false;
      textarea.focus({ preventScroll: true });
      return true;
    } catch (error) {
      return false;
    }
  }

  return { isTouchDevice, focusTerminalKeyboard };
});
