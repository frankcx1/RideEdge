const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const locationUI = require('../farol/static/location.js');
const flush = () => new Promise(resolve => setImmediate(resolve));
const position = (changes = {}) => ({coords:{latitude:47.6062,longitude:-122.3321,accuracy:12},timestamp:Date.now(),...changes});
const fix = () => locationUI.validate(position());

test('device requests require HTTPS and request an uncached high accuracy reading', async () => {
  await assert.rejects(locationUI.get({isSecureContext:false}), /HTTPS/);
  let options;
  const result = await locationUI.get({isSecureContext:true,navigator:{geolocation:{getCurrentPosition(ok, fail, opts) { options=opts; ok(position()); }}}});
  assert.deepEqual(options, {enableHighAccuracy:true,timeout:15000,maximumAge:0});
  assert.equal(result.latitude, 47.6062);
  assert.match(locationUI.note(result), /±12 m · checked/);
  assert.deepEqual(locationUI.body(result), {latitude:47.6062,longitude:-122.3321});
});

test('stale, coarse, invalid and out of coverage fixes are rejected', () => {
  assert.throws(() => locationUI.validate(position({timestamp:Date.now()-31000})), /old location/);
  assert.throws(() => locationUI.validate(position({timestamp:Date.now()+20000})), /old location/);
  assert.throws(() => locationUI.validate(position({coords:{latitude:47.6,longitude:-122.3,accuracy:5000}})), /precise location/);
  for (const coords of [{latitude:0,longitude:0,accuracy:10},{latitude:47.6,longitude:-122.3},{latitude:NaN,longitude:-122.3,accuracy:10}]) {
    assert.throws(() => locationUI.validate(position({coords})), /unusable/);
  }
  const pin = fix();
  assert.equal(locationUI.fresh(pin,pin.timestamp+300000), true);
  assert.equal(locationUI.fresh(pin,pin.timestamp+300001), false);
});

test('permission, timeout and unavailable errors have actionable messages', async () => {
  for (const [code,expected] of [[1,/permission is blocked/],[2,/could not determine/],[3,/timed out/]]) {
    await assert.rejects(locationUI.get({isSecureContext:true,navigator:{geolocation:{getCurrentPosition(ok,fail) { fail({code}); }}}}), expected);
  }
});

function harness(file) {
  const nodes = new Map(), requests = [], gps = [];
  const node = id => {
    if (!nodes.has(id)) {
      const classes = new Set();
      nodes.set(id,{textContent:'',innerHTML:'',value:({'awareness-area':'totem_lake','awareness-period':'all','vehicle-cost':'0.45','value-of-time':'25'})[id] || '',disabled:false,
        classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x),toggle:(x,on)=>on?classes.add(x):classes.delete(x)},
        setAttribute(){},addEventListener(){}});
    }
    return nodes.get(id);
  };
  const document = {getElementById:node,querySelectorAll:()=>[],addEventListener(){}};
  const context = vm.createContext({document,URLSearchParams,URL,Date,console,
    location:{search:'',hash:'#working'},window:{isSecureContext:true,location:{search:''}},
    RideEdgeLocation:{...locationUI,get:()=>new Promise((resolve,reject)=>gps.push({resolve,reject}))},
    fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve:data=>resolve({ok:true,json:async()=>data})}))});
  vm.runInContext(fs.readFileSync(require.resolve(`../farol/static/${file}.js`),'utf8'), context);
  return {node,requests,gps,run:code=>vm.runInContext(code,context)};
}
const area = (id='seattle_core', label='Seattle core') => ({area:id,location_label:label,areas:[{id,label}],snapshot:{state:'ready',age_minutes:0},observations:[],venue_activity:[],feeds:[],busyness_coverage:{},period:'all'});
const here = (id='seattle_core',label='Seattle core') => ({place:{zone:id,label},action:'WATCH',nearby:[],warnings:[],spoken:'No clear move'});

test('Around you replaces Kirkland with Seattle and shows accuracy and time', async () => {
  const h=harness('awareness');
  const pending=h.run('locate()'); h.gps[0].resolve(fix()); await flush();
  assert.equal(h.requests[0].options.method,'POST');
  assert.doesNotMatch(h.requests[0].url,/47\.6062|-122\.3321/);
  assert.deepEqual(JSON.parse(h.requests[0].options.body),locationUI.body(fix()));
  h.requests[0].resolve(area()); await pending;
  assert.equal(h.node('awareness-area').value,'seattle_core');
  assert.match(h.node('view-location').textContent,/device location · near Seattle/);
  assert.match(h.node('location-note').textContent,/±12 m · checked/);
  assert.equal(h.node('awareness-content').classList.contains('hidden'),false);
});

test('Around you clears old results on permission failure and requires a new selection', async () => {
  const h=harness('awareness'); h.run('render('+JSON.stringify(area('totem_lake','Totem Lake'))+')');
  const pending=h.run('locate()');
  assert.equal(h.node('awareness-content').classList.contains('hidden'),true);
  h.gps[0].reject(new Error('Location permission is blocked')); await pending;
  assert.equal(h.node('awareness-area').value,'');
  assert.match(h.node('awareness-error').textContent,/blocked/);
  await h.run('load()'); assert.equal(h.requests.length,0);
});

test('manual area selection wins over a late GPS success or failure', async () => {
  for (const fail of [false,true]) {
    const h=harness('awareness'), pending=h.run('locate()');
    h.node('awareness-area').value='redmond_downtown'; h.run('selectArea()');
    h.requests[0].resolve(area('redmond_downtown','Redmond downtown')); await flush();
    if (fail) h.gps[0].reject(new Error('Old GPS failure')); else h.gps[0].resolve(fix());
    await pending;
    assert.equal(h.requests.length,1);
    assert.equal(h.node('awareness-area').value,'redmond_downtown');
    assert.match(h.node('view-location').textContent,/Selected area · Redmond/);
    assert.equal(h.node('awareness-error').textContent,'');
  }
});

test('an old area fetch cannot redraw cards during a new GPS request', async () => {
  const h=harness('awareness'), old=h.run('load()'), pending=h.run('locate()');
  h.requests[0].resolve(area('totem_lake','Totem Lake')); await old;
  assert.equal(h.node('awareness-content').classList.contains('hidden'),true);
  assert.match(h.node('view-location').textContent,/Getting device/);
  h.gps[0].reject(new Error('Unavailable')); await pending;
});

test('expired nearby pins require refresh, while Metro remains available', async () => {
  const h=harness('awareness');
  h.run('parked = {latitude:47.6062,longitude:-122.3321,accuracy:10,timestamp:Date.now()-301000}');
  await h.run('load()'); assert.equal(h.requests.length,0);
  assert.match(h.node('awareness-error').textContent,/5 minutes/);
  h.run('changeScope("metro")'); h.requests[0].resolve(area()); await flush();
  assert.equal(h.node('awareness-content').classList.contains('hidden'),false);
  h.run('changeScope("nearby")');
  assert.equal(h.node('awareness-content').classList.contains('hidden'),true);
  assert.match(h.node('snapshot-status').textContent,/Location needed/);
});

test('Working posts device coordinates and speaks the resolved Seattle area', async () => {
  const h=harness('tonight'), pending=h.run('parkedHere()');
  h.gps[0].resolve(fix()); await flush();
  assert.equal(h.requests[0].options.method,'POST');
  assert.doesNotMatch(h.requests[0].url,/at=|47\.6062|-122\.3321/);
  h.requests[0].resolve(here()); await pending;
  assert.equal(h.node('here-place').textContent,'Near Seattle core');
  assert.match(h.node('here-location-note').textContent,/Device location · ±12 m/);
  assert.equal(h.node('here-gps').disabled,false);
});

test('Working clears Kirkland cards and speech immediately, including GPS failure', async () => {
  const h=harness('tonight'); h.run('renderHere('+JSON.stringify(here('totem_lake','Totem Lake'))+')');
  const pending=h.run('parkedHere()');
  assert.equal(h.node('here-detail-panel').classList.contains('hidden'),true);
  assert.match(h.run('spokenAnswer()'),/Choose a location/);
  h.gps[0].reject(new Error('Permission blocked')); await pending;
  assert.equal(h.node('here-place').textContent,'LOCATION NEEDED');
  assert.match(h.node('here-error').textContent,/Permission blocked/);
  assert.match(h.run('spokenAnswer()'),/Choose a location/);
});

test('Working manual selection wins over late GPS success or failure', async () => {
  for (const fail of [false,true]) {
    const h=harness('tonight'), pending=h.run('parkedHere()');
    h.node('here-at').value='Redmond'; const manual=h.run('sitHereNow()');
    h.requests[0].resolve(here('redmond_downtown','Redmond downtown')); await manual;
    if (fail) h.gps[0].reject(new Error('Late error')); else h.gps[0].resolve(fix());
    await pending;
    assert.equal(h.requests.length,1);
    assert.equal(h.node('here-place').textContent,'Near Redmond downtown');
    assert.equal(h.node('here-error').classList.contains('hidden'),true);
    assert.equal(h.node('here-gps').disabled,false);
  }
});

test('Working expires old device guidance instead of speaking it as current', async () => {
  const h=harness('tonight'); h.run('renderHere('+JSON.stringify(here())+')');
  h.run('lastDeviceLocation = {timestamp:Date.now()-301000}');
  assert.match(h.run('spokenAnswer()'),/Choose a location/);
  assert.equal(h.node('here-place').textContent,'LOCATION EXPIRED');
  assert.equal(h.node('here-detail-panel').classList.contains('hidden'),true);
});
