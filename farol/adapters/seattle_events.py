"""Seattle special-event permits adapter (data.seattle.gov, Socrata). Keyless.

The permit feed carries dates, neighborhoods, and attendance but no time of
day, so signals cover the whole permitted day at reduced evidence quality.
The city has let this dataset go stale before; the status reports the newest
permit on file so staleness is visible instead of silent.
"""

import re
from datetime import datetime, timedelta
from urllib.parse import quote

from farol.adapters.base import FeedError, FeedStatus, fetch_json
from farol.signals import Signal
from farol.zones import canonical_zone

NAME = "seattle_special_events"
SOURCE = "seattle:data.seattle.gov dm95-f8w5"
RESOURCE = "https://data.seattle.gov/resource/dm95-f8w5.json"
TTL_SECONDS = 12 * 60 * 60

NEIGHBORHOOD_ZONES = {
    "capitol hill": "capitol_hill",
    "belltown": "belltown",
    "downtown": "downtown",
    "pioneer square": "pioneer_square",
    "first hill": "first_hill",
    "south lake union": "south_lake_union",
    "fremont": "fremont",
    "ballard": "ballard",
    "wallingford": "wallingford",
    "green lake": "green_lake",
    "queen anne": "seattle_center",
    "uptown": "seattle_center",
    "seattle center": "seattle_center",
    "sodo": "sodo_stadiums",
    "stadium district": "sodo_stadiums",
}


def zone_for_neighborhood(raw: str) -> str:
    parts = [part.strip() for part in re.split(r"[;/]", raw or "") if part.strip()]
    for part in parts:
        mapped = NEIGHBORHOOD_ZONES.get(part.lower())
        if mapped:
            return canonical_zone(mapped)
    first = parts[0] if parts else "unknown"
    return canonical_zone(re.sub(r"[^a-z0-9]+", "_", first.lower()).strip("_") or "unknown")


def _query_url(window_start: datetime, window_end: datetime) -> str:
    start = window_start.date().isoformat()
    end = window_end.date().isoformat()
    where = (
        f"event_end_date >= '{start}' AND event_start_date <= '{end}' "
        "AND permit_status != 'Cancelled'"
    )
    return f"{RESOURCE}?$where={quote(where)}&$limit=200"


def parse(
    payload: list, window_start: datetime, window_end: datetime, *, fetched_at: str
) -> list[Signal]:
    tz = window_start.tzinfo
    signals = []
    for row in payload:
        starts_raw, ends_raw = row.get("event_start_date"), row.get("event_end_date")
        if not starts_raw or not ends_raw:
            continue
        day_start = datetime.fromisoformat(starts_raw).replace(tzinfo=tz)
        day_end = datetime.fromisoformat(ends_raw).replace(tzinfo=tz) + timedelta(
            hours=23, minutes=59
        )
        if day_end < window_start or day_start > window_end:
            continue
        attendance = float(row.get("attendance") or 0)
        name = row.get("name_of_event", "Special event")
        neighborhood = row.get("event_location_neighborhood", "")
        signals.append(
            Signal(
                id=f"sea-permit-{row.get('year_month_app', name)}-{starts_raw[:10]}",
                kind="special_event",
                zone=zone_for_neighborhood(neighborhood),
                starts_at=day_start.isoformat(),
                ends_at=day_end.isoformat(),
                magnitude=attendance,
                basis="scheduled",
                source=SOURCE,
                fetched_at=fetched_at,
                expires_at=day_end.isoformat(),
                evidence_quality=0.55,
                details={
                    "title": f"{name} ({neighborhood})",
                    "attendance_basis": "permit application estimate",
                    "timing_basis": "all-day permit; feed has no time of day",
                },
            )
        )
    return signals


def _newest_permit_date() -> str | None:
    url = f"{RESOURCE}?$select={quote('max(event_start_date)')}"
    try:
        payload, _, _ = fetch_json(url, cache_key="seattle_events_newest", ttl_seconds=86400)
    except FeedError:
        return None
    if isinstance(payload, list) and payload:
        return (payload[0].get("max_event_start_date") or "")[:10] or None
    return None


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    try:
        payload, mode, fetched_at = fetch_json(
            _query_url(window_start, window_end),
            cache_key=f"seattle_events_{window_start.date().isoformat()}",
            ttl_seconds=TTL_SECONDS,
        )
    except FeedError as error:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, str(error))
    signals = parse(payload, window_start, window_end, fetched_at=fetched_at)
    detail = ""
    if not signals:
        newest = _newest_permit_date()
        detail = "no permitted events in window"
        if newest:
            detail += f"; newest permit on file starts {newest}"
    return signals, FeedStatus(NAME, mode, SOURCE, fetched_at, len(signals), detail)
