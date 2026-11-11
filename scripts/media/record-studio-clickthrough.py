"""Record the actual captured-evaluation dashboard at native 1080p.

No provider refreshes or inference. PNG frame acquisition avoids the browser video
recorder's lossy intermediate. A visible pointer represents actual mouse events.
"""
import asyncio
import hashlib
import json
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from farol.access import AccessPolicy
from farol.browser_access import BrowserAccess
from playwright.async_api import async_playwright

OUT = ROOT/'recordings/rideedge-studio-clickthrough-20261106-take2'
OUT.mkdir(exist_ok=True)
POINTER = """() => {
 const p=document.createElement('div');p.id='recording-pointer';
 p.style.cssText='position:fixed;left:1820px;top:100px;width:22px;height:29px;z-index:2147483647;pointer-events:none;filter:drop-shadow(0 1px 2px #000);';
 p.innerHTML='<svg viewBox="0 0 22 29"><path d="M2 2 L2 24 L8 18 L12 27 L17 24 L12 16 L21 16 Z" fill="white" stroke="#172535" stroke-width="2"/></svg>';
 document.documentElement.appendChild(p);
 document.addEventListener('mousemove',e=>{p.style.left=e.clientX+'px';p.style.top=e.clientY+'px'});
 document.addEventListener('mousedown',()=>{p.style.filter='drop-shadow(0 0 7px #ffb376)'});
 document.addEventListener('mouseup',()=>{p.style.filter='drop-shadow(0 1px 2px #000)'});
 document.body.style.zoom='1.15';
}"""

async def click(page, selector):
    loc=page.locator(selector)
    box=await loc.bounding_box()
    if not box:
        raise RuntimeError('Missing visible control: '+selector)
    await page.mouse.move(box['x']+box['width']/2, box['y']+box['height']/2, steps=12)
    await asyncio.sleep(.2)
    await page.mouse.down();await asyncio.sleep(.12);await page.mouse.up()

async def scroll(page, y):
    await page.evaluate('(y)=>window.scrollTo({top:y,behavior:"smooth"})',y)
    await asyncio.sleep(.85)

async def record(page, key, duration, actions):
    folder=OUT/key;folder.mkdir(exist_ok=True)
    await page.evaluate('window.scrollTo({top:0,behavior:"instant"})')
    await page.mouse.move(1820,100)
    await asyncio.sleep(.3)
    started=time.monotonic();frames=[];previous=None
    async def capture():
        nonlocal previous
        while time.monotonic()-started < duration:
            tick=time.monotonic()
            png=await page.screenshot(type='png',animations='allow')
            stamp=time.monotonic()-started
            digest=hashlib.sha256(png).hexdigest()
            if digest!=previous:
                file=folder/f'{len(frames):05}.png';file.write_bytes(png)
                frames.append({'time':stamp,'file':str(file),'sha256':digest});previous=digest
            await asyncio.sleep(max(0,.1-(time.monotonic()-tick)))
    async def operate():
        for at, op in actions:
            await asyncio.sleep(max(0,started+at-time.monotonic()))
            await op()
    await asyncio.gather(capture(),operate())
    frames[0]['time']=0
    listing=folder/'frames.txt'
    lines=[]
    for i,f in enumerate(frames):
        end=frames[i+1]['time'] if i+1<len(frames) else duration
        lines.extend([f"file '{Path(f['file']).as_posix()}'",f"duration {max(.001,end-f['time']):.6f}"])
    lines.append(f"file '{Path(frames[-1]['file']).as_posix()}'")
    listing.write_text('\n'.join(lines),encoding='utf-8')
    (folder/'frames.json').write_text(json.dumps(frames,indent=2))
    print('Captured '+key+': '+str(len(frames))+' distinct frames',flush=True)
    return dict(key=key,duration_seconds=duration,frames=len(frames))

async def main():
    policy=AccessPolicy();store=BrowserAccess(policy.path)
    token=store.issue(policy.digest(),policy.origin)
    errors=[];shots=[]
    try:
        async with async_playwright() as pw:
            api=await pw.request.new_context(extra_http_headers={'Origin':policy.origin},timeout=30000)
            assert (await api.post(policy.origin+'/auth/login',data={'token':token})).ok
            payload=await (await api.get(policy.origin+'/api/studio?mode=captured')).json()
            assert payload['snapshot_id']=='179771fe99d68e2346e6'
            browser=await pw.chromium.launch()
            context=await browser.new_context(storage_state=await api.storage_state(),viewport={'width':1920,'height':1080},device_scale_factor=1)
            page=await context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            await page.goto(policy.origin+'/studio?mode=captured')
            await page.locator('#badge').filter(has_text='RECORDED EVALUATION').wait_for()
            await page.evaluate(POINTER)
            # Show the intact header before deliberately scrolling into each view.
            shots.append(await record(page,'01-overview',6,[(1.3,lambda:click(page,'[data-tab=architecture]'))]))
            await click(page,'[data-tab=sources]')
            shots.append(await record(page,'02-architecture',25.5,[
                (.7,lambda:click(page,'[data-tab=architecture]')),
                (3.5,lambda:scroll(page,390)),
                (14,lambda:scroll(page,610)),
                (18,lambda:click(page,'#industry')),
                (19,lambda:page.locator('#industry').select_option('delivery'))]))
            shots.append(await record(page,'03-sources',10.5,[
                (.6,lambda:click(page,'[data-tab=sources]')),
                (1.8,lambda:scroll(page,400)),
                (3,lambda:click(page,'#search')),
                (3.5,lambda:page.locator('#search').press_sequentially('BestTime',delay=65)),
                (5,lambda:click(page,'#feedRows button'))]))
            shots.append(await record(page,'04-decision',16.4,[
                (.6,lambda:click(page,'[data-tab=decision]')),
                (2.3,lambda:scroll(page,455)),
                (6,lambda:click(page,'#decision summary')),
                (10.5,lambda:scroll(page,655))]))
            shots.append(await record(page,'05-economics',25.4,[
                (.7,lambda:click(page,'[data-tab=economics]')),
                (2.8,lambda:scroll(page,440)),
                (5,lambda:click(page,'#costMeasured')),
                (12,lambda:click(page,'#costContexts')),
                (13,lambda:page.locator('#costContexts').fill('10')),
                (20,lambda:page.locator('#costContexts').fill('1'))]))
            assert not errors,errors
            await context.close();await browser.close();await api.dispose()
        cursor=0
        for shot in shots:
            shot['offset_seconds']=cursor;cursor+=shot['duration_seconds']
            folder=OUT/shot['key'];target=OUT/(shot['key']+'.mp4')
            with (folder/'encode.log').open('w') as log:
                subprocess.run(['ffmpeg','-hide_banner','-y','-f','concat','-safe','0','-i',str(folder/'frames.txt'),
                    '-t',str(shot['duration_seconds']),'-vf','fps=30,format=yuv420p','-c:v','libx264','-preset','fast','-crf','15','-threads','4','-an',
                    '-video_track_timescale','15360','-movflags','+faststart',str(target)],check=True,stdout=log,stderr=log)
            print('Encoded '+shot['key'],flush=True)
        listing=OUT/'concat.txt';listing.write_text(''.join(f"file '{(OUT/(s['key']+'.mp4')).as_posix()}'\n" for s in shots))
        with (OUT/'assembly.log').open('w') as log:
            subprocess.run(['ffmpeg','-hide_banner','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(OUT/'studio-clickthrough-1080p.mp4')],check=True,stdout=log,stderr=log)
        (OUT/'capture.json').write_text(json.dumps(dict(capture_id=payload['capture_id'],snapshot_id=payload['snapshot_id'],
            viewport=[1920,1080],browser_zoom=1.15,shots=shots,javascript_errors=errors,
            note='Actual dashboard interaction with retained evaluation. Lossless PNG acquisition, visible mouse-event pointer, no provider calls or new inference. Cost contexts briefly changed to 10 as an explicitly user-adjusted scenario, then returned to 1.'),indent=2))
        print('COMPLETE: '+str(OUT),flush=True)
    finally:
        with closing(sqlite3.connect(store.path)) as db,db:
            db.execute('DELETE FROM sessions WHERE digest=?',(hashlib.sha256(token.encode()).hexdigest(),))

if __name__=='__main__':
    asyncio.run(main())
