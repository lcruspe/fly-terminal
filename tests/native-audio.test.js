import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html=fs.readFileSync(new URL('../vendor/novnc/webrtc.html',import.meta.url),'utf8');
const source=html.slice(html.indexOf('      // Native system audio:'),html.indexOf('      async function closeWebRtc('));
function setup(mode='client',reject=false,ws=false) {
  const messages=[], listeners={}, timers=[];
  const element=()=>({hidden:true,value:'',addEventListener(n,f){this[n]=f;}});
  const audio={...element(),paused:true,pause(){this.paused=true;},play(){this.paused=false;return reject?Promise.reject(Error('autoplay')):Promise.resolve();}};
  const select=element(),status=element(), samples=[], starts=[];
  class AudioContext {
    state='suspended'; currentTime=1;
    resume(){this.state='running';return Promise.resolve();}
    suspend(){this.state='suspended';return Promise.resolve();}
    createBuffer(){const channels=[new Float32Array(960),new Float32Array(960)];samples.push(channels);return {getChannelData:i=>channels[i]};}
    createBufferSource(){return {connect(){},start:t=>starts.push(t),stop(){}};}
  }
  const ctx=vm.createContext({document:{visibilityState:'visible',getElementById:id=>({remoteAudio:audio,audioMode:select,audioStatusBtn:status,mediaPriority:element()})[id],addEventListener:(n,f)=>listeners[n]=f},
    window:{AudioContext,addEventListener:(n,f)=>listeners[n]=f},usingWebRtc:!ws,socket:{readyState:1},WebSocket:{OPEN:1},performance:{now:()=>100},reliableChannel:{},dataChannelOpen:()=>true,peerConnection:{connectionState:'connected'},
    mediaPriority:'audio',preferredAudioMode:mode,nativeAudioKey:'nativeDesktopAudioMode',safeStorageSet(){},queueNativePreferences(){},sendTransportMessage:m=>{messages.push(JSON.parse(JSON.stringify(m)));return true;},
    setInterval:f=>timers.push(f),setTimeout(){}});
  vm.runInContext(source+'\naudioOwner=true;audioTrackAvailable=true;audioPcmAvailable=true;',ctx);
  return {ctx,messages,audio,select,status,listeners,timers,samples,starts};
}
test('client-only mode first authorizes playback without muting the Mac',async()=>{
  const {ctx,messages,listeners}=setup();
  ctx.activatePreferredAudio();
  assert.deepEqual(messages,[{type:'audio_mode',mode:'both'}]);
  await new Promise(setImmediate);
  assert.equal(messages.at(-1).mode,'client');
  listeners.pagehide();
  assert.equal(messages.at(-1).mode,'off');
});
test('autoplay rejection stops capture without requesting mute',async()=>{
  const {ctx,messages}=setup('client',true);
  ctx.activatePreferredAudio();
  await new Promise(setImmediate);
  assert.deepEqual(messages.map(m=>m.mode),['both','off']);
});
test('touch capability disables only idle quality reduction',()=>{
  const code=html.slice(html.indexOf('      function sendSessionSettings('),html.indexOf('      async function disconnectForIdle('));
  for(const touch of [0,5]){
    const messages=[];
    const ctx=vm.createContext({navigator:{maxTouchPoints:touch},window:{matchMedia:()=>({matches:false})},sessionIdleTimeoutSeconds:300,sendTransportMessage:m=>messages.push(m)});
    vm.runInContext(code,ctx);ctx.sendSessionSettings();
    assert.equal(messages[0].idleQualityReduction,touch===0);
    assert.equal(messages[0].idleTimeoutSeconds,300);
  }
});

test('WebSocket PCM enables selector and only mutes after actual playback is scheduled',async()=>{
  const {ctx,messages,select,samples,starts,listeners}=setup('client',false,true);
  ctx.refreshAudioControl();assert.equal(select.disabled,false);
  ctx.activatePreferredAudio();
  assert.deepEqual(messages,[{type:'audio_mode',mode:'both',format:'pcm16'}]);
  await new Promise(setImmediate);assert.equal(messages.length,1);
  const buffer=new ArrayBuffer(3845),data=new DataView(buffer);
  data.setUint8(0,0x41);data.setInt16(5,16384,true);data.setInt16(7,-16384,true);
  ctx.receivePcmPacket(buffer);
  await new Promise(setImmediate);
  assert.equal(samples[0][0][0],0.5);assert.equal(samples[0][1][0],-0.5);
  assert.equal(starts.length,1);assert.equal(messages.at(-1).mode,'client');
  listeners.pagehide();assert.equal(messages.at(-1).mode,'off');
  ctx.receivePcmPacket(buffer);assert.equal(starts.length,1);
});
test('WebSocket without server audio capability remains disabled',()=>{
  const {ctx,select,messages}=setup('client',false,true);
  vm.runInContext('audioPcmAvailable=false;',ctx);ctx.refreshAudioControl();
  assert.equal(select.disabled,true);ctx.activatePreferredAudio();assert.equal(messages.length,0);
});

test('audio priority buffers half a second and video priority stays responsive', async()=>{
  for(const [mode,delay] of [['audio',0.5],['balanced',0.16],['video',0.04]]) {
    const {ctx,starts}=setup('both',false,true);
    ctx.mediaPriority=mode;
    ctx.activatePreferredAudio();
    ctx.receivePcmPacket(new ArrayBuffer(3845));
    assert.ok(Math.abs(starts[0]-1-delay)<1e-9);
    await new Promise(setImmediate);
  }
});
