"""Render the supplied screen recording and captured phone UI for Descript.

Run from the repository root: py -3.11 beast/render-podcast-video.py
Requires FFmpeg/ffprobe. No app server, API, or model changes are made.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from farol.podcast import recording_plan

CACHE = ROOT / ".cache/podcast-production"
EXPORT = ROOT / "exports/podcast"
SOURCE = ROOT / "Recording 2026-09-19 215136.mp4"
CLEAN_OUTPUT = EXPORT / "RideEdge-Podcast-5m14s-1080p.mp4"
OUTPUT = EXPORT / "RideEdge-Podcast-5m14s-1080p-credited.mp4"
DURATION = 314
FPS = 30
CREDIT = "App coded & video created with OpenAI’s Astra"
INSERTS = [
    {"capture": "app-around", "start": 65, "duration": 19.5,
     "subtitle": "Actual app  /  Nearby > Metro > Places",
     "footer": "Saved city observations. Source status stays visible."},
    {"capture": "app-decision", "start": 169.5, "duration": 12.5,
     "subtitle": "Actual app  /  A simulated evening changes",
     "footer": "Bellevue to Kirkland. Fictional inputs, real Python calculations."},
]


def run(args: list[str]) -> None:
    subprocess.run(args, cwd=CACHE, check=True)


def probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def phone_clip(item: dict) -> Path:
    folder = CACHE / item["capture"]
    capture = json.loads((folder / "frames.json").read_text(encoding="utf-8"))
    frames = capture["frames"]
    first = frames[0]["time"]
    usable = capture["duration"] - first
    scale = item["duration"] / usable
    lines = ["ffconcat version 1.0"]
    for index, frame in enumerate(frames):
        end = frames[index + 1]["time"] if index + 1 < len(frames) else capture["duration"]
        duration = max(0.001, (end - frame["time"]) * scale)
        lines += [f"file '{(folder / frame['file']).as_posix()}'", f"duration {duration:.6f}"]
    lines.append(f"file '{(folder / frames[-1]['file']).as_posix()}'")
    manifest = folder / "capture.ffconcat"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    clip = CACHE / f"{item['capture']}.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-f", "concat", "-safe", "0",
         "-i", str(manifest), "-vf", "scale=448:896:flags=lanczos,setsar=1,fps=30",
         "-t", str(item["duration"]), "-an", "-c:v", "libx264", "-preset", "fast",
         "-crf", "16", "-pix_fmt", "yuv420p", "-threads", "4", str(clip)])
    return clip


def stamp(seconds: float) -> str:
    value = round(seconds)
    return f"{value // 60:02d}:{value % 60:02d}"


def credit_filter() -> str:
    (CACHE / "credit.txt").write_text(CREDIT, encoding="utf-8")
    # Replace only the existing left footer slogan, leaving the center context
    # label and scene count visible. Keep all scene timing unchanged.
    enabled = "lt(t,12)+gte(t,302)"
    return (
        f"drawbox=x=60:y=1015:w=710:h=48:color=0x0e1712:t=fill:enable='{enabled}',"
        "drawtext=fontfile=font.ttf:textfile=credit.txt:"
        f"x=70:y=1028:fontsize=23:fontcolor=0xd3deb9:enable='{enabled}'"
    )


def credit_existing() -> None:
    """Add the byline to the verified export without rebuilding the montage."""
    CACHE.mkdir(parents=True, exist_ok=True)
    EXPORT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path("C:/Windows/Fonts/segoeui.ttf"), CACHE / "font.ttf")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-i", str(CLEAN_OUTPUT),
         "-vf", credit_filter(), "-an", "-frames:v", str(DURATION * FPS),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-threads", "12",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-map_metadata", "0",
         "-metadata", f"comment={CREDIT}", str(OUTPUT)])
    verify_and_document()


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    EXPORT.mkdir(parents=True, exist_ok=True)
    metadata = probe(SOURCE)
    assert float(metadata["format"]["duration"]) >= 300, "Source recording is too short"
    shutil.copyfile(Path("C:/Windows/Fonts/segoeui.ttf"), CACHE / "font.ttf")
    (CACHE / "inset-title.txt").write_text("Inside RideEdge", encoding="utf-8")
    clips = [phone_clip(item) for item in INSERTS]
    ranges = [f"between(t,{item['start']},{item['start'] + item['duration']})" for item in INSERTS]
    enabled = "+".join(ranges)
    # The first five seconds contain the browser's fullscreen notification.
    # Hold the clean opening frame over that interval, preserving all cue offsets.
    # The source stage runs for 300 seconds; its extra closing hold is omitted.
    graph = [
        "[0:v]trim=start=5:end=300,setpts=PTS-STARTPTS,"
        "crop=2848:1602:8:154,scale=1920:1080:flags=lanczos,setsar=1,"
        "tpad=start_mode=clone:start_duration=5,setpts=PTS*314/300,"
        "fps=30,tpad=stop_mode=clone:stop_duration=1,trim=duration=314,split=2[full][small]",
        "[small]scale=1280:720:flags=lanczos,"
        "pad=1920:1080:48:180:color=0x09110d[layout]",
        f"[full][layout]overlay=0:0:enable='{enabled}'[base]",
    ]
    previous = "base"
    for index, item in enumerate(INSERTS, 1):
        (CACHE / f"subtitle-{index}.txt").write_text(item["subtitle"], encoding="utf-8")
        (CACHE / f"footer-{index}.txt").write_text(item["footer"], encoding="utf-8")
        graph += [
            f"[{index}:v]pad=460:908:6:6:color=0xb5c68c,"
            f"setpts=PTS-STARTPTS+{item['start']}/TB[phone{index}]",
            f"[{previous}][phone{index}]overlay=1390:86:eof_action=pass:repeatlast=0:"
            f"enable='{ranges[index-1]}'[inset{index}]",
            f"[inset{index}]drawtext=fontfile=font.ttf:textfile=subtitle-{index}.txt:"
            f"x=48:y=126:fontsize=27:fontcolor=0xc6d4b9:enable='{ranges[index-1]}',"
            f"drawtext=fontfile=font.ttf:textfile=footer-{index}.txt:"
            f"x=48:y=942:fontsize=25:fontcolor=0xb7c3b9:enable='{ranges[index-1]}'[text{index}]",
        ]
        previous = f"text{index}"
    graph.append(f"[{previous}]drawtext=fontfile=font.ttf:textfile=inset-title.txt:"
                 f"x=48:y=62:fontsize=44:fontcolor=0xe7efde:enable='{enabled}',"
                 f"{credit_filter()},format=yuv420p[out]")
    filterfile = CACHE / "render.ffgraph"
    filterfile.write_text(";\n".join(graph), encoding="utf-8")
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-i", str(SOURCE)]
    for clip in clips:
        args += ["-i", str(clip)]
    args += ["-filter_complex_threads", "2", "-filter_complex_script", str(filterfile),
             "-map", "[out]", "-an", "-frames:v", str(DURATION * FPS),
             "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-threads", "8",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-map_metadata", "-1",
             "-metadata", "title=RideEdge - podcast visual track - 32:32 to 37:46",
             "-progress", str(CACHE / "render-progress.txt"), "-stats_period", "2", str(OUTPUT)]
    print(f"Rendering {OUTPUT}", flush=True)
    run(args)
    verify_and_document()


def verify_and_document() -> None:
    result = probe(OUTPUT)
    streams = result["streams"]
    assert len(streams) == 1 and streams[0]["codec_type"] == "video", "Export must be silent"
    video = streams[0]
    assert (video["width"], video["height"]) == (1920, 1080)
    assert video["avg_frame_rate"] == "30/1"
    assert int(video["nb_frames"]) == 9420
    assert abs(float(result["format"]["duration"]) - DURATION) < 0.001
    (EXPORT / "media-verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    cues = recording_plan()["cues"]
    timeline = {"duration_seconds": DURATION, "podcast_start": "32:32", "podcast_end": "37:46",
                "timing": "evenly paced from transcript word positions; not speech-aligned",
                "credit": {"text": CREDIT, "windows_seconds": [[0, 12], [302, 314]]},
                "inserts": INSERTS, "cues": [dict(cue, seconds=round(cue["fraction"] * DURATION, 3)) for cue in cues]}
    (EXPORT / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    guide = ["# RideEdge video for Descript", "",
             f"Use **{OUTPUT.name}**. It is exactly **5:14**, 1920 x 1080, 30 fps, H.264.",
             "It contains no audio track. Keep your podcast audio, including Co-host's section, as recorded.", "",
             f"Opening and closing footer credit: **{CREDIT}** (first and last 12 seconds).", "",
             "1. Import the MP4 into your Descript project.",
             "2. Add it as a visual layer starting at **32:32** on the episode timeline.",
             "3. Keep playback at **1x / 100%**, with the full clip ending at **37:46**.",
             "4. Fit it to the 16:9 canvas. No extra crop, speed adjustment, or audio mute is needed.", "",
             "The visuals follow the supplied transcript in order and are paced proportionally by word position.",
             "They are not aligned to individual spoken words. This matches the requested even pacing.", "",
             "Two short side-by-side inserts show the actual app:", "",
             "- **Clip 1:05-1:24.5 / episode 33:37-33:56.5:** Nearby, Metro, then Places. Saved observations and missing live data remain labeled.",
             "- **Clip 2:49.5-3:02 / episode 35:21.5-35:34:** Advance a simulated evening from Bellevue to Kirkland. Fictional inputs remain labeled.", "",
             "The original screen recording is unchanged. The export removes the surrounding letterboxing and browser startup notification.",
             "The phone inserts use sampled screenshots of real browser interactions, held between updates.", "",
             "## Approximate spoken cue positions", "", "| Clip | Episode | Topic |", "| --- | --- | --- |"]
    for cue in cues:
        t = cue["fraction"] * DURATION
        guide.append(f"| {stamp(t)} | {stamp(t + 1952)} | {cue['title']} |")
    (EXPORT / "DESCRIPT-PLACEMENT.md").write_text("\n".join(guide) + "\n", encoding="utf-8")
    for second, filename in [(0, "opening.png"), (73, "app-insert-preview.png"),
                             (180, "decision-insert-preview.png"), (210, "cohost-section.png"),
                             (313, "ending.png")]:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(second), "-i", str(OUTPUT),
             "-frames:v", "1", "-update", "1", str(EXPORT / filename)])
    print("Verified: 314.000 seconds; 9420 frames; 1920x1080; 30 fps; no audio.", flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--verify-only"]:
        verify_and_document()
    elif sys.argv[1:] == ["--credit-existing"]:
        credit_existing()
    else:
        main()
