import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../vendor/novnc/webrtc.html', import.meta.url), 'utf8');
const code = html.slice(html.indexOf('      function analyzeBottlenecks('), html.indexOf('      function sampleBottlenecks()'));
const context = { percentile: (values, fraction) => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.ceil(sorted.length * fraction) - 1];
} };
vm.createContext(context);
vm.runInContext(code, context);
function samples(patch = {}) {
  return Array.from({ length: 12 }, (_, i) => ({
    at: i * 1000, connected: true, hidden: false, idle: false, targetFps: 30,
    fps: 30, sourceFrameId: i * 30, rttMs: 25, jitterMs: 3,
    captureMs: 5, encodeMs: 8, queueMs: 2, decodeMs: 8,
    lossPercent: 0, droppedPercent: 0, decodeQueue: 0, ...patch,
  }));
}
function areas(data) { return [...context.analyzeBottlenecks(data).findings].map(item => item.area); }

test('separately identifies network, capture, encoding, queue and client symptoms', () => {
  assert.deepEqual(areas(samples({ rttMs: 240 })), ['Сеть']);
  assert.deepEqual(areas(samples({ lossPercent: 5 })), ['Сеть']);
  assert.deepEqual(areas(samples({ captureMs: 100 })), ['Mac: захват или кодирование']);
  assert.deepEqual(areas(samples({ encodeMs: 80 })), ['Mac: захват или кодирование']);
  assert.deepEqual(areas(samples({ queueMs: 150 })), ['Очередь отправки']);
  assert.deepEqual(areas(samples({ decodeMs: 80 })), ['Клиент: декодирование или вывод']);
  assert.deepEqual(areas(samples({ droppedPercent: 20 })), ['Клиент: декодирование или вывод']);
});

test('detects low presentation rate only while source is producing frames', () => {
  assert.ok(areas(samples({ fps: 5 })).includes('Низкий FPS при активном источнике'));
  assert.deepEqual(areas(samples({ fps: 0, sourceFrameId: 123 })), []);
  assert.deepEqual(areas(samples({ fps: 0, sourceFrameId: null })), []);
});

test('avoids fault attribution with too few samples, hidden tabs and idle profile', () => {
  assert.equal(context.analyzeBottlenecks(samples().slice(0, 4)).status, 'collecting');
  assert.equal(context.analyzeBottlenecks(samples({ hidden: true, rttMs: 300 })).status, 'hidden');
  assert.equal(context.analyzeBottlenecks(samples({ idle: true, fps: 5 })).status, 'idle');
  assert.equal(context.analyzeBottlenecks(samples({ connected: false })).status, 'disconnected');
  assert.equal(context.analyzeBottlenecks(samples()).status, 'no_signal');
  const afterIdle = samples({ rttMs: 300 });
  afterIdle[9].idle = true;
  assert.equal(context.analyzeBottlenecks(afterIdle).status, 'collecting');
});

test('exports the current analysis and uses WebRTC interval deltas', () => {
  assert.match(html, /bottleneckAnalysis: analyzeBottlenecks\(bottleneckSamples\)/);
  assert.match(html, /Number\(inbound\.packetsLost\) - previousInboundStats\.lost/);
  assert.match(html, /Number\(inbound\.totalDecodeTime\) - previousInboundStats\.decodeTime/);
});
