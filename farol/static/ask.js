"use strict";
function createRideEdgeAsk({demo=false, onContext=()=>{}, onAnswer=()=>{}}={}, env=window) {
  const doc=env.document, $ = id => doc.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[ch]);
  const time = value => value ? new Date(value).toLocaleTimeString('en-US',{timeZone:'America/Los_Angeles',hour:'numeric',minute:'2-digit'}) : 'Unknown';
  let context, result, lastAnswer, step=0, serial=0, area='bellevue_core';
  const say = text => { $('ask-status').textContent=text; };
  const constraints = () => ({minutes_available:Number($('ask-minutes').value), reposition_under_minutes:Number($('ask-limit').value), finish_near:$('ask-finish').value});
  const setConstraints = value => { $('ask-minutes').value=value.minutes_available; $('ask-limit').value=value.reposition_under_minutes; $('ask-finish').value=value.finish_near; };
  async function fetchJson(url, options) {
    const response=await env.fetch(url,options), body=await response.json();
    if (!response.ok) throw new Error(body.detail && typeof body.detail==='string' ? body.detail : 'Check the inputs and try again.');
    return body;
  }
  const post = (url,body) => fetchJson(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  function invalidate() { serial++; lastAnswer=null; $('ask-answer').textContent=''; $('ask-answer-state').textContent='Python comparison'; $('ask-explanation').innerHTML=''; $('ask-execution').textContent='No local-model request for this comparison yet.'; $('ask-export').disabled=true; }
  function evidenceHtml(ids) { return ids.map(id=>`<a href="#evidence-${escape(id)}" class="evidence-link" data-evidence="${escape(id)}">Source</a>`).join(' '); }
  function bindEvidence(container) {
    container.querySelectorAll('[data-evidence]').forEach(link=>link.addEventListener('click',event=>{
      event.preventDefault(); $('ask-evidence').open=true;
      // Source links must not change #working or invalidate the answer being inspected.
      doc.getElementById('evidence-'+link.dataset.evidence)?.scrollIntoView({block:'start'});
    }));
  }
  function render(comparison) {
    result=comparison;
    $('ask-summary').textContent=comparison.answer;
    $('ask-deadline').textContent=`From ${context.origin} · finish window ${time(comparison.deadline)}`;
    $('ask-options').innerHTML=comparison.options.map(option=>`<article class="compact-card ${option.eligible?'':'subdued'}"><div class="card-top"><h3>${escape(option.area)}</h3><span class="pill">${option.eligible?'Qualifies':'Excluded'}</span></div><p>${escape(option.venue || 'Area window')}</p><p class="card-meta">${option.route_minutes==null?'Current route unknown':escape(option.route_minutes)+' min · '+escape(option.route_status)} · ${escape(time(option.starts_at))}–${escape(time(option.ends_at))}</p><p>${escape(option.reasons.join(' '))}</p><details><summary>Evidence</summary><p class="quiet-note">Score ${escape(option.score)} · heuristic, not earnings. Route checked ${escape(time(option.route_observed_at))}.</p>${evidenceHtml(option.evidence_ids)}</details></article>`).join('') || '<p class="empty-state">No comparison windows in this snapshot.</p>';
    $('ask-sources').innerHTML=context.evidence.map(row=>`<article id="evidence-${escape(row.id)}" class="compact-card"><strong>${escape(row.text)}</strong><small>${escape(row.synthetic?'Synthetic source':row.source)} · ${escape(time(row.observed_at))}</small><small>${escape(row.id)}</small></article>`).join('');
    $('ask-changes').innerHTML=(comparison.changes || context.changes).slice(0,1).map(change=>`<div class="change-pair"><span>Before<strong>${escape(change.before)}</strong></span><span>Now<strong>${escape(change.now)}</strong></span></div><p>${escape(change.why)}</p>${evidenceHtml(change.evidence_ids)}`).join('') || '<p>No meaningful changes in this comparison yet.</p>';
    $('ask-limits').textContent=comparison.limits;
    $('ask-snapshot').textContent=`${context.label} · ${context.snapshot_id} · ${time(context.as_of)} Pacific`;
    $('ask-path').textContent=`Phone → ${env.location?.protocol==='https:'?'HTTPS connection':'HTTP (use secure link on phone)'} → application → cached data + local Qwen. External API collection → local cache (separate background activity).`;
    bindEvidence($('ask-panel'));
    onContext(context,comparison);
  }
  async function refresh() {
    invalidate(); context=null; const token=serial; say('Reading this comparison…');
    if (!demo && !area) { say('Choose a location in Working before comparing areas.'); return; }
    try {
      const body=await fetchJson(`/api/ask/context?mode=${demo?'demo':'live'}&step=${step}&area=${encodeURIComponent(area)}`);
      if (token!==serial) return;
      context=body.context;
      const comparison=await post('/api/ask/compare',{snapshot_id:context.snapshot_id,constraints:constraints()});
      if (token!==serial) return;
      render(comparison); say(demo?'Simulated inputs · real Python calculations':'Reads saved city observations. Missing cached routes stay unknown.');
    } catch(error) { if (token===serial) say(error.message); }
  }
  async function recompute() {
    invalidate(); const token=serial;
    if (!context) return refresh();
    try {
      const comparison=await post('/api/ask/compare',{snapshot_id:context.snapshot_id,constraints:constraints()});
      if (token!==serial) return;
      render(comparison); say('Updated constraints. Python recalculated; no model call.');
    } catch(error) { if (token===serial) say(error.message); }
  }
  async function submit(question=$('ask-question').value, {fresh=false,isCurrent=()=>true}={}) {
    if (!question.trim()) { say('Enter a question first.'); return ''; }
    if (!context) { await refresh(); if (!context || !isCurrent()) return ''; }
    invalidate(); const token=serial, snapshot=context.snapshot_id;
    const current = () => token===serial && snapshot===context?.snapshot_id && isCurrent();
    $('ask-question').value=question; say('Qwen is interpreting your request…');
    try {
      let reply=await post('/api/ask',{snapshot_id:snapshot,question,constraints:constraints(),fresh});
      while (reply.state==='working' && current()) {
        say(reply.detail);
        await new Promise(resolve=>env.setTimeout(resolve,1800));
        if (!current()) return '';
        reply=await fetchJson(`/api/ask/jobs/${encodeURIComponent(reply.request_id)}`);
      }
      if (!current()) return '';
      if (reply.state!=='ready') { say(reply.detail); return ''; }
      lastAnswer=reply; setConstraints(reply.comparison.constraints); render(reply.comparison);
      $('ask-answer').textContent=reply.answer;
      $('ask-answer-state').textContent=reply.answer_state;
      $('ask-explanation').innerHTML=reply.explanation.map(row=>`<p>${escape(row.text)} ${evidenceHtml(row.evidence_ids)}</p>`).join('');
      bindEvidence($('ask-explanation'));
      $('ask-execution').textContent=JSON.stringify({model:reply.model,model_verified:reply.model_verified,answer_state:reply.answer_state,original_inference_time:reply.generated_at,interpretation:reply.interpretation,execution:reply.execution},null,2);
      $('ask-export').disabled=!demo;
      say(`${reply.answer_state} · ${reply.execution.generation_seconds}s original generation`);
      onAnswer(reply); return reply.answer;
    } catch(error) { if (current()) say(error.message); return ''; }
  }
  $('ask-form').addEventListener('submit',event=>{event.preventDefault();submit();});
  $('ask-fresh').addEventListener('click',()=>submit(undefined,{fresh:true}));
  $('ask-refresh').addEventListener('click',refresh);
  $('ask-apply').addEventListener('click',recompute);
  for (const id of ['ask-minutes','ask-limit','ask-finish']) $(id).addEventListener('change',recompute);
  doc.querySelectorAll('[data-ask]').forEach(button=>button.addEventListener('click',()=>submit(button.dataset.ask)));
  $('ask-panel').addEventListener('toggle',()=>{if ($('ask-panel').open && !context) refresh();});
  $('demo-advance').addEventListener('click',()=>{step=Math.min(2,step+1); $('demo-advance').disabled=step===2; refresh();});
  $('demo-reset').addEventListener('click',()=>{step=0; $('demo-advance').disabled=false; setConstraints({minutes_available:90,reposition_under_minutes:15,finish_near:'kirkland_waterfront'}); refresh();});
  $('demo-evidence').addEventListener('click',async()=>{
    try {$('demo-api-evidence').textContent=JSON.stringify(await fetchJson('/api/demo/evidence'),null,2);} catch(error) {say(error.message);}
  });
  $('ask-usage').addEventListener('click',async()=>{
    try {$('ask-usage-detail').textContent=JSON.stringify(await fetchJson('/api/usage'),null,2);} catch(error) {say(error.message);}
  });
  $('ask-export').addEventListener('click',()=>{
    if (!demo || !lastAnswer) return;
    const blob=new Blob([JSON.stringify({context,question:$('ask-question').value,result:lastAnswer,exported_at:new Date().toISOString()},null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob), link=doc.createElement('a'); link.href=url; link.download=`rideedge-${context.scenario_id}-step-${step}.json`; link.click(); env.setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  env.addEventListener('hashchange',invalidate);
  doc.addEventListener('visibilitychange',()=>{if(doc.hidden) serial++;});
  $('demo-drawer').classList.toggle('hidden',!demo);
  if (demo) { $('ask-panel').open=true; refresh(); }
  return {submit, refresh, cancel:invalidate, answer:()=>lastAnswer?.answer || result?.answer || '',
    clearArea() {
      if (demo) return;
      area=null; context=null; result=null; invalidate();
      for (const id of ['ask-summary','ask-deadline','ask-snapshot','ask-options','ask-sources','ask-changes']) $(id).textContent='';
      say('Choose a location in Working before comparing areas.');
    },
    setArea(value) { if (area!==value) {area=value; context=null; invalidate(); if ($('ask-panel').open) refresh();} }};
}
if (typeof window!=='undefined') window.createRideEdgeAsk=createRideEdgeAsk;
if (typeof module!=='undefined') module.exports={createRideEdgeAsk};
