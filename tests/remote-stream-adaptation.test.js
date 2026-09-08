import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../vendor/novnc/webrtc.html', import.meta.url), 'utf8');
const adaptation = html.slice(html.indexOf('let networkEvaluationAt ='), html.indexOf('function decodeVideoPacket('));

function scenario(rtt) {
  const state = {
    now: 0, lastRttMs: rtt, lastRttDeltaMs: 0,
    latestServerStats: {}, latestDecodeQueueSize: 0,
    poorNetworkTicks: 0, stableNetworkTicks: 0, currentBitrate: 2_000_000,
    changes: [],
    configureStream() { throw new Error('Network adaptation must not restart capture'); },
  };
  state.performance = { now: () => state.now };
  state.setTargetBitrate = (value) => { state.currentBitrate = value; state.changes.push(value); };
  vm.createContext(state);
  vm.runInContext(adaptation, state);
  return state;
}

test('stable high RTT does not repeatedly reduce quality', () => {
  const state = scenario(240);
  for (let i = 0; i < 10; i++) { state.now = i * 2000; state.evaluateNetworkQuality(); }
  assert.equal(state.poorNetworkTicks, 0);
  assert.ok(state.currentBitrate >= 2_000_000);
});

test('duplicate stats/probe callbacks cannot multiply adaptation or restart capture', () => {
  const state = scenario(30);
  state.evaluateNetworkQuality();
  state.lastRttMs = 250;
  state.now = 2000;
  state.evaluateNetworkQuality();
  state.evaluateNetworkQuality();
  assert.equal(state.changes.length, 1);
  for (let i = 2; i < 8; i++) { state.now = i * 2000; state.evaluateNetworkQuality(); }
  assert.ok(state.currentBitrate < 2_000_000);
});
