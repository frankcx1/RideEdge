"""Capture matching Preview phone/DHU shots. No providers, live navigation or model calls."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid


class Recorder:
    def __init__(self, adb, device):
        self.base = [str(adb), '-s', device]

    def adb(self, *args, timeout=20):
        return subprocess.check_output([*self.base, *args], text=True, encoding='utf-8', errors='replace', timeout=timeout)

    def require_preview_foreground(self):
        activity = self.adb('shell', 'dumpsys', 'activity', 'activities')
        if not re.search(r'topResumedActivity=.*com\.rideedge\.app\.preview/com\.rideedge\.app\.MainActivity', activity):
            raise RuntimeError('Keep RideEdge Preview open in the foreground. The normal RideEdge app is a separate app.')

    def control(self, command, shot=None, clean=None):
        args = ['shell', 'am', 'broadcast', '-n', 'com.rideedge.app.preview/com.rideedge.app.RecordingTourReceiver',
                '--es', 'command', command]
        if shot is not None:
            args += ['--ei', 'shot', str(shot)]
        if clean is not None:
            args += ['--ez', 'clean', str(clean).lower()]
        result = self.adb(*args)
        match = re.search(r'Broadcast completed: result=0, data="(.*)"', result)
        if not match:
            raise RuntimeError('Recording Preview is not ready. Open it on the unlocked phone first. ' + result[-200:])
        return json.loads(match[1])

    def ready(self, index, require_car, timeout=12):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            status = self.control('status')
            if status.get('error'):
                raise RuntimeError(status['error'])
            revision = status['revision']
            if status['index'] == index and status['phone_revision'] == revision and (
                    not require_car or (status['car_connected'] and status['car_revision'] == revision)):
                return status
            time.sleep(.4)
        raise RuntimeError('Shot did not reach both requested surfaces. Check Preview on the phone and DHU; no successful take claimed.')


def normalize_phone_clip(ffmpeg, source, target, seconds):
    """Android emits frames on change; retain the intended final static hold."""
    with target.with_suffix('.encode.log').open('w', encoding='utf-8') as log:
        subprocess.run([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'warning', '-i', str(source),
            '-map', '0:v:0', '-an', '-vf', f'tpad=stop_mode=clone:stop_duration={seconds},fps=30',
            '-t', str(seconds), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-threads', '4',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(target)],
            stdout=log, stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default=r'C:\Android\Sdk\platform-tools\adb.exe')
    parser.add_argument('--device')
    parser.add_argument('--dhu-title', help='Exact visible DHU window title; mandatory unless --phone-only')
    parser.add_argument('--dhu-video-size', help='Verified DHU client capture size, e.g. 1280x720, for Windows display scaling')
    parser.add_argument('--phone-only', action='store_true')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--start-shot', type=int, default=0)
    parser.add_argument('--end-shot', type=int)
    parser.add_argument('--output', default='recordings')
    args = parser.parse_args()
    devices = subprocess.check_output([args.adb, 'devices'], text=True)
    ready = re.findall(r'^(\S+)\s+device$', devices, re.M)
    device = args.device or (ready[0] if len(ready) == 1 else None)
    if device not in ready:
        parser.error('Choose exactly one authorized phone with --device.')
    if not args.phone_only and not args.dhu_title:
        parser.error('Supply --dhu-title or explicitly select --phone-only.')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        parser.error('FFmpeg must be available to preserve phone hold times and assemble the tracks.')
    recorder = Recorder(args.adb, device)
    info = recorder.control('status')
    recorder.require_preview_foreground()
    cues = info['cues']
    if args.end_shot is None:
        args.end_shot = len(cues) - 1
    if not 0 <= args.start_shot <= args.end_shot < len(cues):
        parser.error('Shot range must be inside the tour, using zero-based indexes.')
    if not args.phone_only and not info['car_connected']:
        parser.error('Connect the DHU and select RideEdge Preview before recording.')
    if args.check_only:
        print(json.dumps({'shots': len(cues), 'seconds': sum(c['seconds'] for c in cues),
                         'car_connected': info['car_connected'], 'preview_ready': True}))
        return
    output = Path(args.output).resolve() / ('rideedge-tour-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
    output.mkdir(parents=True, exist_ok=False)
    (output / 'cues.json').write_text(json.dumps(cues, indent=2), encoding='utf-8')
    receipts = []
    try:
        recorder.control('pause', clean=True)
        for i in range(args.start_shot, args.end_shot+1):
            recorder.require_preview_foreground()
            cue = cues[i]
            name = f"{i+1:02d}-scene-{cue['scene']}-{cue['shot']}"
            print(f"Recording {name}: {cue['title']}", flush=True)
            remote = '/sdcard/rideedge-tour-' + uuid.uuid4().hex + '.mp4'
            # Capture before the cue so the edit includes the real UI transition.
            phone_log = (output / (name + '-phone.log')).open('w', encoding='utf-8')
            phone = subprocess.Popen([*recorder.base, 'shell', 'screenrecord', '--bit-rate', '12000000',
                '--size', '1080x2400', '--time-limit', str(cue['seconds']), remote], stdout=phone_log, stderr=subprocess.STDOUT)
            car = None
            car_log = None
            started = time.monotonic()
            try:
                if not args.phone_only:
                    car_log = (output / (name + '-car.log')).open('w', encoding='utf-8')
                    car = subprocess.Popen([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'warning',
                        '-f', 'gdigrab', '-framerate', '30', '-draw_mouse', '0',
                        *(['-video_size', args.dhu_video_size] if args.dhu_video_size else []), '-i', 'title='+args.dhu_title,
                        '-t', str(cue['seconds']), '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
                        '-pix_fmt', 'yuv420p', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', str(output/(name+'-car.mp4'))],
                        stdout=car_log, stderr=subprocess.STDOUT)
                time.sleep(.6)
                if phone.poll() is not None or (car and car.poll() is not None):
                    raise RuntimeError('Capture exited early. Inspect this take’s logs; keep the DHU visible and unobscured.')
                recorder.control('seek', shot=i)
                status = recorder.ready(i, not args.phone_only)
                if status.get('capture_id') != info.get('capture_id'):
                    raise RuntimeError('The captured session changed during recording; completed takes are preserved.')
                ready_after = round(time.monotonic()-started, 3)
                phone.wait(timeout=cue['seconds']+15)
                if car:
                    car.wait(timeout=15)
                if phone.returncode or (car and car.returncode):
                    raise RuntimeError('Capture failed; inspect the logs. Completed earlier shots are preserved.')
                raw_phone = output/(name+'-phone-raw.mp4')
                recorder.adb('pull', remote, str(raw_phone), timeout=120)
                recorder.adb('shell', 'rm', remote)  # Exact random temporary file owned by this take.
                normalize_phone_clip(ffmpeg, raw_phone, output/(name+'-phone.mp4'), cue['seconds'])
                receipts.append({'shot': i, 'name': name, 'title': cue['title'], 'seconds': cue['seconds'],
                                 'ready_after_seconds': ready_after, 'phone_revision': status['phone_revision'],
                                 'capture_id': status.get('capture_id'), 'snapshot_id': status.get('snapshot_id'),
                                 'car_revision': status['car_revision'] if car else None})
                (output/'takes.json').write_text(json.dumps(receipts, indent=2), encoding='utf-8')
                print(f"Saved {name}", flush=True)
            finally:
                # Only the child processes created above; screenrecord is bounded on-device.
                for process in (phone, car):
                    if process and process.poll() is None:
                        process.terminate()
                phone_log.close()
                if car_log:
                    car_log.close()
    finally:
        recorder.control('pause', clean=False)
    # Also provide continuous tracks; retain every original shot for easy retakes.
    if ffmpeg:
        for surface in (['phone'] if args.phone_only else ['phone', 'car']):
            playlist = output / (surface + '-concat.txt')
            playlist.write_text(''.join("file '"+r['name']+'-'+surface+".mp4'\n" for r in receipts), encoding='utf-8')
            with (output / (surface + '-assembly.log')).open('w') as log:
                subprocess.run([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'warning', '-f', 'concat',
                    '-safe', '0', '-i', str(playlist), '-c', 'copy', str(output/(surface+'-full.mp4'))],
                    stdout=log, stderr=subprocess.STDOUT, check=True)
    (output/'EDITING.md').write_text('''# RideEdge capture takes

Phone and car MP4s are separate, silent tracks. Match them by numbered filename.
The *-full.mp4 files concatenate the corresponding original clips without re-encoding.
Phone *-raw.mp4 files retain the original Android capture. The editable phone clips
use 30 fps and extend the final recorded frame to preserve the planned static hold.
Each starts before the cue; takes.json records when both requested UIs acknowledged
the cue. Use that as an alignment guide, not a frame-accurate hardware sync claim.
Shot count and duration follow the app's active cue list. Keep original files;
assemble selected takes in your editor with narration and B-roll.
The real Google Maps handoff is a separate manual take; its route can reveal
the phone's actual starting location.
''', encoding='utf-8')
    with (output/'EDITING.md').open('a', encoding='utf-8') as notes:
        notes.write(('\nCaptured real evaluation: ' + info['capture_id'] + '\nSnapshot: ' + str(info.get('snapshot_id'))
                     + '\nOriginal evidence and inference timestamps are retained. No passenger trips were observed.\n')
                    if info.get('capture_id') else '\nAuthored Friday UI rehearsal; no real model evaluation.\n')
    print(f"Saved {len(receipts)} matching takes to {output}", flush=True)


if __name__ == '__main__':
    main()
