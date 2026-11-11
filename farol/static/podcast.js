"use strict";
const Podcast = (() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[ch]);
  const clock = seconds => `${Math.floor(Math.max(0,seconds)/60)}:${String(Math.floor(Math.max(0,seconds)%60)).padStart(2,"0")}`;
  const stamp = value => value ? new Date(value).toLocaleString("en-US",{timeZone:"America/Los_Angeles",month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}) : "Time unavailable";
  const cueAt = (cues, time) => Math.max(0,cues.findLastIndex(cue => cue.at <= time));
  function estimates(plan, duration) { return plan.cues.map((cue,i) => ({...cue,at:i ? Math.round(cue.fraction*duration*10)/10 : 0})); }
  function timingValid(cues,duration) {
    return Number.isFinite(duration) && duration>=30 && duration<=7200 && cues.length>0 && cues[0].at===0
      && cues.every((cue,i) => Number.isFinite(cue.at) && cue.at>=0 && cue.at<duration && (!i || cue.at>cues[i-1].at));
  }
  function importTiming(saved,plan) {
    if (saved.version!==1 || saved.cues?.length!==plan.cues.length || !Number.isFinite(saved.segment_start) || saved.segment_start<0) throw Error("This timing file does not match the transcript.");
    const cues=plan.cues.map((cue,i) => {
      if (cue.id!==saved.cues[i]?.id) throw Error("The timing file has a different cue order.");
      return {...cue,at:saved.cues[i].at};
    });
    if (!timingValid(cues,saved.duration)) throw Error("Cue times must increase and fit within the segment.");
    return {cues,duration:saved.duration,segment_start:saved.segment_start,reviewed:saved.reviewed===true};
  }
  function optionCards(comparison) {
    return `<div class="grid three">${comparison.options.map(row => `<article class="card ${row.id===comparison.best_id?'best':row.eligible?'':'dim'}"><span class="pill ${row.eligible?'':'warn'}">${row.id===comparison.best_id?'Top qualifying option':row.eligible?'Within your limits':'Outside your limits'}</span><h2>${escape(row.area)}</h2><p class="meta">${escape(row.venue)}</p><div class="number">${row.route_minutes==null?'?':escape(row.route_minutes)} <span>min</span></div><p>${escape(row.reasons.join(' '))}</p></article>`).join('')}</div>`;
  }
  function eventCard(row) {
    const when=row.date_only?'Hours unconfirmed':row.end_unknown?'End time unconfirmed':stamp(row.window_starts_at);
    return `<article class="card"><span class="pill">${escape(row.community_event?'Community calendar':'Event window')}</span><h3>${escape(row.title)}</h3><p>${escape(row.location_label || row.zone_labels?.join(' · ') || 'Area unconfirmed')}</p><p class="meta">${escape(when)}</p><div class="source-line">${escape(row.source)} · ${escape(row.freshness)}${row.conflicts?.length?' · schedule needs confirmation':''}</div></article>`;
  }
  function scene(view, data, cueId) {
    const {plan,nearby,metro,scope='nearby'}=data, comparison=plan.states[view==='changed'?1:0].comparison;
    const heads=(tag,title,description='') => `<p class="kicker">${tag}</p><h1>${title}</h1>${description?`<p class="lede">${description}</p>`:''}`;
    const badge='Illustrated explanation';
    if (view==='intro') return {badge,mode:'decide',html:heads('A LOCAL AI EXPERIMENT','Where should I go next?','A Seattle driver’s question. A computer at home. An app in the car.')+`<div class="hero"><p class="statement">Better context for the next decision.</p><p>Events. Places. Access. Your own preferences.</p></div><div class="grid three top-space"><div class="card"><h2>Should I drive?</h2><p>Is there a window worth a look?</p></div><div class="card"><h2>Working</h2><p>Compare where to go next.</p></div><div class="card"><h2>Around you</h2><p>Explore nearby and across the metro.</p></div></div>`};
    if (view==='hotspots') return {badge:'Illustration · driver hypothesis',mode:'working',html:heads('THE PROBLEM','Everyone sees the same hotspot.','By the time you arrive, other drivers have arrived too.')+`<div class="city-map"><span class="water">LAKE WASHINGTON</span><span class="city seattle">Seattle</span><span class="city bellevue">Bellevue</span><span class="city kirkland">Kirkland</span><span class="cars">▰ ▰ ▰ ▰ ▰</span></div><div class="callout">What else is happening nearby—and can I get in and out?</div><p class="meta">Concept illustration. RideEdge cannot see competing drivers or unrequested rides.</p>`};
    if (view==='sources') return {badge:'How the app collects context',mode:'around',html:heads('CITY DATA → workstation',cueId==='collect'?'workstation puts the pieces together.':'A city full of useful signals.','Public feeds and selected APIs collect into a local cache.')+`<div class="grid three"><article class="card"><span class="pill">Events</span><h2>Shows &amp; festivals</h2><p>Ticketmaster<br>Community calendars<br>Venue schedules</p></article><article class="card"><span class="pill">Places</span><h2>Restaurants &amp; nightlife</h2><p>Google place hours<br>BestTime activity estimates<br>Typical venue patterns</p></article><article class="card"><span class="pill">Access</span><h2>Getting there</h2><p>Road &amp; transit alerts<br>Weather forecasts<br>Airport arrivals</p></article></div><div class="callout">Different sources, different refresh times. Every observation needs context.</div>`};
    if (view==='around') {
      const selected=scope==='metro'?metro:nearby, events=(selected?.observations||[]).filter(row=>row.layer==='events');
      const rows=[...events].sort((a,b)=>Number(Boolean(b.community_event))-Number(Boolean(a.community_event))).slice(0,3);
      const venues=(selected?.venue_activity||[]).slice(0,2);
      return {badge:selected?.demo?'Demo feeds':selected?'Collected snapshot':'Feeds unavailable',mode:'around',note:selected?`Saved feed snapshot · ${stamp(selected.snapshot?.collected_at)}`:'No replacement facts invented',html:heads('AROUND YOU',scope==='metro'?'Across greater Seattle.':'Within about five miles of Seattle.','Events and places first. Traffic is available when you need it.')+`<div class="scope-controls"><button data-scope="nearby" class="${scope==='nearby'?'selected':''}">Nearby · Seattle</button><button data-scope="metro" class="${scope==='metro'?'selected':''}">Metro · Seattle &amp; Eastside</button><span class="meta">Next 7 days · saved calendar</span></div><div class="grid three">${rows.map(eventCard).join('') || '<article class="card"><h2>No matching events in this saved view</h2><p>Missing coverage does not mean the area is quiet.</p></article>'}</div><div class="callout">${venues.length?venues.map(row=>`${escape(row.name)} · ${row.live_recent?'recent activity reading':'typical pattern; live unknown'}`).join(' &nbsp; / &nbsp; '):'Venue activity estimates add context. They are not rider counts.'}</div>`};
    }
    if (view==='working' || view==='changed') return {badge:'Simulated conditions · real calculations',mode:'working',note:'September 19, 2026 · fictional evening · not a rider-demand forecast',html:heads('WORKING',view==='changed'?'A changed route changes the answer.':'Compare the options against my limits.',view==='changed'?'Bellevue’s drive changes from 8 to 22 minutes. Kirkland stays at 14.':'90 minutes available · reposition under 15 minutes · prefer to finish near Kirkland')+optionCards(comparison)+`<div class="callout"><b>${escape(comparison.answer)}</b> &nbsp; Python checks the route limits and scores.</div><p class="meta">Qwen interprets preferences and helps explain checked evidence. Staying put remains an option.</p>`};
    if (view==='models') return {badge:'Workload-specific comparison',mode:'working',html:heads('CHOOSING A LOCAL MODEL',cueId==='qwen'?'For this app, I chose Qwen.':'Speed is one part of the decision.','presenter’s reported generation speeds on workstation; not universal model benchmarks.')+`<div class="grid two">${[['gemma','Gemma','~120'],['qwen','Qwen','~40']].map(([key,name,speed])=>{const check=plan.model_checks.find(row=>row.profile===key);return `<article class="card ${cueId===key?'best':''}"><h2>${name}</h2><div class="number">${speed} <span>tokens / second</span></div><p>${key==='gemma'?'Faster generation in presenter’s benchmark.':'Preferred for this app’s tested behavior.'}</p>${check?`<div class="metric-line"><span>App response checks</span><strong>${check.passed} / ${check.total}</strong></div><p class="meta">Before guardrails · September 18 tests<br>${check.guarded_passed}/${check.total} passed after guardrails</p>`:''}</article>`;}).join('')}</div><p class="meta">Different model variants and generation settings. These checks do not measure real driving earnings.</p>`};
    if (view==='tuning') return {badge:'Model comparison context',mode:'working',html:heads('CO-HOST’S POINT','The model name is only the beginning.','Results depend on the workload and how the model is configured.')+`<div class="grid two"><article class="card"><h2>Model variant</h2><p>Size, architecture, and distillation.</p></article><article class="card"><h2>Quantization</h2><p>Memory savings can affect results.</p></article><article class="card"><h2>Reasoning settings</h2><p>Budget, limits, and generation time.</p></article><article class="card"><h2>Prompt &amp; sampling</h2><p>Instructions, temperature, and the task.</p></article></div><div class="callout">“Better for my app, with these settings.”</div>`};
    if (view==='architecture') return {badge:'Current app architecture',mode:'working',html:heads('LOCAL AI, REMOTE ACCESS','The phone is the interface. workstation does the work.','Private HTTPS access through Tailscale.')+`<div class="path-row"><div class="path-box"><span class="pill">Pixel / browser</span><h2>RideEdge</h2><p>Location, preferences,<br>questions, and voice.</p></div><span class="arrow">↔</span><div class="path-box"><span class="pill">Private connection</span><h2>Tailscale + HTTPS</h2><p>Connect the phone<br>to the app at home.</p></div><span class="arrow">↔</span><div class="path-box"><span class="pill">workstation</span><h2>Python + local Qwen</h2><p>Checked calculations.<br>Preference interpretation.<br>Evidence explanations.</p></div></div><div class="callout">City APIs → collector → local cache → app tools and model</div><p class="meta">No cloud-model token bill for local Qwen. Data APIs, hardware, and power still have costs.</p>`};
    if (view==='airport') {
      const row=metro?.observations?.find(item=>item.kind==='airport_arrivals');
      return {badge:row?'Collected airport observation':'Airport capability',mode:'around',html:heads('SEA–TAC ARRIVALS','Another piece of the city’s rhythm.','FlightAware provides arrivals context when the airport view is requested.')+`<div class="grid two"><article class="card best"><span class="pill">Arrivals</span><h2>${escape(row?.title || 'Flight arrival windows')}</h2><p>${escape(row?.detail || 'The app can look for groups of arriving flights.')}</p><p class="meta">${row?escape(`${row.freshness} · ${stamp(row.fetched_at)}`):'No recent airport arrival example in this saved snapshot.'}</p></article><article class="card"><span class="pill warn">Unknown</span><h2>The driver queue</h2><p>Arrivals do not tell us how many drivers are waiting—or guarantee a pickup.</p></article></div><div class="callout">A useful signal, with its limits visible.</div>`};
    }
    if (view==='transit') return {badge:'Transit capability · occupancy unknown',mode:'around',html:heads('TRANSIT & ACCESS','What could change the trip home?','Service disruptions can matter around a stadium or a busy neighborhood.')+`<div class="grid two"><article class="card"><span class="pill">OneBusAway</span><h2>Service alerts</h2><p>Link delays, suspensions, and other relevant disruptions add context.</p></article><article class="card"><span class="pill warn">Not measured</span><h2>Train crowding</h2><p>The current app does not know how many passengers are on a train.</p></article></div><div class="callout">A reason to investigate an area—not proof of waiting riders.</div>`};
    return {badge:'Real-world results still to be tested',mode:'decide',html:heads('THE EXPERIMENT CONTINUES','Does better context lead to better decisions?')+`<div class="hero"><p class="statement">“Whether it’s valuable,<br>I don’t know yet.”</p><p>Try it on real shifts. Compare the suggestions with what actually happens.</p></div><div class="grid three top-space"><div class="card"><h2>Observe</h2><p>What is happening around me?</p></div><div class="card"><h2>Decide</h2><p>Is a move worth considering?</p></div><div class="card"><h2>Learn</h2><p>Did the context help?</p></div></div>`};
  }
  return {escape,clock,stamp,cueAt,estimates,timingValid,importTiming,optionCards,eventCard,scene};
})();

async function initPodcast() {
  const $=id=>document.getElementById(id), media=$('source-media');
  let plan,cues=[],duration=300,segmentStart=0,time=0,playing=false,reviewed=false,lastTick=0,current=-1,lastScope='',manualScope=null,mediaURL=null,nearby=null,metro=null;
  const fail=message=>{ $('error').textContent=message; $('error').hidden=!message; };
  const request=async url=>{const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw Error('Could not load '+url.split('?')[0]);return r.json();};
  function fit() { const box=$('capture').getBoundingClientRect(),scale=Math.min(box.width/1920,box.height/1080);$('stage').style.transform=`scale(${scale})`;$('stage-wrap').style.width=`${1920*scale}px`;$('stage-wrap').style.height=`${1080*scale}px`; }
  function timingState() { $('timing-state').textContent=reviewed?'Cue timing reviewed':'Estimated / unreviewed timing · align to the recording'; }
  function draw(force=false) {
    if(!plan)return;
    const index=Podcast.cueAt(cues,time),cue=cues[index],end=cues[index+1]?.at??duration;
    if(index!==current)manualScope=null;
    const scope=manualScope || (time>cue.at+(end-cue.at)/2?'metro':'nearby');
    if(force || index!==current || cue.view==='around'&&scope!==lastScope) {
      current=index;lastScope=scope;
      const s=Podcast.scene(cue.view,{plan,nearby,metro,scope},cue.id);
      $('scene').innerHTML=s.html;$('scene').className=['around','airport','models'].includes(cue.view)?'scene-small':'';
      $('source-badge').textContent=s.badge;$('scene-note').textContent=s.note||'Seattle & the Eastside · context, not guaranteed demand';
      for(const mode of ['decide','working','around'])$('mode-'+mode).classList.toggle('active',s.mode===mode);
      $('scene-count').textContent=`${String(index+1).padStart(2,'0')} / ${cues.length}`;
      $('cue-title').textContent=cue.title;$('cue-quote').textContent='“'+cue.quote+'…”';
      $('back').disabled=index===0;$('next').disabled=index===cues.length-1;
    }
    $('clock').textContent=`${Podcast.clock(time)} / ${Podcast.clock(duration)}`;$('scrub').value=time;
  }
  function pause() {playing=false;media.pause();$('play').textContent='Play visuals';}
  function seek(value) {time=Math.max(0,Math.min(duration,value));if(mediaURL)media.currentTime=segmentStart+time;lastTick=performance.now();manualScope=null;draw(true);}
  function mediaFits() {return !mediaURL || Number.isFinite(media.duration)&&segmentStart+duration<=media.duration+.15;}
  async function play() {
    if(playing){pause();return;}if(!mediaFits()){fail('The selected segment extends beyond this recording. Check start and duration.');return;}
    if(time>=duration)seek(0);fail('');
    if(mediaURL){media.currentTime=segmentStart+time;media.muted=$('muted').checked;try{await media.play();}catch{fail('Could not play this media file. Try a browser-supported audio or video format.');return;}}
    playing=true;lastTick=performance.now();$('play').textContent='Pause';
  }
  function tick(now) {
    if(playing){time=mediaURL?media.currentTime-segmentStart:time+(now-lastTick)/1000;time=Math.max(0,time);if(time>=duration){time=duration;pause();}draw();}
    lastTick=now;requestAnimationFrame(tick);
  }
  function editor() {
    $('cue-editor').innerHTML=cues.map((cue,i)=>`<div class="cue-edit-row"><strong>${Podcast.escape(cue.title)}</strong><blockquote>${Podcast.escape(cue.quote)}</blockquote><input aria-label="Cue ${i+1} seconds" type="number" min="0" max="${duration}" step="0.1" data-time="${i}" value="${cue.at}" ${i===0?'disabled':''}><button data-mark="${i}" ${i===0?'disabled':''}>Set now</button></div>`).join('');timingState();
  }
  function changeCue(index,at) {const updated=cues.map((cue,i)=>({...cue,at:i===index?at:cue.at}));if(!Podcast.timingValid(updated,duration)){fail('Cue times must stay in transcript order and inside the segment.');editor();return;}cues=updated;reviewed=false;fail('');editor();draw(true);}
  async function collected() {
    $('reload-data').disabled=true;
    try {
      const results=await Promise.allSettled([request('/api/awareness?scope=nearby&area=seattle_core&period=week'),request('/api/awareness?scope=metro&period=week')]);
      nearby=results[0].status==='fulfilled'?results[0].value:null;metro=results[1].status==='fulfilled'?results[1].value:null;
      $('data-status').textContent=nearby&&metro?'Collected examples loaded and held steady for this take. Original source times stay visible.':'Some collected examples are unavailable. The simulated comparison still works.';
      draw(true);
    } finally {$('reload-data').disabled=false;}
  }
  try{plan=await request('/api/podcast');cues=Podcast.estimates(plan,duration);if(!Podcast.timingValid(cues,duration))throw Error('The transcript cue order is invalid.');}
  catch(error){fail(error.message);$('scene').innerHTML='<h1>Recording setup unavailable</h1><p>Check the app connection and transcript file, then reload.</p>';return;}
  $('play').addEventListener('click',play);$('back').addEventListener('click',()=>seek(cues[Math.max(0,current-1)].at));$('next').addEventListener('click',()=>seek(cues[Math.min(cues.length-1,current+1)].at));
  $('reset').addEventListener('click',()=>{pause();seek(0);});$('scrub').addEventListener('input',event=>seek(Number(event.target.value)));
  $('clean').addEventListener('click',()=>{document.body.classList.toggle('clean');$('clean').blur();fit();});
  async function fullscreen(){try{if(document.fullscreenElement)await document.exitFullscreen();else {await $('capture').requestFullscreen();$('fullscreen').blur();}}catch{fail('Fullscreen unavailable. Use the browser’s F11 shortcut.');}}
  $('fullscreen').addEventListener('click',fullscreen);document.addEventListener('fullscreenchange',fit);
  $('setup-toggle').addEventListener('click',()=>{$('setup').open=!$('setup').open;$('setup-toggle').setAttribute('aria-expanded',String($('setup').open));fit();});$('setup').addEventListener('toggle',fit);
  $('muted').addEventListener('change',()=>media.muted=$('muted').checked);
  $('media-file').addEventListener('change',event=>{const file=event.target.files[0];if(!file)return;pause();if(mediaURL)URL.revokeObjectURL(mediaURL);mediaURL=URL.createObjectURL(file);media.src=mediaURL;reviewed=false;timingState();$('media-status').textContent='Loading local recording…';});
  media.addEventListener('loadedmetadata',()=>{$('media-status').textContent=`Local recording: ${Podcast.clock(media.duration)}. Set the segment start and duration, then align each phrase below.`;seek(0);if(!mediaFits())fail('Set the segment duration to fit inside the loaded recording.');});
  media.addEventListener('error',()=>{pause();fail('This recording could not be decoded. Try an MP4, WebM, MP3, or WAV supported by this browser.');});media.addEventListener('ended',()=>{pause();draw();});
  function updateSegment(){pause();const d=Number($('duration').value),s=Number($('segment-start').value);if(!Number.isFinite(d)||d<30||d>7200||!Number.isFinite(s)||s<0){fail('Use a duration from 30 to 7200 seconds and a nonnegative start.');return;}const next=cues.map(cue=>({...cue,at:Math.round(cue.at*d/duration*10)/10}));if(!Podcast.timingValid(next,d)){fail('These settings put cue times too close together.');return;}duration=d;segmentStart=s;cues=next;reviewed=false;$('scrub').max=duration;editor();seek(0);fail(mediaFits()?'':'This segment extends beyond the recording.');}
  $('duration').addEventListener('change',updateSegment);$('segment-start').addEventListener('change',updateSegment);
  $('cue-editor').addEventListener('change',event=>{if(event.target.dataset.time!==undefined)changeCue(Number(event.target.dataset.time),Number(event.target.value));});
  $('cue-editor').addEventListener('click',event=>{if(event.target.dataset.mark!==undefined)changeCue(Number(event.target.dataset.mark),Math.round(time*10)/10);});
  $('confirm-timing').addEventListener('click',()=>{
    const edited=cues.map((cue,i)=>({...cue,at:Number(document.querySelector(`[data-time="${i}"]`).value)}));
    if(!Podcast.timingValid(edited,duration)){fail('Cue times must stay in transcript order and inside the segment.');return;}
    cues=edited;reviewed=true;fail('');editor();draw(true);
  });
  $('estimate').addEventListener('click',()=>{cues=Podcast.estimates(plan,duration);reviewed=false;editor();draw(true);});
  $('save-timing').addEventListener('click',()=>{const blob=new Blob([JSON.stringify({version:1,duration,segment_start:segmentStart,reviewed,cues:cues.map(({id,at})=>({id,at}))},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='rideedge-podcast-timing.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  $('load-timing').addEventListener('change',async event=>{const file=event.target.files[0];if(!file)return;try{const saved=Podcast.importTiming(JSON.parse(await file.text()),plan);pause();({cues,duration,reviewed}=saved);segmentStart=saved.segment_start;$('duration').value=duration;$('segment-start').value=segmentStart;$('scrub').max=duration;editor();seek(0);fail('');}catch(error){fail(error.message);}});
  $('reload-data').addEventListener('click',collected);
  $('scene').addEventListener('click',event=>{if(event.target.dataset.scope){manualScope=event.target.dataset.scope;draw(true);}});
  document.addEventListener('keydown',event=>{
    if(['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName)||event.ctrlKey||event.altKey||event.metaKey)return;
    if(event.code==='Space'&&['BUTTON','A','SUMMARY'].includes(event.target.tagName))return;
    if(event.code==='Space'){event.preventDefault();play();}else if(event.key==='ArrowRight'){event.preventDefault();seek(cues[Math.min(cues.length-1,current+1)].at);}else if(event.key==='ArrowLeft'){event.preventDefault();seek(cues[Math.max(0,current-1)].at);}else if(event.key.toLowerCase()==='h'){document.body.classList.toggle('clean');fit();}else if(event.key.toLowerCase()==='f'){fullscreen();}else if(event.key==='Escape'){document.body.classList.remove('clean');fit();}
  });
  // Pause when switching away; the media clock is authoritative when a recording is loaded.
  document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
  window.addEventListener('resize',fit);new ResizeObserver(fit).observe($('capture'));editor();draw();fit();collected();requestAnimationFrame(tick);
}
if(typeof module!=='undefined')module.exports=Podcast;
if(typeof document!=='undefined')document.addEventListener('DOMContentLoaded',initPodcast);
