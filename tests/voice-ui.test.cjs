const {test} = require('node:test');
const assert = require('node:assert/strict');
const {voiceIntent, createVoice} = require('../farol/static/voice.js');
const flush = () => new Promise(resolve => setImmediate(resolve));

function harness({secure=true, delayedPermission=false, question=null}={}) {
  const nodes = new Map(), events = {}, records = [], requests = [], locations = [], players = [];
  const node = id => {
    if (!nodes.has(id)) { const classes = new Set(); nodes.set(id, {value:'', textContent:'', disabled:false,
      classList:{add:k=>classes.add(k), remove:k=>classes.delete(k), contains:k=>classes.has(k), toggle:(k,on)=>on?classes.add(k):classes.delete(k)},
      addEventListener:(kind, fn)=>events[`${id}:${kind}`]=fn}); }
    return nodes.get(id);
  };
  let stopped = 0, permission;
  const stream = {getTracks:()=>[{stop:()=>stopped++}]};
  class Recorder {
    static isTypeSupported() { return true; }
    constructor(_, options) { this.mimeType=options.mimeType; this.state='inactive'; records.push(this); }
    start() { this.state='recording'; }
    stop() { this.state='inactive'; this.ondataavailable?.({data:new Blob(['audio'])}); queueMicrotask(()=>this.onstop?.()); }
  }
  class Audio {
    constructor() { this.paused=true; players.push(this); }
    async play() { this.paused=false; }
    pause() { this.paused=true; }
    removeAttribute() {} load() {}
  }
  const env = {isSecureContext:secure, navigator:{mediaDevices:{getUserMedia:()=>delayedPermission?new Promise(r=>permission=r):Promise.resolve(stream)}},
    MediaRecorder:Recorder, Audio, AbortController, Blob,
    URL:{createObjectURL:()=> 'blob:reply', revokeObjectURL:()=>{}},
    setTimeout:()=>1, clearTimeout:()=>{}, setInterval:()=>2, clearInterval:()=>{},
    document:{hidden:false, getElementById:node, addEventListener:(kind,fn)=>events[kind]=fn},
    addEventListener:(kind,fn)=>events[kind]=fn,
    fetch:(url, options)=>new Promise(resolve=>requests.push({url,options,resolve})),
  };
  const ui = createVoice({location:async place=>{ locations.push(place); return true; }, answer:()=> 'Watch Bellevue. Live demand unknown.', nearby:()=>{}, wantsQuestion:()=>Boolean(question), question}, env);
  return {ui,env,node,events,records,requests,locations,players,stopped:()=>stopped,grant:()=>permission(stream)};
}
const transcription = text => ({ok:true, json:async()=>({text})});
const speech = () => ({ok:true, blob:async()=>new Blob(['RIFF'])});

test('bounded voice commands parse real Seattle place requests', () => {
  for (const [phrase,place] of [["I'm in Bellevue. Where should I go?",'Bellevue'],['I am near Totem Lake.','Totem Lake'],['Capitol Hill','Capitol Hill'],['Check WAMU Theater.','WAMU Theater']]) assert.deepEqual(voiceIntent(phrase), {kind:'location',place});
  assert.equal(voiceIntent('Read my brief.').kind, 'brief');
  assert.equal(voiceIntent('Where should I go?').kind, 'here');
  assert.equal(voiceIntent('What’s around me?').kind, 'nearby');
  assert.equal(voiceIntent('Stop talking!').kind, 'stop');
});
test('constraints and consequential actions cannot become a location lookup', () => {
  for (const phrase of ['Bellevue under 15 minutes', 'Avoid Seattle', 'Compare Kirkland versus Bellevue', 'Take me to Redmond', 'Send to Volvo', 'I need to earn $200', 'Where should I go for more rides?', 'Bellevue or Seattle']) assert.equal(voiceIntent(phrase).kind, 'unsupported', phrase);
});
test('insecure phone URL never requests microphone', async () => {
  const h=harness({secure:false}); await h.ui.record();
  assert.equal(h.records.length,0); assert.match(h.node('voice-status').textContent,/HTTPS/);
});
test('late microphone permission after cancel immediately stops tracks', async () => {
  const h=harness({delayedPermission:true}); const pending=h.ui.record(); h.ui.cancel(); h.grant(); await pending;
  assert.equal(h.stopped(),1); assert.equal(h.records.length,0);
});
test('finish releases microphone before transcription then reads result', async () => {
  const h=harness(); await h.ui.record(); await h.ui.record(); await flush();
  assert.equal(h.stopped(),1); assert.equal(h.requests[0].url,'/api/voice/transcribe');
  h.requests[0].resolve(transcription("I'm in Bellevue.")); await flush();
  assert.deepEqual(h.locations,['Bellevue']); assert.equal(h.requests[1].url,'/api/voice/speak');
  h.requests[1].resolve(speech()); await flush();
  assert.equal(h.node('voice-play').textContent,'Stop speaking');
  h.ui.cancel(); assert.equal(h.players[0].paused,true);
});
test('canceled upload cannot execute a stale location or speak', async () => {
  const h=harness(); await h.ui.record(); await h.ui.record(); await flush(); h.ui.cancel();
  assert.equal(h.requests[0].options.signal.aborted,true);
  h.requests[0].resolve(transcription('Bellevue')); await flush();
  assert.deepEqual(h.locations,[]); assert.equal(h.requests.length,1);
});
test('hiding page stops recording and discards captured audio', async () => {
  const h=harness(); await h.ui.record(); h.env.document.hidden=true; h.events.visibilitychange(); await flush();
  assert.equal(h.stopped(),1); assert.equal(h.requests.length,0);
});
test('late recorder error does not cancel a new recording', async () => {
  const h=harness(); await h.ui.record(); const old=h.records[0]; h.ui.cancel(); await h.ui.record(); old.onerror();
  assert.equal(h.records[1].state,'recording'); assert.equal(h.node('voice-record').textContent,'Finish'); h.ui.cancel();
});
test('transcription failure leaves typed input and retry available', async () => {
  const h=harness(); await h.ui.record(); await h.ui.record(); await flush();
  h.requests[0].resolve({ok:false,json:async()=>({detail:'No clear speech'})}); await flush();
  assert.match(h.node('voice-status').textContent,/No clear speech/); assert.equal(h.node('voice-record').disabled,false);
  assert.equal(h.locations.length,0);
});
test('late speech response after cancel cannot start audio playback', async () => {
  const h=harness(); const pending=h.ui.listen(); h.ui.cancel(); h.requests[0].resolve(speech()); await pending;
  assert.equal(h.players.length,0);
});
test('Ask by voice preserves the full preference question for Qwen', async()=>{
  const questions=[], h=harness({question:async text=>{questions.push(text); return 'Seattle is excluded by your route limit.';}});
  await h.ui.record(); await h.ui.record(); await flush();
  h.requests[0].resolve(transcription('Keep reposition drives under 15 minutes.')); await flush();
  assert.deepEqual(questions,['Keep reposition drives under 15 minutes.']);
  assert.deepEqual(h.locations,[]);
  assert.equal(h.requests[1].url,'/api/voice/speak'); h.requests[1].resolve(speech()); await flush(); h.ui.cancel();
});
test('canceling a spoken question suppresses its late spoken answer', async()=>{
  let resolveAnswer;
  const h=harness({question:()=>new Promise(resolve=>resolveAnswer=resolve)});
  await h.ui.record(); await h.ui.record(); await flush(); h.requests[0].resolve(transcription('Compare my options')); await flush();
  h.ui.cancel(); resolveAnswer('Old answer'); await flush(); assert.equal(h.requests.length,1);
});
test('microphone denial leaves retry and typing available', async()=>{
  const h=harness(); h.env.navigator.mediaDevices.getUserMedia=async()=>{const error=new Error('Denied');error.name='NotAllowedError';throw error;};
  await h.ui.record(); assert.match(h.node('voice-status').textContent,/permission was denied/);
  assert.equal(h.node('voice-record').disabled,false); assert.equal(h.requests.length,0);
});
test('autoplay denial offers an explicit playback gesture',async()=>{
  const h=harness(); h.env.Audio.prototype.play=async()=>{throw new Error('Autoplay blocked');};
  const pending=h.ui.listen(); h.requests[0].resolve(speech()); await pending;
  assert.equal(h.node('voice-play').textContent,'Play reply');
  h.env.Audio.prototype.play=async function(){this.paused=false;}; await h.ui.listen();
  assert.equal(h.node('voice-play').textContent,'Stop speaking'); h.ui.cancel();
});
