from pathlib import Path
import subprocess
from PIL import Image, ImageDraw
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'recordings/podcast/edit-v1/work'
sources={
 'dashboard':('recordings/rideedge-studio-clickthrough-20261106-take2/studio-clickthrough-1080p.mp4',[0,8,16,25,33,38,44,50]),
 'phone':('recordings/rideedge-tour-20261103-163324-0d023d/phone-feature-edit.mp4',[2,22,42,62,69,82,90,151]),
 'volvo':('recordings/androidauto.mp4',[2,5,8,11,14,17,20,24,26]),
}
for name,(src,times) in sources.items():
    sheet=Image.new('RGB',(1280,390*((len(times)+1)//2)),'#09131d')
    for j,t in enumerate(times):
        p=OUT/f'{name}-{t}.jpg'
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(ROOT/src),'-frames:v','1','-vf','scale=640:360:force_original_aspect_ratio=decrease',str(p)],check=True)
        im=Image.open(p);x=(j%2)*640;y=(j//2)*390
        sheet.paste(im,(x+(640-im.width)//2,y))
        ImageDraw.Draw(sheet).text((x+10,y+367),f'{name} source {t}s',fill='white')
    sheet.save(OUT/f'{name}-sheet.jpg')
