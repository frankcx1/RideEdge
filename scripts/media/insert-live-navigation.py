"""Replace the v2 pickup slate with the user's continuous Volvo handoff recording.

The source and earlier exports remain untouched. No app/backend actions or uploads.
"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]
PREVIOUS=ROOT/'recordings/rideedge-narrated-demo-20261106-v2'
OUT=ROOT/'recordings/rideedge-narrated-demo-20261106-v3'
SOURCE=ROOT/'recordings/androidauto.mp4'
WORK=OUT/'edit-assets'
for path in (OUT,WORK,OUT/'sections'):
    path.mkdir(exist_ok=True,parents=True)

def run(args,name):
    with (WORK/(name+'.log')).open('w',encoding='utf-8') as log:
        subprocess.run(['ffmpeg','-hide_banner','-y',*map(str,args)],check=True,stdout=log,stderr=log)

timeline=json.loads((PREVIOUS/'edit-timeline.json').read_text())
timeline['revision']='v3'
timeline['based_on']='recordings/rideedge-narrated-demo-20261106-v2'
timeline['original_media']['live_car']='recordings/androidauto.mp4'
timeline['navigation_pickup']['status']='replaced_with_actual_in_car_footage'
timeline['live_navigation']={
    'source':'recordings/androidauto.mp4',
    'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    'source_in_seconds':2.0,'source_out_seconds':26.9,
    'timeline_start_seconds':117.0,'timeline_end_seconds':141.9,
    'playback_speed':1.0,'source_audio_used':False,
    'observed_sequence':'Marymoor Park selected in RideEdge; Navigate pressed; Google Maps opens route and turn-by-turn directions.',
    'note':'Continuous source footage, split into two adjacent existing edit shots. No speed changes or constructed app states. This is a separate user-recorded car session, not the November 3 captured evaluation.'
}

for s in timeline['sections']:
    for shot in s['shots']:
        target=OUT/shot['output']
        if shot['key'] not in ('shot-12','shot-13'):
            shutil.copy2(PREVIOUS/shot['output'],target)
            if shot.get('background'):
                shutil.copy2(PREVIOUS/shot['background'],OUT/shot['background'])
            continue
        start=2.0 if shot['key']=='shot-12' else 17.7
        duration=shot['frames']/30
        shot.update(kind='live_car',source_start_seconds=start,source_available_seconds=duration,
                    background=None,source='recordings/androidauto.mp4')
        # Label sits in the black margin of the original camera view, outside the display.
        vf=("fps=30,setsar=1,drawbox=x=42:y=32:w=330:h=64:color=0x09131d@0.92:t=fill,"
            "drawtext=fontfile='C\\:/Windows/Fonts/segoeuib.ttf':text='IN THE VOLVO':fontsize=27:fontcolor=0xf3f1e9:x=62:y=48,format=yuv420p")
        print('Rendering '+shot['key']+' from live recording',flush=True)
        run(['-ss',start,'-i',SOURCE,'-vf',vf,'-frames:v',shot['frames'],'-an',
             '-c:v','libx264','-threads','4','-preset','fast','-crf','18',
             '-r','30','-video_track_timescale','15360',target],shot['key'])

for filename in ('RideEdge-walkthrough-narration.wav','Live-navigation-insert-VO.wav'):
    shutil.copy2(PREVIOUS/filename,OUT/filename)
audio=OUT/'RideEdge-walkthrough-narration.wav'
for s in timeline['sections']:
    target=OUT/'sections'/(s['key']+'.mp4')
    if s['key']!='05_Android_Auto':
        shutil.copy2(PREVIOUS/'sections'/target.name,target)
        continue
    listing=WORK/'android-auto-shots.txt'
    listing.write_text(''.join(f"file '{(OUT/x['output']).as_posix()}'\n" for x in s['shots']),encoding='utf-8')
    run(['-f','concat','-safe','0','-i',listing,'-ss',s['start_seconds'],'-i',audio,
         '-map','0:v','-map','1:a','-t',s['duration_seconds'],'-c:v','copy','-c:a','aac','-b:a','192k',
         '-movflags','+faststart',target],'android-auto-mux')

metadata=(PREVIOUS/'edit-assets/chapters.txt').read_text(encoding='utf-8').replace(
    'RideEdge narrated walkthrough — navigation pickup reserved','RideEdge narrated walkthrough — live Volvo navigation')
(WORK/'chapters.txt').write_text(metadata,encoding='utf-8')
listing=WORK/'all-shots.txt'
listing.write_text(''.join(f"file '{(OUT/x['output']).as_posix()}'\n" for s in timeline['sections'] for x in s['shots']),encoding='utf-8')
run(['-f','concat','-safe','0','-i',listing,'-i',audio,'-i',WORK/'chapters.txt',
     '-map','0:v','-map','1:a','-map_metadata','2','-map_chapters','2','-t',timeline['duration_seconds'],
     '-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',OUT/'RideEdge-walkthrough-review-v3.mp4'],'master-mux')

# Separate narrated handoff for the editor, with the same continuous footage as the master.
listing=WORK/'live-navigation-shots.txt'
listing.write_text(''.join(f"file '{(WORK/(key+'.mp4')).as_posix()}'\n" for key in ['shot-12','shot-13']),encoding='utf-8')
run(['-f','concat','-safe','0','-i',listing,'-ss',117,'-i',audio,'-map','0:v','-map','1:a',
     '-t',24.9,'-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',OUT/'Volvo-live-navigation-narrated.mp4'],'handoff-mux')
(OUT/'edit-timeline.json').write_text(json.dumps(timeline,indent=2),encoding='utf-8')
(OUT/'EDIT_HANDOFF.md').write_text('''# RideEdge walkthrough — version 3

The live Volvo navigation recording is now included. Runtime remains **04:34.800**, 1920×1080 at 30 fps. The seven chapters, narration and all other edit timings are unchanged from version 2. This is the app walkthrough for combining with the editor's presenter footage and B-roll.

## Main deliverables

- `RideEdge-walkthrough-review-v3.mp4`: complete narrated walkthrough, with no navigation placeholder.
- `sections/05_Android_Auto.mp4`: updated standalone Android Auto section.
- `Volvo-live-navigation-narrated.mp4`: 24.9-second standalone narrated live handoff.
- `sections/`: all seven narrated sections for the editor to rearrange.
- `RideEdge-walkthrough-narration.wav`: unchanged leveled narration.
- `edit-timeline.json`: original sources, exact selections and provenance.

## Live handoff

The user supplied `recordings/androidauto.mp4`. Its **00:02.000–00:26.900** excerpt runs continuously, at original speed, at **01:57.000–02:21.900** in the walkthrough. It replaces the original 15.7-second pickup slate and the following 9.2-second return to the desktop car capture. The scene now ends on the actual Volvo display.

The recording shows selection of Marymoor Park in RideEdge, a tap on Navigate, Google Maps opening the destination/route, and turn-by-turn guidance. It establishes the navigation handoff; it does not show completion of the drive or arrival. A small “IN THE VOLVO” label occupies the black margin outside the display. Source framing is preserved. The source camera audio is omitted from the edit so the recorded voiceover remains the soundtrack; the original file is unchanged.

This footage is a separate user-recorded car session. The surrounding phone and desktop car views retain the earlier November 3 captured evaluation. The fresh full-HD dashboard click-through from version 2 and the notification-free phone insert are retained.

## Earlier editorial choices retained

Architecture narration keeps whole passages from source ranges 2.2–27.7, 36.5–52.2 and 63.1–74.3 seconds. The recurring-review graphic explains active-session behavior; it does not present the old stopped-worker dashboard as a live heartbeat. The cloud calculator is an estimate for the recorded workload and pricing snapshot, not measured net savings. Raw voiceovers, source footage and versions 1 and 2 remain untouched. No provider collection, model startup, publishing or upload was needed for this edit.
''',encoding='utf-8')
print('COMPLETE: '+str(OUT),flush=True)
