"""Read-only recording companion: transcript cues and isolated app calculations."""
from __future__ import annotations

import json
from pathlib import Path

from farol.rideedge import Constraints, compare, scenario

ROOT = Path(__file__).resolve().parents[1]
# Exact phrases in the supplied transcript, in the original recorded order.
CUES = [
    ("intro", "The driving question", "I'm gonna showcase", "intro"),
    ("hotspots", "Everyone sees the hotspot", "Uber will tell you where the hotspot is", "hotspots"),
    ("data", "A city full of data", "It is amazing how much data is out there", "sources"),
    ("around", "What's around me?", "I've actually created an app", "around"),
    ("collect", "workstation collects the context", "I have this machine literally sitting right behind me", "sources"),
    ("reasoning", "From context to a comparison", "Now, the th- problem is", "working"),
    ("gemma", "Speed versus the task", "the Gemma model from Google", "models"),
    ("qwen", "Why I chose Qwen", "Qwen, on the other hand", "models"),
    ("decision", "Where should I go next?", "And so what it does is", "changed"),
    ("cohost", "The settings matter", "gonna  point out as you're talking", "tuning"),
    ("local", "Local AI, on the phone", "Well,  and I'll finish the story", "architecture"),
    ("flight", "Airport arrivals add context", "like I do FlightAware", "airport"),
    ("transit", "Transit adds context", "You know, I'm even scraping", "transit"),
    ("ending", "The real-world experiment", "whether it's valuable, I don't know yet", "ending"),
]


def recording_plan(transcript: str | None = None) -> dict:
    text = transcript if transcript is not None else (ROOT / "Uber App Text.txt").read_text(encoding="utf-8-sig")
    words = len(text.split())
    if not words:
        raise ValueError("Podcast transcript is empty")
    cues, previous = [], -1
    for cue_id, title, quote, view in CUES:
        offset = text.find(quote)
        if offset < 0 or offset <= previous:
            raise ValueError(f"Podcast transcript cue missing or out of order: {cue_id}")
        previous = offset
        cues.append({"id": cue_id, "title": title, "quote": quote, "view": view,
                     "fraction": len(text[:offset].split()) / words})
    states = []
    for step in (0, 1):
        context = scenario(step)
        states.append({"context": context, "comparison": compare(context, Constraints())})
    return {"version": 1, "word_count": words, "timing": "estimated_from_word_position",
            "default_duration": 300, "cues": cues, "states": states,
            "model_checks": saved_model_checks()}


def saved_model_checks() -> list[dict]:
    path = ROOT / ".cache" / "simulations" / "20260918T043953Z" / "comparison.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))["models"]
        # Never publish prompts, raw model text, credentials, or endpoint URLs.
        return [{"model": row["model"], "profile": row["profile"],
                 "passed": row["passed"], "total": row["total"],
                 "guarded_passed": row["guarded_passed"]} for row in rows]
    except (OSError, ValueError, KeyError, TypeError):
        return []
