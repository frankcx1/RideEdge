"""Assemble existing captures and narration; no services, uploads or provider calls.

Original media is read-only. The navigation insert is an explicitly marked pickup,
not a simulated successful handoff. Requires ffmpeg, Pillow, numpy, soundfile, scipy.
"""
from pathlib import Path
import argparse
import json
import math
import shutil
import subprocess
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--revision', choices=['v1', 'v2'], default='v2')
REVISION = parser.parse_args().revision
V2 = REVISION == 'v2'
ORIGINAL = ROOT / 'recordings/rideedge-narrated-demo-20261106'
OUT = ROOT / ('recordings/rideedge-narrated-demo-20261106-v2' if V2 else 'recordings/rideedge-narrated-demo-20261106')
WORK = OUT / 'edit-assets'
VO = ROOT / 'recordings/voiceover/2026-11-06'
for p in (OUT, WORK, OUT / 'sections'):
    p.mkdir(parents=True, exist_ok=True)
MEDIA = {
    'phone': ROOT / 'recordings/rideedge-tour-20261103-163324-0d023d/phone-feature-edit.mp4',
    'car': ROOT / 'recordings/rideedge-tour-20261103-174601-a16bf8/car-feature-edit.mp4',
    'studio': ROOT / 'recordings/rideedge-studio-20261103-163514/studio-features.mp4',
}
if V2:
    MEDIA['studio'] = ROOT / 'recordings/rideedge-studio-clickthrough-20261106-take2/studio-clickthrough-1080p.mp4'
    assert MEDIA['studio'].exists(), 'Record the full-HD dashboard click-through first.'
FPS, SR = 30, 48000
NAVY, PANEL, WHITE, MUTED, AMBER, TEAL = '#09131d', '#132735', '#f3f1e9', '#aabcc9', '#f4a15c', '#82d4cd'

def run(args, name):
    with (WORK / (name + '.log')).open('w', encoding='utf-8') as log:
        subprocess.run(['ffmpeg', '-hide_banner', '-y', *map(str, args)], stdout=log, stderr=log, check=True)

def font(size, bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf' if bold else 'C:/Windows/Fonts/segoeui.ttf', size)

def wrap(draw, text, xy, size, width, fill=WHITE, bold=False, gap=14):
    x, y = xy
    f = font(size, bold)
    for paragraph in text.split('\n'):
        line = ''
        for word in paragraph.split():
            candidate = (line + ' ' + word).strip()
            if draw.textlength(candidate, font=f) > width and line:
                draw.text((x, y), line, font=f, fill=fill)
                y += size + gap
                line = word
            else:
                line = candidate
        draw.text((x, y), line, font=f, fill=fill)
        y += size + gap
    return y

def background(key, title, kind, heading='', body='', footer='Recorded evaluation · November 3, 2026'):
    im = Image.new('RGB', (1920, 1080), NAVY)
    d = ImageDraw.Draw(im)
    d.rectangle((64, 34, 70, 66), fill=AMBER)
    d.text((88, 28), 'RideEdge', font=font(30, True), fill=WHITE)
    d.text((270, 33), title, font=font(24), fill=MUTED)
    if footer:
        w = d.textlength(footer, font=font(19))
        d.text((1856-w, 36), footer, font=font(19), fill=MUTED)
    d.line((64, 84, 1856, 84), fill='#294351', width=2)
    if kind == 'phone':
        d.text((108, 218), 'ON THE PHONE', font=font(22, True), fill=TEAL)
        y = wrap(d, heading, (104, 278), 70, 860, bold=True)
        wrap(d, body, (108, y+35), 32, 800, MUTED, gap=16)
        d.rounded_rectangle((1178, 101, 1656, 1059), radius=28, fill='#203745', outline='#3c596a', width=2)
    elif kind in ('graphic', 'pickup'):
        label = 'EDITORIAL INSERT · REPLACE WITH IN-CAR FOOTAGE' if kind == 'pickup' else 'HOW THE SERVICE WORKS'
        d.text((108, 170), label, font=font(23, True), fill=AMBER if kind == 'pickup' else TEAL)
        y = wrap(d, heading, (104, 230), 64, 1680, bold=True)
        wrap(d, body, (108, y+30), 32, 1580, MUTED, gap=16)
    path = WORK / (key + '.png')
    im.save(path)
    return path

def cycle_graphic(key, title, applications=False):
    path = background(key, title, 'graphic',
        'One local engine. Repeated useful work.' if applications else 'Review. Validate. Deliver. Repeat.',
        'The same pattern can support many operational decisions.' if applications else
        'During an active planning session, the next review is scheduled ten minutes after the previous evaluation finishes.',
        footer='Architecture illustration')
    im = Image.open(path); d = ImageDraw.Draw(im)
    labels = [('Delivery', 'Revisit delays and routes'), ('Field service', 'Assess the next assignment'), ('Equipment', 'Flag what needs attention')] if applications else [
        ('Evidence', 'Freshness, coverage and timing'), ('Local Qwen', 'Evaluate eligible options'), ('Validation', 'Check and serve the result')]
    for i, (a, b) in enumerate(labels):
        x = 108 + 576*i
        d.rounded_rectangle((x, 555, x+540, 825), radius=20, fill=PANEL, outline='#365261', width=2)
        d.text((x+30, 588), f'0{i+1}', font=font(24, True), fill=AMBER)
        d.text((x+30, 643), a, font=font(40, True), fill=WHITE)
        wrap(d, b, (x+30, 715), 26, 470, MUTED)
    d.text((108, 923), 'Potential applications' if applications else 'Next review: 10 minutes after completion · Active planning required', font=font(26), fill=TEAL)
    im.save(path)
    return path

# Audio edits use whole spoken passages. Raw WAVs and raw transcripts are retained.
specs = [
 ('01_Overview', 'What RideEdge does', '02_What_RideEdge_does.wav', None),
 ('02_Now', 'Now · the next positioning decision', '05_Now_and_its_evidence.wav', None),
 ('03_Nearby', 'Nearby · inspect the surrounding activity', '06_Nearby_and_changing_context.wav', None),
 ('04_Plan', 'Plan · look ahead', '08_Plan_and_Comparison.wav', None),
 ('05_Android_Auto', 'Android Auto · guidance in the car', '08_Android_Auto_and_Maps.wav', [(0, 35.7)]),
 ('06_Architecture', 'Inside the local AI service', '09_Reveal_the_architecture.wav', [(2.2, 27.7), (36.5, 52.2), (63.1, 74.3)]),
 ('07_Recurring_Work', 'Recurring work · local ownership', '10_Recurring_review_and_local_economics.wav', None),
]
sections, audio_parts, cursor = [], [], 0
for key, title, filename, cuts in specs:
    data, rate = sf.read(VO / filename)
    cuts = cuts or [(0, len(data)/rate)]
    pieces = []
    for start, end in cuts:
        piece = data[round(start*rate):round(end*rate)].copy()
        fade = min(round(rate*.006), len(piece)//2)
        piece[:fade] *= np.linspace(0, 1, fade)
        piece[-fade:] *= np.linspace(1, 0, fade)
        pieces.append(piece)
    data = np.concatenate(pieces)
    g = math.gcd(rate, SR)
    data = resample_poly(data, SR//g, rate//g)
    frames = math.ceil(len(data)/SR*FPS)
    duration = frames/FPS
    data = np.pad(data, (0, frames*(SR//FPS)-len(data)))
    audio_parts.append(data)
    sections.append(dict(key=key, title=title, audio_source=filename, audio_cuts_seconds=cuts,
                         start_seconds=cursor/FPS, duration_seconds=duration, frames=frames, shots=[]))
    cursor += frames
sf.write(WORK / 'narration-before-leveling.wav', np.concatenate(audio_parts), SR, subtype='PCM_24')
run(['-i', WORK/'narration-before-leveling.wav', '-af', 'loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json', '-f','null','-'], 'loudness-measure')
log = (WORK/'loudness-measure.log').read_text()
measure = json.JSONDecoder().raw_decode(log[log.rfind('{'):])[0]
af = 'loudnorm=I=-18:TP=-1.5:LRA=11:linear=true:' + ':'.join([
    'measured_I='+measure['input_i'], 'measured_TP='+measure['input_tp'],
    'measured_LRA='+measure['input_lra'], 'measured_thresh='+measure['input_thresh'], 'offset='+measure['target_offset']])
run(['-i', WORK/'narration-before-leveling.wav', '-af', af, '-ar', SR, '-c:a','pcm_s24le', OUT/'RideEdge-walkthrough-narration.wav'], 'loudness-apply')

def shot(section, kind, start, available, seconds, heading='', body='', graphic=None):
    s = sections[section]
    used = sum(x['frames'] for x in s['shots'])
    n = s['frames']-used if seconds is None else round(seconds*FPS)
    index = sum(len(x['shots']) for x in sections)
    key = f'shot-{index:02}'
    bg = graphic or background(key, s['title'], kind, heading, body)
    s['shots'].append(dict(key=key, kind=kind, source_start_seconds=start, source_available_seconds=available,
                           frames=n, background=str(bg.relative_to(OUT)), output=str((WORK/(key+'.mp4')).relative_to(OUT))))

shot(0,'phone',1,15,11,'Where should I go next?', 'Activity, timing and travel — brought together in one place.')
shot(0,'car',1,15,5)
shot(0,'studio',0 if V2 else 1,6 if V2 else 13,None)
shot(1,'phone',1,18,12.7,'Now', 'An immediate recommendation, with alternatives to inspect.')
shot(1,'phone',21,18,11.3,'Why this place?', 'Review the supporting evidence and the travel involved.')
shot(1,'phone',41,18,None,'Compare the options.', 'RideEdge supports positioning decisions. Uber handles rider matching.')
shot(2,'phone',61,18,20.5,'Nearby', 'Explore activity around you — and how its timing fits your arrival.')
shot(2,'phone',151 if V2 else 141,8 if V2 else 18,None,'Inspect the evidence.', 'See what is available, and what is still unknown.')
shot(3,'phone',81,18,None,'Plan', 'A six-hour outlook you can revisit as the evening develops.')
shot(4,'car',1,15,4.4)
shot(4,'car',61,18,3.2)
shot(4,'car',81,18,3.2)
pickup = background('navigation-pickup', 'Android Auto · live navigation insert', 'pickup',
    'RideEdge → Google Maps',
    'Reserved for your live Volvo recording.\nSelect a recommendation, choose Navigate, then show Google Maps opening the route.\nKeep the car parked while demonstrating the handoff.', footer='Pickup slot · 15.7 seconds')
shot(4,'pickup',0,0,15.7,graphic=pickup)
shot(4,'car',1,18,None)
shot(5,'studio',6 if V2 else 1,25.5 if V2 else 13,25.5)
shot(5,'studio',31.5 if V2 else 16,10.5 if V2 else 13,10.5 if V2 else 5.3)
shot(5,'studio',42 if V2 else 31,16.4 if V2 else 13,None)
cycle = cycle_graphic('review-cycle', 'Recurring work · local ownership')
apps = cycle_graphic('business-applications', 'Recurring work · local ownership', True)
shot(6,'graphic',0,0,20.2,graphic=cycle)
shot(6,'graphic',0,0,19.4,graphic=apps)
shot(6,'studio',58.4 if V2 else 61,25.4 if V2 else 13,25.4)
shot(6,'graphic',0,0,None,graphic=cycle)

for s in sections:
    assert sum(x['frames'] for x in s['shots']) == s['frames']
    for x in s['shots']:
        destination = OUT / x['output']
        duration = x['frames']/FPS
        unchanged = V2 and x['key'] not in {'shot-02','shot-07','shot-14','shot-15','shot-16','shot-19'}
        prior = ORIGINAL / x['output']
        if unchanged and prior.exists():
            shutil.copy2(prior, destination)
            print('Reused unchanged '+x['key'], flush=True)
            continue
        args = ['-loop','1','-framerate',FPS,'-i', OUT/x['background']]
        if x['kind'] in MEDIA:
            args += ['-ss',x['source_start_seconds'],'-t',min(duration,x['source_available_seconds']),'-i',MEDIA[x['kind']]]
            w,h,px,py = {'phone':(456,938,1189,111), 'car':(1728,972,96,94), 'studio':(1488,930,216,112)}[x['kind']]
            if V2 and x['kind']=='studio':
                w,h,px,py = 1920,1080,0,0
            vf = f'[1:v]fps=30,scale={w}:{h}:flags=lanczos,setsar=1,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={duration}[v];[0:v][v]overlay={px}:{py}:shortest=1,format=yuv420p[out]'
            args += ['-filter_complex_threads','2','-filter_complex',vf,'-map','[out]']
        else:
            args += ['-vf','format=yuv420p']
        args += ['-frames:v', x['frames'], '-an','-c:v','libx264','-threads','4','-preset','fast','-crf','16' if V2 and x['kind']=='studio' else '19','-r',FPS,'-video_track_timescale','15360',destination]
        print(f'Rendering {x["key"]}: {s["title"]} ({duration:.1f}s)', flush=True)
        run(args, x['key'])
    listing = WORK/(s['key']+'.txt')
    listing.write_text(''.join(f"file '{(OUT/x['output']).as_posix()}'\n" for x in s['shots']), encoding='utf-8')
    run(['-f','concat','-safe','0','-i',listing,'-ss',s['start_seconds'],'-i',OUT/'RideEdge-walkthrough-narration.wav',
         '-map','0:v','-map','1:a','-t',s['duration_seconds'],'-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',
         OUT/'sections'/(s['key']+'.mp4')], s['key']+'-mux')

navigation = sections[4]['start_seconds']+10.8
manifest = dict(created='2026-11-06', revision=REVISION, fps=FPS, duration_seconds=cursor/FPS, sections=sections,
                navigation_pickup=dict(start_seconds=navigation, duration_seconds=15.7,
                    audio_source='08_Android_Auto_and_Maps.wav', source_in_seconds=10.8, source_out_seconds=26.5),
                source_capture_id='20261104T001624Z-70eec709', snapshot_id='179771fe99d68e2346e6',
                original_media={k:str(v.relative_to(ROOT)) for k,v in MEDIA.items()},
                audio_leveling=dict(target_lufs=-18, max_true_peak_dbtp=-1.5, source_measurement=measure))
(OUT/'edit-timeline.json').write_text(json.dumps(manifest, indent=2),encoding='utf-8')
metadata = ';FFMETADATA1\ntitle=RideEdge narrated walkthrough — navigation pickup reserved\n'
for s in sections:
    metadata += f'\n[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(s["start_seconds"]*1000)}\nEND={round((s["start_seconds"]+s["duration_seconds"])*1000)}\ntitle={s["title"]}\n'
(WORK/'chapters.txt').write_text(metadata,encoding='utf-8')
listing=WORK/'all-shots.txt'
listing.write_text(''.join(f"file '{(OUT/x['output']).as_posix()}'\n" for s in sections for x in s['shots']),encoding='utf-8')
run(['-f','concat','-safe','0','-i',listing,'-i',OUT/'RideEdge-walkthrough-narration.wav','-i',WORK/'chapters.txt',
     '-map','0:v','-map','1:a','-map_metadata','2','-map_chapters','2','-t',cursor/FPS,'-c:v','copy','-c:a','aac','-b:a','192k',
     '-movflags','+faststart',OUT/f'RideEdge-walkthrough-review-{REVISION}.mp4'],'master-mux')
run(['-ss',navigation,'-i',OUT/'RideEdge-walkthrough-narration.wav','-t',15.7,'-c:a','pcm_s24le',OUT/'Live-navigation-insert-VO.wav'],'navigation-vo')

def tc(value):
    return f'{int(value)//60:02}:{value%60:06.3f}'

notes = f'''# RideEdge narrated walkthrough — edit handoff

Runtime: **{tc(cursor/FPS)}**. 1920×1080, 30 fps, H.264/AAC. Narration: mono, 48 kHz, targeted at -18 LUFS.

`RideEdge-walkthrough-review-{REVISION}.mp4` is a complete review assembly with one clearly marked live-footage pickup slot. It is not the final publish version until that slot is replaced. No presenter opening, closing, music or B-roll is included.

## Live Volvo navigation insert

Replace **{tc(navigation)}–{tc(navigation+15.7)}** with the actual in-car RideEdge → Google Maps handoff. In `sections/05_Android_Auto.mp4`, the same slot is **00:10.800–00:26.500**. Its narration is also supplied as `Live-navigation-insert-VO.wav`.

Record 25–35 seconds with the car parked. Hold on the RideEdge recommendation for 3–5 seconds, select it and tap Navigate, allow Google Maps to open the actual destination/route, then hold for at least 5 seconds. Keep a continuous take, including any loading or confirmation step. the editor can trim pauses to fit the 15.7-second slot, or extend that slot and move the later material. This assembly contains no successful Maps handoff footage and does not substitute the failed earlier takes.

## Chapters

'''
notes += '\n'.join(f'- {tc(s["start_seconds"])} — {s["title"]}' for s in sections)
notes += '''

## What the editor receives

- Review MP4 with chapter markers and the navigation pickup slate.
- `sections/`: seven standalone narrated MP4s for rearranging around the presenter and B-roll.
- `RideEdge-walkthrough-narration.wav`: leveled 48 kHz/24-bit mono narration.
- `Live-navigation-insert-VO.wav`: the narration for the reserved live handoff.
- `edit-timeline.json`: exact source selections, timings and capture identifiers.
- `edit-assets/`: caption backgrounds, explanatory graphics and picture-only shots; these permit reframing without changing the original recordings.

## Editorial choices and provenance

The phone, Android Auto and dashboard footage comes from the same November 3 captured evaluation, not a reconstructed Friday shift. Long dashboard/phone views use an intentional final-frame hold; they do not manufacture subsequent evaluations. Graphic explanations are labeled as architecture illustrations. The dashboard operations capture shows a stopped worker and is deliberately not used to illustrate an actively running heartbeat. The capture was made after GPU release; this cut does not present its VRAM as Qwen's loaded usage.

The Android Auto voiceover is retained through 35.7 seconds, including the reserved live-handoff passage. Architecture narration uses source ranges 2.2–27.7, 36.5–52.2 and 63.1–74.3 seconds, removing two passages for a tighter account of collection, policy and validation. Other chosen tracks retain their complete narration. Whole sentences remain in their original order, with short edge fades and level adjustment. Original WAVs and uncorrected transcripts are untouched. Raw transcript wording is not burned into the video as captions.

The cloud calculator displays an estimate for the captured workload and the pricing snapshot visible in the recording; it is not a fresh price quote or a measured net operating saving. Local inference avoids cloud-model token charges; hardware, electricity and data feeds still have costs. BestTime and the model were not started to produce this edit.

The technical checks cover decoding, dimensions, timing, frame layout and signal levels. The final spoken pacing and pronunciation still merit a listen-through before publication.
'''
(OUT/'EDIT_HANDOFF.md').write_text(notes,encoding='utf-8')
if V2:
    with (OUT/'EDIT_HANDOFF.md').open('a',encoding='utf-8') as note:
        note.write('''

## Revision 2 — dashboard and notification fixes

The dashboard was re-recorded on November 6 using the actual application in captured-evaluation mode, retaining the same November 3 evidence and model result. It now fills the 1920×1080 frame without downscaling, with 115% browser zoom, intact page header at the beginning, visible pointer movements, tab clicks, a source search/detail view, an expanded policy and the interactive cost calculator. Screen acquisition uses lossless PNG frames before high-quality H.264 encoding. Scrolling is deliberate and recorded; the top of the page is shown before each feature is explored. The calculator briefly shows a user-adjusted scenario of 10 contexts and returns to 1; it is not presented as measured workload growth.

The phone source-detail insert now starts at 02:31 of the original phone feature master, after the notification has cleared. The notification-containing frames are excluded rather than obscured. Narration, total runtime and the live Volvo navigation slot remain unchanged. Version 1 and all source recordings are retained.
''')
print(f'COMPLETE: {OUT} ({tc(cursor/FPS)})', flush=True)
