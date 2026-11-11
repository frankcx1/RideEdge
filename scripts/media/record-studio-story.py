"""Record the simplified Studio with actual read-only status; no collection/inference."""
from pathlib import Path
from datetime import datetime,UTC
from contextlib import closing
import hashlib,json,sqlite3,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from farol.access import AccessPolicy
from farol.browser_access import BrowserAccess
from playwright.sync_api import sync_playwright
OUT=ROOT/'recordings/podcast/edit-v2/dashboard'
OUT.mkdir(parents=True,exist_ok=True)
policy=AccessPolicy();store=BrowserAccess(policy.path);token=store.issue(policy.digest(),policy.origin)
source=(ROOT/'farol/static/studio-story.html').read_text(encoding='utf-8')
errors=[];requests=[]
try:
 with sync_playwright() as pw:
    browser=pw.chromium.launch()
    context=browser.new_context(viewport={'width':1920,'height':1080},device_scale_factor=1)
    response=context.request.post(policy.origin+'/auth/login',data={'token':token},headers={'Origin':policy.origin})
    assert response.ok,'Browser sign-in failed'
    response=context.request.get(policy.origin+'/api/studio?mode=live');assert response.ok
    raw=response.json()
    rawdir=ROOT/'.cache/qa/studio-story';rawdir.mkdir(parents=True,exist_ok=True)
    rawfile=rawdir/(datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'-raw.json')
    rawfile.write_text(json.dumps(raw,indent=2),encoding='utf-8')
    # Export only fields this presentation needs; retain the original response locally.
    runtime=raw.get('runtime') or {}
    d={'mode':'live','observed_at':raw.get('observed_at'),'health':{'feeds':[
        {k:f.get(k) for k in ('adapter','healthy')} for f in (raw.get('health') or {}).get('feeds',[])]},
       'besttime':{'enabled':(raw.get('besttime') or {}).get('enabled')},
       'runtime':{'model':{'state':(runtime.get('model') or {}).get('state')},
         'scheduler':{'last_evidence_at':(runtime.get('scheduler') or {}).get('last_evidence_at')},
         'performance':{'samples':[{'observed_at':p.get('observed_at')} for p in (runtime.get('performance') or {}).get('samples',[])[:1]]}},
       'decision':{'generated_at':(raw.get('decision') or {}).get('generated_at')}}
    (OUT/'recorded-status.json').write_text(json.dumps(d,indent=2),encoding='utf-8')
    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:requests.append(r.url.split('?')[0].split('/')[-1]))
    page.route('**/studio/story?*',lambda route:route.fulfill(status=200,content_type='text/html',body=source))
    page.route('**/api/studio?*',lambda route:route.fulfill(json=d))
    page.goto(policy.origin+'/studio/story?clean=1');page.wait_for_function('window.RideEdgeStory !== undefined')
    page.evaluate('(d)=>RideEdgeStory.setSnapshot(d)',d)
    cues=page.evaluate('RideEdgeStory.cues');receipts=[]
    for i,cue in enumerate(cues):
        page.evaluate('(id)=>RideEdgeStory.draw(id)',cue['id']);page.screenshot(path=str(OUT/(cue['id']+'.png')))
        bounds=page.evaluate('''() => [...document.querySelectorAll('#scene h1,#scene .card,#scene .caption,#scene .cycle,#scene .uncertain')].map(e=>{const b=e.getBoundingClientRect();return {tag:e.tagName,bottom:b.bottom,right:b.right,left:b.left}})''')
        assert all(b['bottom']<980 and b['right']<=1920 and b['left']>=0 for b in bounds),(cue,bounds)
        receipts.append({'cue':cue['id'],'bounds':bounds})
    # Missing/offline data must never turn into a ready or healthy assertion.
    page.evaluate('RideEdgeStory.setSnapshot(null);RideEdgeStory.draw("status")')
    assert 'Not observed' in page.locator('#scene').inner_text()
    page.evaluate('RideEdgeStory.draw("availability")')
    assert page.locator('.pill').all_text_contents()==['Not observed']*4
    page.evaluate('(d)=>RideEdgeStory.setSnapshot(d)',d)
    page.evaluate('document.body.classList.remove("clean")')
    page.get_by_role('button',name='Review again',exact=True).click()
    assert '10' in page.locator('.clock').inner_text()
    for width in (1280,800):
        page.set_viewport_size({'width':width,'height':900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors,errors
    browser.close()
    # Self-contained review copy: the same UI with explicitly dated server observations.
    snapshot_js=json.dumps(d).replace('<','\\u003c')
    offline="$('refresh').disabled=true;$('mode').disabled=true;$('mode').options[0].text='Recorded server snapshot';"
    offline+=f"document.querySelector('a[href=\"/studio\"]').href={json.dumps(policy.origin+'/studio')};"
    preview=source.replace("if(location.protocol!=='file:')refresh();",f"RideEdgeStory.setSnapshot({snapshot_js});"+offline)
    (OUT/'RideEdge-dashboard-presentation.html').write_text(preview,encoding='utf-8')
    fps=30;duration=860/fps
    for i,cue in enumerate(cues):
        end=cues[i+1]['at'] if i+1<len(cues) else duration
        frames=round(end*fps)-round(cue['at']*fps)
        args=['ffmpeg','-hide_banner','-y','-loop','1','-framerate','30','-i',str(OUT/(cue['id']+'.png')),
          '-frames:v',str(frames),'-vf','format=yuv420p','-c:v','libx264','-preset','fast','-crf','16','-threads','4',
          '-video_track_timescale','15360','-an',str(OUT/(cue['id']+'.mp4'))]
        with (OUT/(cue['id']+'.log')).open('w') as log:subprocess.run(args,check=True,stdout=log,stderr=log)
        cue['frames']=frames;print('Rendered '+cue['id'],flush=True)
    (OUT/'concat.txt').write_text(''.join(f"file '{(OUT/(c['id']+'.mp4')).as_posix()}'\n" for c in cues),encoding='utf-8')
    subprocess.run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(OUT/'concat.txt'),'-c','copy','-movflags','+faststart',str(OUT/'dashboard-story.mp4')],check=True)
    (OUT/'capture.json').write_text(json.dumps({'cues':cues,'observed_at':d['observed_at'],'raw_provenance':str(rawfile.relative_to(ROOT)),
        'javascript_errors':errors,'layout_checks':receipts,'requests':requests,'note':'Actual read-only server observations. No collection, refresh of paid providers or inference. Scene changes are narration cues, not live model progress.'},indent=2),encoding='utf-8')
    print('COMPLETE',flush=True)
finally:
 with closing(sqlite3.connect(store.path)) as db,db:
    db.execute('DELETE FROM sessions WHERE digest=?',(hashlib.sha256(token.encode()).hexdigest(),))
