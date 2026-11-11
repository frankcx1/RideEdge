const {test}=require('node:test');
const assert=require('node:assert/strict');
const ui=require('../farol/static/podcast.js');
const plan={cues:[{id:'one',fraction:0},{id:'two',fraction:.4},{id:'three',fraction:.8}]};

test('cue boundaries track media time, including seeking backwards',()=>{
  const cues=ui.estimates(plan,300);
  assert.equal(ui.cueAt(cues,119.9),0);
  assert.equal(ui.cueAt(cues,120),1);
  assert.equal(ui.cueAt(cues,300),2);
  assert.equal(ui.cueAt(cues,0),0);
  assert.equal(ui.timingValid(cues,300),true);
});
test('duration changes preserve transcript proportions without claiming exact timing',()=>{
  assert.deepEqual(ui.estimates(plan,450).map(row=>row.at),[0,180,360]);
  assert.equal(ui.clock(65.8),'1:05');
});
test('imported timing rejects mismatched cues, duplicates, and invalid media ranges',()=>{
  const saved={version:1,duration:300,segment_start:60,reviewed:true,cues:[{id:'one',at:0},{id:'two',at:100},{id:'three',at:200}]};
  assert.equal(ui.importTiming(saved,plan).reviewed,true);
  assert.equal(ui.importTiming(saved,plan).segment_start,60);
  for(const change of [{duration:NaN},{segment_start:-1},{cues:[{id:'wrong',at:0},...saved.cues.slice(1)]},{cues:saved.cues.map(row=>({...row,at:0}))},{duration:180}]) {
    assert.throws(()=>ui.importTiming({...saved,...change},plan));
  }
});
test('collected events preserve uncertainty and escape external text',()=>{
  const card=ui.eventCard({title:'<script>wrong</script>',date_only:true,community_event:true,location_label:'Marymoor',source:'city',freshness:'old source data',conflicts:['date conflict']});
  assert.match(card,/Hours unconfirmed/);assert.match(card,/old source data/);assert.match(card,/schedule needs confirmation/);
  assert.doesNotMatch(card,/<script>/);
});
test('simulated decision is labeled and taken from the supplied engine comparison',()=>{
  const comparison={answer:'Watch Kirkland.',best_id:'k',options:[{id:'k',area:'Kirkland',venue:'Fictional venue',eligible:true,route_minutes:14,reasons:['Within limit']}]};
  const result=ui.scene('changed',{plan:{states:[{comparison},{comparison}]}},'decision');
  assert.match(result.badge,/Simulated/);assert.match(result.html,/Watch Kirkland/);assert.match(result.html,/14/);
  assert.match(result.html,/Python checks/);
});
test('missing source coverage and model evaluations stay explicitly unavailable',()=>{
  const comparison={options:[]},base={states:[{comparison},{comparison}],model_checks:[]};
  const nearby=ui.scene('around',{plan:base},'around');assert.equal(nearby.badge,'Feeds unavailable');
  assert.match(nearby.html,/Missing coverage/);
  const airport=ui.scene('airport',{plan:base},'flight');assert.match(airport.html,/No recent airport arrival/);
  const models=ui.scene('models',{plan:base},'gemma');assert.doesNotMatch(models.html,/App response checks/);
  assert.match(models.html,/reported generation speeds/);
});
