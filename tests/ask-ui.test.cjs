const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createRideEdgeAsk}=require('../farol/static/ask.js');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const constraints={minutes_available:90,reposition_under_minutes:15,finish_near:'kirkland_waterfront'};
const comparison={constraints,options:[],answer:'Watch Bellevue',deadline:'2026-09-19T21:30:00-07:00',limits:'Unknown rider demand'};
const context={snapshot_id:'snap-a',scenario_id:'demo',mode:'demo',label:'Simulated scenario',origin:'Bellevue',as_of:'2026-09-19T20:00:00-07:00',changes:[],evidence:[]};
function harness() {
  const nodes=new Map(), events={}, requests=[];
  function node(id) {
    if (!nodes.has(id)) nodes.set(id,{value:({'ask-minutes':90,'ask-limit':15,'ask-finish':'kirkland_waterfront'})[id]??'',textContent:'',innerHTML:'',open:false,disabled:false,
      classList:{toggle:()=>{}},querySelectorAll:()=>[],addEventListener:(kind,fn)=>events[`${id}:${kind}`]=fn});
    return nodes.get(id);
  }
  const env={isSecureContext:true,document:{getElementById:node,querySelectorAll:()=>[],addEventListener:(kind,fn)=>events[kind]=fn},
    addEventListener:(kind,fn)=>events[kind]=fn,setTimeout,
    fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve:body=>resolve({ok:true,json:async()=>body})}))};
  const ui=createRideEdgeAsk({},env);
  async function ready() {
    const pending=ui.refresh(); requests.at(-1).resolve({context,comparison}); await flush(); requests.at(-1).resolve(comparison); await pending;
  }
  return {ui,node,requests,events,ready};
}
const answer=text=>({state:'ready',request_id:text,snapshot_id:'snap-a',comparison,answer:text,answer_state:'Fresh local inference',explanation:[],execution:{generation_seconds:1},model:'qwen3.8-27b'});

test('late answer cannot replace a newer question',async()=>{
  const h=harness(); await h.ready();
  const first=h.ui.submit('First question'), r1=h.requests.at(-1);
  const second=h.ui.submit('New question'), r2=h.requests.at(-1);
  r2.resolve(answer('New answer')); await second;
  r1.resolve(answer('Old answer')); await first;
  assert.equal(h.node('ask-answer').textContent,'New answer');
});
test('changing preferences recomputes without Qwen and invalidates old answer',async()=>{
  const h=harness(); await h.ready(); const first=h.ui.submit('Question'), r1=h.requests.at(-1);
  h.node('ask-limit').value=30;
  const update=h.events['ask-limit:change'](), request=h.requests.at(-1);
  assert.equal(request.url,'/api/ask/compare');
  assert.equal(JSON.parse(request.options.body).constraints.reposition_under_minutes,30);
  request.resolve({...comparison,constraints:{...constraints,reposition_under_minutes:30}}); await update;
  r1.resolve(answer('Obsolete answer')); await first;
  assert.equal(h.node('ask-answer').textContent,'');
  assert.equal(h.node('ask-answer-state').textContent,'Python comparison');
});
test('mode switch prevents a late model answer from rendering',async()=>{
  const h=harness(); await h.ready(); const pending=h.ui.submit('Why?'), request=h.requests.at(-1);
  h.events.hashchange(); request.resolve(answer('Late')); await pending;
  assert.equal(h.node('ask-answer').textContent,'');
});
test('new area clears the old snapshot before another question',async()=>{
  const h=harness(); await h.ready(); h.ui.setArea('kirkland_waterfront');
  const pending=h.ui.refresh();
  assert.match(h.requests.at(-1).url,/area=kirkland_waterfront/);
  h.requests.at(-1).resolve({context:{...context,snapshot_id:'snap-b'},comparison}); await flush();
  assert.equal(JSON.parse(h.requests.at(-1).options.body).snapshot_id,'snap-b');
  h.requests.at(-1).resolve(comparison); await pending;
});

test('pending or failed device location clears old comparison and blocks reuse',async()=>{
  const h=harness(); await h.ready(); const count=h.requests.length;
  h.ui.clearArea();
  assert.equal(h.ui.answer(),'');
  assert.equal(h.node('ask-summary').textContent,'');
  await h.ui.submit('Where should I go?');
  assert.equal(h.requests.length,count);
  assert.match(h.node('ask-status').textContent,/Choose a location/);
  h.ui.setArea('seattle_core'); const pending=h.ui.refresh();
  assert.match(h.requests.at(-1).url,/area=seattle_core/);
  h.requests.at(-1).resolve({context:{...context,origin:'Seattle',snapshot_id:'seattle'},comparison}); await flush();
  h.requests.at(-1).resolve(comparison); await pending;
  assert.match(h.node('ask-deadline').textContent,/From Seattle/);
});
