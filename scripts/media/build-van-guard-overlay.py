"""Silent podcast overlay from verified original Van Guard footage. CPU only."""
from pathlib import Path
import json,subprocess
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'recordings/van-guard';OUT=BASE/'overlay-v1';WORK=OUT/'work';SHOTS=OUT/'shots'
WORK.mkdir(parents=True,exist_ok=True);SHOTS.mkdir(exist_ok=True)
SRC=BASE/'phone-originals/screen-20261015-163813-1792107383317.mp4'
FPS=30

def ff(args,name):
    with (WORK/(name+'.log')).open('w',encoding='utf-8') as log:
        subprocess.run(['ffmpeg','-hide_banner','-y',*map(str,args)],stdout=log,stderr=log,check=True)
def probe(p):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)]))
def font(size,bold=False):return ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf' if bold else 'C:/Windows/Fonts/segoeui.ttf',size)

shots=[
 {'name':'01_Local_AI_on_the_phone','duration':16,'start':51.6,'hold':True,'heading':'Local AI.\nOn your phone.','body':'Van Guard\nYour van, on hand.','cue':'And then recently, I actually installed...'},
 {'name':'02_Ask_for_the_diagram','duration':12,'start':52.4,'heading':'Ask for what\nyou need.','body':'Speak your request.\nReview the words.','cue':'...find me the wiring diagram for my inverter... I can say it over voice...'},
 {'name':'03_Find_the_reference','duration':10,'start':64.4,'heading':'Find the\nsaved reference.','body':'Matching manual pages\nand diagrams.','cue':'...find that file and find that diagram...'},
 {'name':'04_Open_and_zoom','duration':16,'start':74.4,'heading':'The diagram.\nReady to inspect.','body':'Open the reference.\nZoom into the details.','cue':"...I’ll actually play a little bit of it... these phones themselves..."},
 {'name':'05_Practical_local_AI','duration':6,'start':90.4,'heading':'Useful AI.\nRight on the device.','body':'Your equipment.\nYour saved information.','cue':'...what is the problem and what are we trying to solve...'},
]
ff(['-ss','51.6','-i',SRC,'-frames:v','1',WORK/'intro-frame.png'],'intro-frame')
cursor=0
for s in shots:
    s['timeline_start']=cursor;cursor+=s['duration']
    im=Image.new('RGB',(1920,1080),'#10281f');d=ImageDraw.Draw(im)
    d.rectangle((88,73,95,109),fill='#c9d8b7')
    d.text((115,65),'VAN GUARD',font=font(33,True),fill='#f5f2e9')
    d.text((94,247),'LOCAL AI / A PRACTICAL APPLICATION',font=font(23),fill='#a9c8b5')
    d.multiline_text((88,313),s['heading'],font=font(78,True),fill='#f5f2e9',spacing=10)
    d.multiline_text((94,557),s['body'],font=font(35),fill='#c5d7cc',spacing=16)
    d.text((94,976),'Your vanlife field guide.',font=font(23),fill='#a9c8b5')
    d.rounded_rectangle((1190,55,1670,1021),radius=28,fill='#28483a',outline='#5b7a67',width=2)
    bg=WORK/(s['name']+'.png');im.save(bg)
    input_args=['-loop','1','-framerate',FPS,'-i',WORK/'intro-frame.png'] if s.get('hold') else ['-ss',s['start'],'-t',s['duration'],'-i',SRC]
    portrait=SHOTS/(s['name']+'-portrait.mp4')
    ff([*input_args,'-vf','crop=1080:2220:0:130,fps=30,setpts=PTS-STARTPTS,setsar=1,format=yuv420p','-frames:v',s['duration']*FPS,'-an','-c:v','libx264','-preset','fast','-crf','17','-threads','4','-video_track_timescale','15360',portrait],s['name']+'-portrait')
    dest=SHOTS/(s['name']+'.mp4')
    ff(['-loop','1','-framerate',FPS,'-i',bg,'-i',portrait,'-filter_complex_threads','2','-filter_complex',
        '[1:v]scale=460:946:flags=lanczos,setsar=1[p];[0:v][p]overlay=1200:65:shortest=1,format=yuv420p[out]',
        '-map','[out]','-frames:v',s['duration']*FPS,'-an','-c:v','libx264','-preset','fast','-crf','18','-threads','4','-video_track_timescale','15360',dest],s['name'])
    for p in (portrait,dest):
        info=probe(p);assert not any(x['codec_type']=='audio' for x in info['streams']);assert int(info['streams'][0]['nb_frames'])==s['duration']*FPS
    print('Rendered '+s['name'],flush=True)

qa={}
for suffix,title in [('', 'Van-Guard-podcast-overlay-60s-SILENT.mp4'),('-portrait','Van-Guard-phone-only-60s-SILENT.mp4')]:
    listing=WORK/('concat'+suffix+'.txt');listing.write_text(''.join(f"file '{(SHOTS/(s['name']+suffix+'.mp4')).as_posix()}'\n" for s in shots),encoding='utf-8')
    target=OUT/title
    ff(['-f','concat','-safe','0','-i',listing,'-c:v','copy','-an','-movflags','+faststart',target],'master'+suffix)
    ff(['-v','error','-i',target,'-f','null','NUL'],'decode'+suffix)
    info=probe(target);assert not any(x['codec_type']=='audio' for x in info['streams']);assert abs(float(info['format']['duration'])-60)<.04
    qa[title]={'full_decode_passed':True,'no_audio_stream':True,'probe':info}
(OUT/'technical-qa.json').write_text(json.dumps(qa,indent=2),encoding='utf-8')
(OUT/'edit-timeline.json').write_text(json.dumps({'duration_seconds':60,'timing':'Estimated editorial cues from supplied transcript; podcast audio was not provided.','source':str(SRC.relative_to(ROOT)),
    'shots':shots,'originals_unchanged':True,'crop':{'x':0,'y':130,'width':1080,'height':2220},
    'notes':['Intro holds a real pre-request frame for 16 seconds.','The rest is continuous source 52.4–96.4 at original speed. No synthesized UI, reordered results or fabricated successful steps.','System status strip and bottom gesture area are cropped for cleaner framing. Notifications and unrelated home screens are excluded.','No audio streams, music or narration. Original speech remains in the source recording.','Product captions describe saved references; they do not claim whole-phone filesystem access or independent verification of model size.']},indent=2),encoding='utf-8')

notes='''VAN GUARD — SILENT PODCAST OVERLAY

Start this overlay at: “And then recently, I actually installed...”
Keep the podcast’s existing audio playing underneath. Both exports have NO audio stream.

Van-Guard-podcast-overlay-60s-SILENT.mp4: 1920 x 1080, 30 fps, branded landscape layout.
Van-Guard-phone-only-60s-SILENT.mp4: 1080 x 2220, 30 fps, clean phone footage for your own framing.
shots/: five separate clips in both layouts, for exact alignment in the podcast editor.

ESTIMATED CUES — NOT AUDIO-SYNCHRONIZED
00:00–00:16  Local model / the app you built. Real Find screen held for narration.
00:16–00:28  “...wiring diagram for my inverter...” / voice request becomes text.
00:28–00:38  “...find that file... that diagram...” / saved diagram results and opening.
00:38–00:54  “...play a little bit...” / inspect and zoom the actual wiring diagram.
00:54–01:00  Closing point about practical local AI / hold on the reference.

The transcript’s app-and-conclusion portion is roughly one minute at a brisk podcast pace.
Use the phrases, rather than assuming these estimated times match the finished podcast.
If more time is needed, extend the opening still or the final diagram frame. Prefer trimming
the holds over speeding up the voice/search demonstration. Cut back to the hosts when useful.
The earlier Nanda/Pixel story is not illustrated or independently verified by this footage.

SOURCE AND EDIT
Source: phone recording screen-20261015-163813-1792107383317.mp4.
Opening hold: original frame at 00:51.600. Following footage: 00:52.400–01:36.400,
continuous and original speed. The phone’s top system/recording strip and bottom gesture area
are cropped. No personal notification screens, selfie overlays or failed voice takes are used.
Source audio is fully omitted; originals and prior imports remain unchanged.

This recording demonstrates searching saved manuals and opening a reference diagram.
It does not establish unrestricted access to every phone file. Captions stay within that scope.
The recorded UI identifies an EmbeddingGemma model; no additional model size or hardware claim
has been added to the video. No app services, models or paid feeds were started for this edit.

Full-file decoding, dimensions, frame counts and absence of audio were checked.
'''
(OUT/'EDIT-CUES.txt').write_text(notes,encoding='utf-8')
for t in [3,18,27,32,40,47,57]:
    ff(['-ss',t,'-i',OUT/'Van-Guard-podcast-overlay-60s-SILENT.mp4','-frames:v','1',WORK/f'check-{t}.jpg'],f'check-{t}')
print('COMPLETE: '+str(OUT),flush=True)
