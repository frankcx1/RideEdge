"""Unverified standing positioning assumptions, not dated provider schedules.

The retained rules describe possible hospital/office activity and transit cutoffs.
Their windows and old magnitudes are not observations. Transit cutoff assumptions
remain context until a separate source supplies dated service evidence.
"""

from __future__ import annotations

import copy
from dataclasses import asdict
from datetime import datetime, timedelta

from farol.adapters.base import FeedStatus
from farol.signals import Signal

NAME = "situational_demand_waves"
SOURCE = "farol:situational demand waves (Link cutoffs, hospitals, conventions)"

ASSUMPTION_NOTE = (
    "Unverified standing rule; this window is a positioning assumption, not a dated schedule, "
    "observed departure, passenger count or confirmed ride demand."
)


def review_record(record: dict) -> dict:
    """Correct this source's retained labels in memory, preserving reported values."""
    if record.get("source") != SOURCE:
        return record
    reviewed = copy.deepcopy(record)
    details = reviewed.setdefault("details", {})
    if "assumption_review" not in details:
        details["assumption_review"] = {
            "method": "standing-rule-v1", "reported_basis": record.get("basis"),
            "reported_magnitude": record.get("magnitude"),
            "reported_title": details.get("title"), "reported_notes": details.get("notes"),
        }
    original = details["assumption_review"]
    details["title"] = "Unverified local assumption: " + str(original.get("reported_title") or "activity window")
    details["notes"] = ASSUMPTION_NOTE
    details["magnitude_unit"] = "unavailable; no passenger or crowd measurement"
    if record.get("kind") == "transit_disruption":
        details["context_only"] = True
        details["notes"] += " Last departure and service disruption require dated transit evidence."
    reviewed.update(basis="assumed", magnitude=0.0, evidence_quality=0.2)
    return reviewed

# (zone, start_hhmm, end_hhmm, kind, magnitude, venue, title, notes, weekdays_or_None)
STANDING_WAVES: tuple[tuple[str, str, str, str, float, str, str, str, set[int] | None], ...] = (
    # 1. Sound Transit Link Last-Train Stranded-Rider Cliffs
    (
        "bellevue_core",
        "23:15",
        "00:15",
        "transit_disruption",
        11.5,
        "Bellevue Downtown Station (2 Line)",
        "Link 2 Line last-train cutoff at Downtown Bellevue",
        "Eastside 2 Line service ends for the night; late diners and bar patrons without cars switch to Uber.",
        None,
    ),
    (
        "redmond_downtown",
        "23:00",
        "00:00",
        "transit_disruption",
        10.5,
        "Redmond Technology / Downtown Station (2 Line)",
        "Link 2 Line last-train cutoff at Redmond",
        "Final Eastside 2 Line trains depart; stranded riders request rideshare home.",
        None,
    ),
    (
        "capitol_hill",
        "00:45",
        "01:45",
        "transit_disruption",
        12.5,
        "Capitol Hill Link Station (Broadway & E John)",
        "Link 1 Line last-train cutoff at Capitol Hill",
        "Final 1 Line trains depart before 2:00 AM bar close; rideshare becomes the only cross-town and Eastside option.",
        None,
    ),
    (
        "uw_district",
        "00:45",
        "01:45",
        "transit_disruption",
        11.5,
        "U District & UW Link Stations",
        "Link 1 Line last-train cutoff at U-District / UW",
        "Final late-night 1 Line trains depart; students and The Ave/Greek Row riders switch to Uber.",
        None,
    ),
    # 2. Hospital 12-Hour Shift Changes (06:45-07:45 & 18:45-19:45)
    (
        "seattle_core",
        "06:45",
        "07:45",
        "special_event",
        11500.0,
        "First Hill Medical Hub (Swedish / Harborview / Virginia Mason)",
        "First Hill hospital 7:00 AM shift change & staff wave",
        "12-hour nursing and medical staff shift turnover across Swedish, Harborview, and Virginia Mason.",
        None,
    ),
    (
        "seattle_core",
        "18:45",
        "19:45",
        "special_event",
        12000.0,
        "First Hill Medical Hub (Swedish / Harborview / Virginia Mason)",
        "First Hill hospital 7:00 PM shift change & discharge wave",
        "Evening 12-hour medical shift change and visitor/outpatient departures on Pill Hill.",
        None,
    ),
    (
        "bellevue_core",
        "18:45",
        "19:45",
        "special_event",
        11500.0,
        "Overlake Medical Center (Bellevue)",
        "Overlake Hospital 7:00 PM shift change wave",
        "Evening nursing/staff turnover and visitor departures near NE 8th St & I-405.",
        None,
    ),
    (
        "totem_lake",
        "18:45",
        "19:45",
        "special_event",
        11500.0,
        "EvergreenHealth Medical Center (Totem Lake)",
        "EvergreenHealth 7:00 PM hospital shift change wave",
        "Evening 12-hour medical shift turnover right in the Totem Lake area.",
        None,
    ),
    # 3. Convention Center & Corporate RTO Evening Discharges (Weekdays)
    (
        "seattle_core",
        "16:30",
        "18:30",
        "special_event",
        13500.0,
        "Seattle Convention Center (Summit & Arch) / SLU",
        "Convention Center & SLU corporate evening discharge wave",
        "Conference session let-out and SLU tech RTO commute window; expense-account rides to restaurants, hotels, and SEA.",
        {0, 1, 2, 3, 4},
    ),
    (
        "bellevue_core",
        "16:30",
        "18:30",
        "special_event",
        13000.0,
        "Meydenbauer Center & Downtown Bellevue Towers",
        "Bellevue corporate & Meydenbauer conference dinner/airport wave",
        "Afternoon conference discharge and downtown office towers heading to Lincoln Square dining or Sea-Tac.",
        {0, 1, 2, 3, 4},
    ),
    (
        "redmond_downtown",
        "16:30",
        "18:30",
        "special_event",
        12000.0,
        "Redmond Technology Campus",
        "Redmond tech RTO evening commuter wave",
        "Tue–Thu campus commute window; strong Eastside and Seattle-bound rideshare trips.",
        {1, 2, 3},
    ),
)


def _clock(day: datetime, hhmm: str) -> datetime:
    hour, minute = (int(part) for part in hhmm.split(":"))
    point = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if hour < 5:
        point = (day + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
    return point


def parse(window_start: datetime, window_end: datetime, *, fetched_at: str) -> list[Signal]:
    tz = window_start.tzinfo
    signals: list[Signal] = []
    day = datetime(window_start.year, window_start.month, window_start.day, tzinfo=tz) - timedelta(
        days=1
    )
    last = datetime(window_end.year, window_end.month, window_end.day, tzinfo=tz)
    while day <= last:
        weekday = day.weekday()
        for zone, start_hm, end_hm, kind, _mag, venue, title, notes, allowed_days in STANDING_WAVES:
            if allowed_days is not None and weekday not in allowed_days:
                continue
            starts = _clock(day, start_hm)
            ends = _clock(day, end_hm)
            if ends < window_start or starts > window_end:
                continue
            slug = f"{zone}-{start_hm.replace(':', '')}-{day.date().isoformat()}"
            signals.append(
                Signal(
                    id=f"situational-{slug}",
                    kind=kind,
                    zone=zone,
                    starts_at=starts.isoformat(),
                    ends_at=ends.isoformat(),
                    magnitude=0.0,
                    basis="assumed",
                    source=SOURCE,
                    fetched_at=fetched_at,
                    expires_at=ends.isoformat(),
                    evidence_quality=0.65,
                    details={
                        "title": title,
                        "venue": venue,
                        "notes": notes,
                    },
                )
            )
        day += timedelta(days=1)
    return [Signal(**review_record(asdict(signal))) for signal in signals]


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    fetched_at = window_start.isoformat()
    signals = parse(window_start, window_end, fetched_at=fetched_at)
    return signals, FeedStatus(
        NAME,
        "static",
        SOURCE,
        fetched_at,
        len(signals),
        f"{len(signals)} unverified local assumption window(s); no dated schedules or crowd observations",
    )
