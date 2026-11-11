"""Named venue last-call harvests (bars, clubs, late restaurants).

Hours start from fixtures/venues.json (Places-backed Eastside list) and are
overlaid by the Google Places adapter when MOCK_FEEDS=0. Harvest is the window
around close. WA last call is 02:00.
"""

from datetime import datetime, timedelta
from pathlib import Path
import json

from farol.adapters.base import FeedStatus
from farol.dashboard import FIXTURES
from farol.signals import Signal

NAME = "venue_hours"
SOURCE = "fixtures/venues.json"
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def load_venues(path: Path | None = None) -> list[dict]:
    payload = json.loads((path or FIXTURES / "venues.json").read_text(encoding="utf-8"))
    return list(payload.get("venues") or [])


def _close_clock(day: datetime, close_hhmm: str) -> datetime:
    hour, minute = (int(part) for part in close_hhmm.split(":"))
    point = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if hour < 12:
        point += timedelta(days=1)
    return point


def parse(
    window_start: datetime, window_end: datetime, *, fetched_at: str, venues: list[dict] | None = None
) -> list[Signal]:
    tz = window_start.tzinfo
    # Start yesterday so a 01:10 query still sees Friday night's 02:00 last call.
    day = datetime(window_start.year, window_start.month, window_start.day, tzinfo=tz) - timedelta(days=1)
    last = datetime(window_end.year, window_end.month, window_end.day, tzinfo=tz)
    signals: list[Signal] = []
    for venue in venues if venues is not None else load_venues():
        close_map = venue.get("close") or {}
        before = int(venue.get("harvest_minutes_before") or 45)
        after = int(venue.get("harvest_minutes_after") or 30)
        cursor = day
        while cursor <= last:
            key = WEEKDAYS[cursor.weekday()]
            close_hhmm = close_map.get(key)
            if close_hhmm:
                close_at = _close_clock(cursor, close_hhmm)
                starts = close_at - timedelta(minutes=before)
                ends = close_at + timedelta(minutes=after)
                if not (ends < window_start or starts > window_end):
                    signals.append(
                        Signal(
                            id=f"venue-{venue['id']}-{cursor.date().isoformat()}",
                            kind="closing_wave",
                            zone=venue["zone"],
                            starts_at=starts.isoformat(),
                            ends_at=ends.isoformat(),
                            magnitude=float(venue.get("magnitude") or 3),
                            basis=venue.get("basis") or "scheduled",
                            source=str(venue.get("source") or SOURCE),
                            fetched_at=fetched_at,
                            expires_at=ends.isoformat(),
                            evidence_quality=float(venue.get("evidence_quality") or 0.6),
                            details={
                                "title": f"{venue['name']} last-call harvest (closes {close_hhmm})",
                                "venue_id": venue["id"],
                                "close_at": close_at.isoformat(),
                                "notes": venue.get("notes") or "",
                                "state_service_boundary": "02:00",
                            },
                        )
                    )
            cursor += timedelta(days=1)
    return signals


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    venues = load_venues()
    fetched_at = window_start.isoformat()
    signals = parse(window_start, window_end, fetched_at=fetched_at, venues=venues)
    return signals, FeedStatus(
        NAME,
        "static",
        SOURCE,
        fetched_at,
        len(signals),
        f"{len(venues)} named venues; last-call harvest windows",
    )
