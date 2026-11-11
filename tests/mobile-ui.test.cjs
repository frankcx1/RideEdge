const {test} = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = process.env.FAROL_UI_DIR || path.join(__dirname, '../farol/static');
const brief = require(path.join(root, 'tonight.js'));
const area = require(path.join(root, 'awareness.js'));

test('planning highlights at most three engine-ranked qualifying opportunities', () => {
  const rows = [1,2,3,4,5].map(n => ({id:String(n), score:n*10, action:'WATCH'}));
  const groups = brief.opportunityGroups({opportunities:rows, ranked_opportunity_ids:['5','4','3','2','1']});
  assert.deepEqual(groups.featured.map(r=>r.id), ['5','4','3']);
  assert.equal(groups.other.length, 2);
  assert.equal(rows[0].id, '1');
});
test('weak and avoided windows are not promoted to worth a look', () => {
  const opportunities = [{id:'avoid', action:'AVOID', score:40},{id:'weak', action:'WATCH', score:4.9}];
  assert.equal(brief.opportunityGroups({opportunities}).featured.length, 0);
  assert.equal(brief.opportunityGroups({opportunities:[{id:'x', action:'WATCH', score:30}],shift_decision:{action:'NO CLEAR SIGNAL'}}).featured.length, 0);
});
test('working recommendations preserve WATCH and label estimated repositioning', () => {
  const result = brief.workingSummary({place:{zone:'bellevue_core',label:'Bellevue'},action:'WATCH',best:{zone:'kirkland_waterfront',reposition_minutes:12,thin:true}});
  assert.match(result.title, /^Watch /);
  assert.match(result.text, /estimate/);
  assert.match(result.basis, /Limited pickup history/);
  assert.doesNotMatch(JSON.stringify(result), /\$|surge|guarantee/i);
});
test('WAIT uses staying evidence and retains uncertainty about waiting', () => {
  const result = brief.workingSummary({place:{zone:'bellevue_core',label:'Bellevue'},action:'WAIT',stay:{thin:true},best:{thin:false}});
  assert.match(result.title, /^Stay near/);
  assert.match(result.basis, /Limited pickup history.*wait time unknown/);
});
test('missing working history and missing travel minutes stay unknown', () => {
  const place = {zone:'bellevue_core',label:'Bellevue'};
  assert.equal(brief.workingSummary({place,action:'WATCH'}).title, 'No clear move yet');
  assert.equal(brief.workingSummary({place,action:'WATCH',best:{zone:'redmond'}}).text, 'Repositioning time unknown.');
  for (const route of [null,{}, {traffic_minutes:-1}, {traffic_minutes:'bad'}]) assert.equal(brief.routeLabel(route), 'Drive time unknown');
  assert.match(brief.routeLabel({traffic_minutes:12,basis:'assumed'}), /estimated/);
});
test('airport does not inherit a street recommendation or claim a queue length', () => {
  const result = brief.workingSummary({place:{zone:'sea_airport'},action:'WAIT',best:{zone:'bellevue_core'},stay:{},nearby:[]});
  assert.equal(result.title, 'Check the airport queue');
  assert.match(result.basis, /driver queue unknown/);
});
test('traffic never enters event or dining highlights, even when it dominates feeds', () => {
  const rows = Array.from({length:150},(_,i)=>({id:i,layer:'access'}));
  rows.push({id:'show',layer:'events'}, {id:'closing',layer:'dining'}, {id:'rain',layer:'weather'});
  const groups = area.groupObservations(rows);
  assert.deepEqual(groups.events.map(r=>r.id), ['show']);
  assert.deepEqual(groups.dining.map(r=>r.id), ['closing']);
  assert.equal(groups.access.length, 150);
  assert.equal(groups.other[0].id, 'rain');
});
test('an old high reading never becomes a live hotspot', () => {
  assert.equal(area.venueLabel({live_recent:false,live_value:150,live_delta:70,profile_usable:true}).text, 'Typical pattern only');
  assert.equal(area.venueLabel({live_recent:false,profile_usable:true,typically_closed_now:true}).text, 'Usually closed now');
  assert.equal(area.venueLabel({profile_usable:false}).text, 'Activity unknown');
});
test('live zero and unknown comparison are not described as busier than normal', () => {
  assert.equal(area.venueLabel({live_recent:true,live_value:0,live_delta:-50}).text, 'Quieter than usual');
  assert.equal(area.venueLabel({live_recent:true,live_value:80,live_delta:null}).text, 'Recent activity reading');
  assert.equal(area.venueLabel({live_recent:true,live_value:80,live_delta:0}).text, 'At its usual level');
});
test('recent venue activity outranks old high readings without mutating input', () => {
  const rows = [{name:'Old',live_recent:false,live_value:170},{name:'Usual',live_recent:true,live_delta:0},{name:'Busy',live_recent:true,live_delta:25}];
  assert.deepEqual(area.rankedVenues(rows).map(r=>r.name), ['Busy','Usual','Old']);
  assert.equal(rows[0].name,'Old');
});
test('unapproved curb has no navigation button; external titles are escaped', () => {
  const row = {id:'x',score:10,action:'WATCH',zone:'sodo',starts_at:'2026-09-19T21:00:00-07:00',ends_at:'2026-09-19T22:00:00-07:00',venue_name:'<img src=x onerror=alert(1)>',navigation_available:false};
  const card = brief.opportunityCard(row);
  assert.doesNotMatch(card, /<img|send-route/);
  assert.match(card, /&lt;img/);
  assert.match(brief.opportunityCard({...row,navigation_available:true}), /send-route/);
  assert.match(brief.opportunityCard({...row,navigation_available:true,anchor:{latitude:47.6794,longitude:-122.1813}}), /open-maps/);
});
test('road timing remains unverified and stale evidence remains visible on compact cards', () => {
  const card = area.observationCard({layer:'access',kind:'highway_alert',freshness:'old source data',title:'Ramp closure',zone_labels:['Bellevue'],timing_label:'Restriction times unverified',source:'test',basis:'live'});
  assert.match(card, /old source data/);
  assert.match(card, /Restriction times unverified/);
  assert.doesNotMatch(card, /closed now/i);
});

test('community dates without hours never appear as midnight let-outs', () => {
  const card = area.observationCard({layer:'events',kind:'special_event',community_event:true,
    date_only:true,end_unknown:true,category:'festival',title:'Tea Festival',zone_labels:['Seattle Center'],
    window_starts_at:'2026-09-26T00:00:00-07:00',ends_at:'2026-09-27T00:00:00-07:00',
    timing_label:'Hours unconfirmed',freshness:'recently checked',source_age_minutes:10,receipts:[],
    source:'community:visit_seattle',basis:'scheduled'});
  assert.match(card, /Sep 26/);
  assert.match(card, /Hours unconfirmed/);
  assert.doesNotMatch(card, /12:00|let-out/i);
});

test('community receipts escape titles and reject executable links', () => {
  const card = area.observationCard({layer:'events',kind:'special_event',community_event:true,
    title:'<img src=x onerror=alert(1)>',zone_labels:['Seattle'],freshness:'not seen on latest check',
    conflicts:['Sources disagree'],receipts:[{name:'Bad',url:'javascript:alert(1)'},
      {name:'Organizer',url:'https://example.org/event?a=1&b=2'}]});
  assert.doesNotMatch(card, /href="javascript|<img/);
  assert.match(card, /https:\/\/example.org\/event/);
  assert.match(card, /not seen on latest check/);
  assert.match(card, /Schedule needs confirmation/);
});
