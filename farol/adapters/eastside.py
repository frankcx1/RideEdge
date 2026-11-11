"""Eastside operating doctrine: staggered closing harvest and SEA morning banks.

These are scheduled/assumed standing windows until Google Places hours and a
live airport feed exist. They keep Kirkland / Bellevue / Redmond / Woodinville
/ SEA on the brief even when event calendars are quiet.
"""

from datetime import datetime, timedelta

from farol.adapters.base import FeedStatus
from farol.signals import Signal

NAME = "eastside_doctrine"
SOURCE = "farol:eastside doctrine"

# Spec cascade: Redmond then Bellevue/Woodinville then Kirkland closer.
# Weekend nights run later and denser than Sun-Thu.
WEEKEND_CLOSINGS = (
    ("redmond_downtown", "21:00", "23:00", 4.0, "Redmond downtown closing wave"),
    ("bellevue_core", "22:00", "00:15", 5.0, "Bellevue core closing wave"),
    ("woodinville_wine", "21:30", "23:30", 3.0, "Woodinville tasting-room close"),
    ("kirkland_waterfront", "00:45", "02:15", 5.0, "Kirkland last-call closer"),
)
WEEKNIGHT_CLOSINGS = (
    ("redmond_downtown", "20:30", "22:30", 3.0, "Redmond downtown closing wave"),
    ("bellevue_core", "21:30", "23:30", 4.0, "Bellevue core closing wave"),
    ("woodinville_wine", "20:30", "22:30", 2.0, "Woodinville tasting-room close"),
    ("kirkland_waterfront", "00:45", "02:15", 4.0, "Kirkland last-call closer"),
)
# Spec airport_express: Tue/Thu 04:45-09:30.
AIRPORT_WEEKDAYS = {1, 3}  # Tuesday, Thursday
AIRPORT_START = (4, 45)
AIRPORT_END = (9, 30)
AIRPORT_MAGNITUDE = 8.0


def _at(day: datetime, hour: int, minute: int) -> datetime:
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _clock(day: datetime, text: str) -> datetime:
    hour, minute = (int(part) for part in text.split(":"))
    point = _at(day, hour, minute)
    # Clocks before 06:00 are the morning after an evening cascade (WA last call is 02:00).
    if hour < 6:
        point = _at(day + timedelta(days=1), hour, minute)
    return point


def parse(window_start: datetime, window_end: datetime, *, fetched_at: str) -> list[Signal]:
    tz = window_start.tzinfo
    signals: list[Signal] = []
    day = datetime(window_start.year, window_start.month, window_start.day, tzinfo=tz) - timedelta(days=1)
    last = datetime(window_end.year, window_end.month, window_end.day, tzinfo=tz)
    while day <= last:
        weekend = day.weekday() >= 4
        cascade = WEEKEND_CLOSINGS if weekend else WEEKNIGHT_CLOSINGS
        for zone, start_clock, end_clock, magnitude, title in cascade:
            starts = _clock(day, start_clock)
            ends = _clock(day, end_clock)
            if ends < window_start or starts > window_end:
                continue
            signals.append(
                Signal(
                    id=f"eastside-close-{zone}-{day.date().isoformat()}",
                    kind="closing_wave",
                    zone=zone,
                    starts_at=starts.isoformat(),
                    ends_at=ends.isoformat(),
                    magnitude=magnitude,
                    basis="assumed",
                    source=SOURCE,
                    fetched_at=fetched_at,
                    expires_at=ends.isoformat(),
                    evidence_quality=0.4,
                    details={
                        "title": title,
                        "timing_basis": "doctrine staggered close; Google Places not wired",
                        "state_service_boundary": "02:00",
                    },
                )
            )
        if day.weekday() in AIRPORT_WEEKDAYS:
            starts = _at(day, *AIRPORT_START)
            ends = _at(day, *AIRPORT_END)
            if not (ends < window_start or starts > window_end):
                signals.append(
                    Signal(
                        id=f"eastside-sea-{day.date().isoformat()}",
                        kind="airport_arrivals",
                        zone="sea_airport",
                        starts_at=starts.isoformat(),
                        ends_at=ends.isoformat(),
                        magnitude=AIRPORT_MAGNITUDE,
                        basis="assumed",
                        source=SOURCE,
                        fetched_at=fetched_at,
                        expires_at=ends.isoformat(),
                        evidence_quality=0.35,
                        details={
                            "title": "SEA morning arrival banks (Tue/Thu doctrine)",
                            "timing_basis": "doctrine airport_express 04:45-09:30",
                        },
                    )
                )
        day += timedelta(days=1)
    return signals


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    fetched_at = window_start.isoformat()
    signals = parse(window_start, window_end, fetched_at=fetched_at)
    return signals, FeedStatus(
        NAME,
        "static",
        SOURCE,
        fetched_at,
        len(signals),
        "staggered Eastside close + Tue/Thu SEA morning window",
    )
