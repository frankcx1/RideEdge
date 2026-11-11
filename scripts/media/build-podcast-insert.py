"""Local podcast assembly. Original recordings remain untouched; CPU encoding only."""
from pathlib import Path
import argparse, json, math, subprocess
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--revision',choices=['v1','v2'],default='v1')
REV=parser.parse_args().revision
V2=REV=='v2'
OUT=ROOT/f'recordings/podcast/edit-{REV}'
WORK=OUT/'work'
SECTIONS=OUT/'sections'
SECTIONS.mkdir(parents=True,exist_ok=True)
WORK.mkdir(exist_ok=True)
SR=48000
FPS=30
RAW=ROOT/'recordings/podcast'
OLD=ROOT/'recordings/rideedge-narrated-demo-20261106-v3/edit-assets'
STUDIO=ROOT/'recordings/rideedge-studio-clickthrough-20261106-take2/studio-clickthrough-1080p.mp4'
VOLVO=ROOT/'recordings/androidauto.mp4'

def ff(args,name):
    p=subprocess.run(['ffmpeg','-hide_banner','-y',*map(str,args)],capture_output=True,text=True,encoding='utf-8',errors='replace')
    (WORK/f'{name}.log').write_text(p.stderr,encoding='utf-8')
    if p.returncode: raise RuntimeError(name+': '+p.stderr[-2500:])
    return p.stderr

def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)]))

sections=[
 dict(key='01_Opening',source='01-opening.mp4',cuts=[[.30,34.70 if V2 else 15.03]]),
 dict(key='02_Inside_the_local_engine',source="02_Here's how it works.wav",cuts=[[1.80,20.10],[23.20,33.55]]),
 dict(key='03_Phone_and_real_Volvo',source='03_Phone and car walktrhough.wav',cuts=[[2.55,35.40]]),
 dict(key='04_Beyond_rideshare',source='04__local_ai_closing.mp4',cuts=[[0,37.0]]),
]
cursor=0
audio=[]
for s in sections:
    decoded=WORK/(s['key']+'-source.wav')
    ff(['-i',RAW/s['source'],'-vn','-ac','1','-ar',SR,'-c:a','pcm_f32le',decoded],s['key']+'-decode')
    samples,rate=sf.read(decoded,dtype='float32'); assert rate==SR
    pieces=[]
    for a,b in s['cuts']:
        clip=samples[round(a*SR):round(b*SR)].copy()
        fade=min(240,len(clip)//2)
        clip[:fade]*=np.linspace(0,1,fade)
        clip[-fade:]*=np.linspace(1,0,fade)
        pieces.append(clip)
    joined=np.concatenate(pieces)
    s['frames']=math.ceil(len(joined)/SR*FPS-1e-8)
    s['duration']=s['frames']/FPS
    s['start']=cursor;cursor+=s['duration']
    joined=np.pad(joined,(0,round(s['duration']*SR)-len(joined)))
    raw=WORK/(s['key']+'-cut.wav');sf.write(raw,joined,SR,subtype='FLOAT')
    log=ff(['-i',raw,'-af','loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json','-f','null','NUL'],s['key']+'-measure')
    measure=json.loads(log[log.rfind('{'):log.rfind('}')+1]);s['input_loudness']=measure
    filt='loudnorm=I=-18:TP=-1.5:LRA=11:linear=true:print_format=json:'+':'.join(f'{k}={measure[v]}' for k,v in [('measured_I','input_i'),('measured_TP','input_tp'),('measured_LRA','input_lra'),('measured_thresh','input_thresh'),('offset','target_offset')])
    normalized=WORK/(s['key']+'-normalized.wav')
    ff(['-i',raw,'-af',filt,'-ar',SR,'-c:a','pcm_s24le',normalized],s['key']+'-normalize')
    data,_=sf.read(normalized);data=data[:round(s['duration']*SR)]
    data=np.pad(data,(0,max(0,round(s['duration']*SR)-len(data))))
    audio.append(data)
    s['audio']=str(normalized.relative_to(OUT))
    print('Prepared '+s['key']+f' {s["duration"]:.2f}s',flush=True)
sf.write(OUT/'RideEdge-podcast-audio.wav',np.concatenate(audio),SR,subtype='PCM_24')

shots=[]
def shot(section,source,start,duration=None,frames=None,tag=None):
    frames=round(duration*FPS) if frames is None else frames
    shots.append(dict(section=section,source=str(source.relative_to(ROOT)),source_start=start,frames=frames,duration=frames/FPS,tag=tag))

shot(0,RAW/sections[0]['source'],.30,frames=sections[0]['frames'])
if V2:
    shot(1,OUT/'dashboard/dashboard-story.mp4',0,frames=sections[1]['frames'])
else:
    shot(1,STUDIO,6,5)
    shot(1,STUDIO,11,10)
    shot(1,STUDIO,34,5)
    shot(1,STUDIO,44,6)
    shot(1,STUDIO,39,frames=sections[1]['frames']-26*FPS)
shot(2,OLD/'shot-03.mp4',0,6)
shot(2,OLD/'shot-04.mp4',0,4.1)
shot(2,OLD/'shot-06.mp4',0,4.4)
shot(2,OLD/'shot-08.mp4',0,3.9)
shot(2,VOLVO,2,frames=sections[2]['frames']-round(18.4*FPS),tag='IN THE VOLVO')
shot(3,RAW/sections[3]['source'],0,frames=sections[3]['frames'])

overlay=Image.new('RGBA',(1920,1080),(0,0,0,0))
draw=ImageDraw.Draw(overlay)
draw.rounded_rectangle((36,28,335,85),radius=10,fill=(9,19,29,235))
draw.text((54,39),'IN THE VOLVO',font=ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf',28),fill='#f3f1e9')
overlay.save(WORK/'volvo-label.png')

for i,s in enumerate(shots):
    dest=WORK/f'podcast-shot-{i:02}.mp4';s['output']=str(dest.relative_to(OUT))
    args=['-ss',s['source_start'],'-i',ROOT/s['source']]
    vf='fps=30,scale=1920:1080:flags=lanczos,setsar=1,setpts=PTS-STARTPTS'
    if s['tag']:
        args+=['-i',WORK/'volvo-label.png','-filter_complex_threads','2','-filter_complex',f'[0:v]{vf}[v];[v][1:v]overlay=0:0,format=yuv420p[out]','-map','[out]']
    else: args+=['-vf',vf+',format=yuv420p']
    args+=['-frames:v',s['frames'],'-an','-c:v','libx264','-threads','4','-preset','fast','-crf','18','-r','30','-video_track_timescale','15360',dest]
    ff(args,f'shot-{i:02}')
    actual=probe(dest)
    assert int(next(v for v in actual['streams'] if v['codec_type']=='video')['nb_frames'])==s['frames']
    print(f'Rendered shot {i+1}/{len(shots)}',flush=True)

def listing(name,chosen):
    p=WORK/name
    p.write_text(''.join(f"file '{(OUT/x['output']).as_posix()}'\n" for x in chosen),encoding='utf-8')
    return p

for i,s in enumerate(sections):
    chosen=[x for x in shots if x['section']==i]
    assert sum(x['frames'] for x in chosen)==s['frames']
    ff(['-f','concat','-safe','0','-i',listing(s['key']+'.txt',chosen),'-i',OUT/s['audio'],'-map','0:v','-map','1:a','-t',s['duration'],'-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',SECTIONS/(s['key']+'.mp4')],s['key']+'-mux')

metadata=';FFMETADATA1\ntitle=RideEdge — podcast insert\n'
for s in sections:
    metadata+=f'\n[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(s["start"]*1000)}\nEND={round((s["start"]+s["duration"])*1000)}\ntitle={s["key"][3:].replace("_"," ")}\n'
(WORK/'podcast-chapters.txt').write_text(metadata,encoding='utf-8')
master=OUT/f'RideEdge-podcast-review-{REV}.mp4'
ff(['-f','concat','-safe','0','-i',listing('podcast-master.txt',shots),'-i',OUT/'RideEdge-podcast-audio.wav','-i',WORK/'podcast-chapters.txt','-map','0:v','-map','1:a','-map_metadata','2','-map_chapters','2','-t',cursor,'-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',master],'podcast-master')
ff(['-i',OUT/'RideEdge-podcast-audio.wav','-c:a','libmp3lame','-b:a','192k',OUT/'RideEdge-podcast-audio.mp3'],'podcast-mp3')
manifest=dict(duration=cursor,fps=FPS,sections=sections,shots=shots,originals_unchanged=True,notes=['Camera opening ends after APIs and data feeds; the next narration explains collection and evaluation.','Removed 23 subscriptions aside: inventory includes authored/static sources.','Phone/dashboard: retained Nov 3 evidence; actual UI recording. Not a new live evaluation.','Volvo: continuous source 2 seconds onward, original speed, original car audio muted.','No synthesized speech, no music, no changed app UI, no provider calls or model changes.'])
if V2:
    manifest['notes'][0]='Full spoken opening restored, including named data feeds and the workstation explanation; only leading and trailing silence trimmed.'
    manifest['notes'][2]='Simplified Studio presentation uses actual dated server observations; phone footage retains the Nov 3 evaluation. Concept views describe architecture, not live execution.'
    manifest['notes'][4]='No synthesized speech or music. New presentation UI is paced to narration. No paid provider calls or model changes.'
(OUT/'edit-timeline.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')

ff(['-v','error','-i',master,'-f','null','NUL'],'full-decode-check')
log=ff(['-i',master,'-af','loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json','-vn','-f','null','NUL'],'master-audio-check')
qa=dict(probe=probe(master),full_decode_passed=True,loudness=json.loads(log[log.rfind('{'):log.rfind('}')+1]))
(OUT/'technical-qa.json').write_text(json.dumps(qa,indent=2),encoding='utf-8')
times=[2,16,24,32,35,40,43,50,54,59,65,71,75,79,83,90,98,130,132] if V2 else [2,13,17,23,32,37,42,46,51,55,59,63,67,72,78,92,109,112]
sheet=Image.new('RGB',(1280,390*math.ceil(len(times)/2)),'#09131d')
for i,t in enumerate(times):
    p=WORK/f'review-{t}.jpg'
    ff(['-ss',t,'-i',master,'-frames:v','1','-vf','scale=640:360',p],f'frame-{t}')
    x=(i%2)*640;y=(i//2)*390
    sheet.paste(Image.open(p),(x,y));ImageDraw.Draw(sheet).text((x+12,y+367),f'Podcast edit {t//60:02}:{t%60:02}',fill='white')
sheet.save(OUT/'review-contact-sheet.jpg')

def tc(t):return f'{int(t)//60:02}:{t%60:06.3f}'
notes=f'''# RideEdge podcast insert — first cut

Runtime **{tc(cursor)}**. 1920×1080 at 30 fps. Four newly recorded takes, existing full-HD dashboard/phone footage, and the actual Volvo navigation handoff. Originals are unchanged.

## Deliverables

- `RideEdge-podcast-review-v1.mp4`: complete video insert, including presenter opening and closing.
- `RideEdge-podcast-audio.wav`: 48 kHz/24-bit mono audio master for the audio podcast.
- `RideEdge-podcast-audio.mp3`: convenient listening copy.
- `sections/`: four narrated sections for the editor to rearrange.
- `edit-timeline.json`: exact source ranges, speech trims, chapters, and picture edits.

## Chapters

'''
notes+='\n'.join(f'- {tc(s["start"])} — {s["key"][3:].replace("_"," ")}' for s in sections)
notes+='''

## Editorial decisions

The opening ends after “APIs and data feeds,” then cuts to “Here’s how it works.” This removes the repeated API list and the later “scrape that data” wording; the following narration accurately says the app gathers data and Qwen evaluates the options. The original opening remains available for a longer version.

The dashboard narration omits the aside about subscribing to 23 feeds. The dashboard's 23-source inventory includes static and authored inputs and should not be described as 23 live API subscriptions. All other spoken content remains in order; only lead-in/trailing pauses are trimmed. No synthetic voice or rewritten spoken words are used. Levels are matched across the four takes; speech speed is unchanged.

The phone/dashboard footage shows the recorded November 3 evaluation, with its original labels and timestamps. It is not a fresh live run and predates version 2.5.2. Missing current venue activity is visible in the evidence view. Dashboard footage is native 1080p; the stopped-worker operations view and older blurry screen are excluded. Nearby uses an early clean range before the Teams notification. The real Volvo handoff is continuous at original speed, from source 00:02 to approximately 00:16.5; its original sound is muted beneath the new voiceover. Maps opens with an existing route/stop context, which is preserved, not represented as a fresh trip or completed arrival.

The closing retains the distinction between no cloud-model token charge and ongoing hardware, power and feed costs. Example industries are hypothetical applications, not deployments claimed to exist.

## Review before publishing

Full-file decode, frame counts, output dimensions and audio levels are checked in `technical-qa.json`. Contact frames are provided for visual inspection. Please listen through once for the joins, natural pacing, and the “current activity” sentence; automatic transcription is a timing aid, not an authoritative transcript. No captions are burned in. Raw machine transcripts are retained separately and can contain mistaken names.

The Volvo footage includes real map/location information. This is a local review file; nothing has been uploaded or published. The app, GPU lease, local model and paid data feeds were not changed to create the edit.
'''
if V2:
    notes=notes.replace('first cut','revision 2').replace('RideEdge-podcast-review-v1.mp4','RideEdge-podcast-review-v2.mp4')
    a=notes.index('The opening ends after');b=notes.index('The dashboard narration omits',a)
    notes=notes[:a]+'The full spoken opening is restored, including Ticketmaster, FlightAware, Google Places, BestTime and the workstation explanation. Only its leading and trailing silence is trimmed. The following narration distinguishes app collection from model evaluation.\n\n'+notes[b:]
    a=notes.index('The phone/dashboard footage');b=notes.index('The closing retains',a)
    notes=notes[:a]+'''The dashboard is now a dedicated presentation with six narration-aligned views: named feeds and their roles; local Qwen; the ten-minute recurring review; actual source availability; actual model status and evidence/request timestamps; and unknown activity. All text is deliberately large. Status values are from a real read-only server request at the time recorded in `dashboard/capture.json`; the original response is retained locally at its provenance path. Scene progression is presentation timing, not staged model execution. No provider collection or inference was started to make this recording.

`dashboard/RideEdge-dashboard-presentation.html` is an interactive offline copy carrying the dated observations. Open it in Edge to review the six scenes or play the narration cues. `farol/static/studio-story.html` and `/studio/story` implement the new server presentation; that new route becomes available on the next normal backend restart. The existing operations dashboard is preserved.

The phone footage remains the November 3 recorded evaluation and predates version 2.5.2. Nearby uses the clean range before the Teams notification. The real Volvo handoff is continuous at original speed, from source 00:02 to approximately 00:16.5, muted beneath the new voiceover. Maps opens with an existing route/stop context, preserved as recorded. Original media and version 1 are unchanged.

'''+notes[b:]
(OUT/'EDIT_HANDOFF.md').write_text(notes,encoding='utf-8')
print(f'COMPLETE {master} {tc(cursor)}',flush=True)
