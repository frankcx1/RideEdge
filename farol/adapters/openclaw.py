"""Ingest schema-validated JSON that OpenClaw jobs write.

OpenClaw (Chrome extension + cron) is optional and stays outside scoring.
Jobs drop files into signals/; this adapter turns them into Signal rows.
Invalid JSON is skipped, never takes down the brief.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from farol.adapters.base import FeedStatus
from farol.dashboard import ROOT
from farol.signals import Signal
from farol.zones import canonical_zone

NAME = "openclaw_drop"
SOURCE = "signals/openclaw*.json"
REQUIRED = {
    "id",
    "kind",
    "zone",
    "starts_at",
    "ends_at",
    "magnitude",
    "basis",
    "source",
    "fetched_at",
    "expires_at",
    "evidence_quality",
}
ALLOWED_KIND = {
    "closing_wave",
    "event_exit",
    "special_event",
    "airport_arrivals",
    "cruise_disembark",
    "driver_intel",
    "rate_card",
    "supply",
    "precipitation",
}


def signals_dir() -> Path:
    return ROOT / "signals"


def parse_file(path: Path, window_start: datetime, window_end: datetime) -> list[Signal]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = payload.get("signals") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    out: list[Signal] = []
    for item in rows:
        if not isinstance(item, dict) or not REQUIRED.issubset(item):
            continue
        if item.get("kind") not in ALLOWED_KIND:
            continue
        if item.get("basis") not in {"scheduled", "live", "assumed"}:
            continue
        try:
            starts = datetime.fromisoformat(str(item["starts_at"]))
            ends = datetime.fromisoformat(str(item["ends_at"]))
            quality = float(item["evidence_quality"])
            magnitude = float(item["magnitude"])
        except (TypeError, ValueError):
            continue
        if ends < window_start or starts > window_end:
            continue
        kind = item["kind"]
        if kind in {"rate_card", "supply"}:
            kind = "driver_intel"
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        out.append(
            Signal(
                id=str(item["id"])[:80],
                kind=kind,
                zone=canonical_zone(str(item["zone"])),
                starts_at=starts.isoformat(),
                ends_at=ends.isoformat(),
                magnitude=max(0.0, magnitude),
                basis=item["basis"],
                source=str(item["source"])[:300],
                fetched_at=str(item["fetched_at"]),
                expires_at=str(item["expires_at"]),
                evidence_quality=max(0.1, min(0.9, quality)),
                details=details,
            )
        )
    return out


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    directory = signals_dir()
    if not directory.is_dir():
        return [], FeedStatus(NAME, "static", SOURCE, None, 0, "no signals/ drop folder yet")
    files = sorted(directory.glob("openclaw*.json"))
    signals: list[Signal] = []
    for path in files:
        signals.extend(parse_file(path, window_start, window_end))
    detail = f"{len(files)} drop file(s)" if files else "folder empty; OpenClaw job has not written yet"
    return signals, FeedStatus(NAME, "static", SOURCE, None, len(signals), detail)
