import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../vendor/novnc/webrtc.html', import.meta.url), 'utf8');
const functions = html.slice(html.indexOf('      function getRenderedScreenRect()'), html.indexOf('      inputLayer.addEventListener("pointermove"'));

for (const usingWebRtc of [false, true]) {
  for (const mode of ['contain', 'fill', 'sync']) {
    for (const autoResize of [false, true]) {
      test(`${usingWebRtc ? 'WebRTC' : 'WebCodecs'} ${mode}, auto-resize ${autoResize}`, () => {
        const objectFit = autoResize || mode === 'fill' ? 'fill' : 'contain';
        const surface = { width: 1600, height: 900, videoWidth: 1600, videoHeight: 900,
          getBoundingClientRect: () => ({ left: 20, top: 30, width: 1000, height: 800 }) };
        const context = vm.createContext({ usingWebRtc, screenVideo: surface, canvas: surface,
          fitMode: mode, streamWidth: 800, streamHeight: 600,
          getComputedStyle: () => ({ objectFit }) });
        vm.runInContext(functions, context);
        // The stream metadata intentionally differs from the displayed frame.
        const top = objectFit === 'fill' ? 30 : 148.75;
        const height = objectFit === 'fill' ? 800 : 562.5;
        for (const [x, y] of [[0, 0], [0.25, 0.25], [0.5, 0.5], [0.75, 0.75], [1, 1]]) {
          const actual = context.getNormalizedCoords({ clientX: 20 + 1000 * x, clientY: top + height * y });
          assert.equal(actual.x, x);
          assert.equal(actual.y, y);
        }
        assert.equal(context.getNormalizedCoords({ clientX: -100, clientY: -100 }).x, 0);
        assert.equal(context.getNormalizedCoords({ clientX: 2000, clientY: 2000 }).y, 1);
      });
    }
  }
}
