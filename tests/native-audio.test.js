import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html=fs.readFileSync(new URL('../vendor/novnc/webrtc.html',import.meta.url),'utf8');
const source=html.slice(html.indexOf('      // Native system audio:'),html.indexOf('      async function closeWebRtc('));
function setup(mode='client',reject=false) {
  const messages=[], listeners={}, timers=[];
  const element=()=>({hidden:true,value:'',addEventListener(n,f){this[n]=f;}});
  const audio={...element(),paused:true,pause(){this.paused=true;},play(){this.paused=false;return reject?Promise.reject(Error('autoplay')):Promise.resolve();}};
  const select=element(),status=element();
  const ctx=vm.createContext({document:{visibilityState:'visible',getElementById:id=>({remoteAudio:audio,audioMode:select,audioStatusBtn:status})[id],addEventListener:(n,f)=>listeners[n]=f},
    window:{addEventListener:(n,f)=>listeners[n]=f},usingWebRtc:true,reliableChannel:{},dataChannelOpen:()=>true,peerConnection:{connectionState:'connected'},
    preferredAudioMode:mode,nativeAudioKey:'nativeDesktopAudioMode',safeStorageSet(){},queueNativePreferences(){},sendTransportMessage:m=>{messages.push(JSON.parse(JSON.stringify(m)));return true;},
    setInterval:f=>timers.push(f),setTimeout(){}});
  vm.runInContext(source+'\naudioOwner=true;audioTrackAvailable=true;',ctx);
  return {ctx,messages,audio,select,status,listeners,timers};
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
