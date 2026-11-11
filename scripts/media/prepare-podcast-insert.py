"""Inspect local podcast takes, retaining originals; CPU-only speech transcription."""
from pathlib import Path
import json,subprocess
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'recordings/podcast/edit-v1'
WORK=OUT/'work'
WORK.mkdir(parents=True,exist_ok=True)
sources=sorted(p for p in (ROOT/'recordings/podcast').iterdir() if p.is_file() and p.suffix.lower() in {'.mp4','.wav'})
inventory=[]
for i,p in enumerate(sources):
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(p)]))
    duration=float(probe['format']['duration'])
    inventory.append({'file':p.name,'duration':duration,'streams':[{k:s.get(k) for k in ('codec_type','codec_name','width','height','r_frame_rate','sample_rate','channels')} for s in probe['streams']]})
    audio=WORK/f'{i+1:02}-speech.wav'
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(p),'-vn','-ar','16000','-ac','1',str(audio)],check=True)
    if p.suffix=='.mp4':
        frames=[]
        for j,t in enumerate((2,duration*.25,duration*.5,duration*.75,duration-2)):
            frame=WORK/f'{i+1:02}-frame-{j}.jpg'
            subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(p),'-frames:v','1','-vf','scale=640:-1',str(frame)],check=True)
            im=Image.open(frame).convert('RGB'); canvas=Image.new('RGB',(640,400),'#101820')
            im.thumbnail((640,360));canvas.paste(im,((640-im.width)//2,0));ImageDraw.Draw(canvas).text((12,370),f'{p.name} at {t:.1f}s',fill='white');frames.append(canvas)
        sheet=Image.new('RGB',(1280,1200),'#101820')
        for j,im in enumerate(frames):sheet.paste(im,((j%2)*640,(j//2)*400))
        sheet.save(WORK/f'{i+1:02}-contact.jpg')
(OUT/'source-inventory.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
print(json.dumps(inventory),flush=True)

from faster_whisper import WhisperModel
model=WhisperModel('base.en',device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
for i,p in enumerate(sources):
    segs,info=model.transcribe(str(WORK/f'{i+1:02}-speech.wav'),language='en',beam_size=5,word_timestamps=True,vad_filter=True)
    segments=[{'start':s.start,'end':s.end,'text':s.text,'words':[{'start':w.start,'end':w.end,'word':w.word} for w in s.words or []]} for s in segs]
    (OUT/f'{i+1:02}-transcript.json').write_text(json.dumps({'source':p.name,'method':'faster-whisper base.en CPU int8; machine transcript, verify names against source','segments':segments},indent=2),encoding='utf-8')
    print(p.name,[(round(s['start'],2),round(s['end'],2),s['text']) for s in segments],flush=True)
