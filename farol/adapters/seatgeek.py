"""SeatGeek Platform API v2: event cross-check for the Seattle box.

Sports stay on ESPN/MLB/NHL. SeatGeek fills concerts/theater TM may miss and
can attach listing_count as a crude inventory proxy (not dollars). Client ID
is enough; secret is unused for public event search.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from farol.adapters.base import FeedError, FeedStatus, fetch_json
from farol.adapters.ticketmaster import (
    TOUR_NOISE,
    collapse_duplicate_exits,
    event_query_bounds,
    zone_for_venue,
)
from farol.signals import Signal

NAME = "seatgeek_events"
SOURCE = "seatgeek:api/2/events"
EVENTS_URL = "https://api.seatgeek.com/2/events"
TTL_SECONDS = 6 * 60 * 60
LAT = "47.62"
LON = "-122.33"
RANGE = "35mi"
SKIP_TYPES = {
    "mlb",
    "nfl",
    "nba",
    "nhl",
    "mls",
    "ncaa_football",
    "ncaa_basketball",
    "ncaa_womens_basketball",
    "wnba",
    "minor_league_baseball",
    "sports",
}


def _client_id() -> str:
    return os.getenv("SEATGEEK_CLIENT_ID", "").strip()


def _is_sport(event: dict) -> bool:
    if str(event.get("type") or "").lower() in SKIP_TYPES:
        return True
    for item in event.get("taxonomies") or []:
        name = str((item or {}).get("name") or "").lower()
        if name in SKIP_TYPES or name == "sports":
            return True
    return False


def _kickoff(event: dict, tzinfo) -> datetime | None:
    raw = event.get("datetime_local") or event.get("datetime_utc")
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=tzinfo if event.get("datetime_local") else UTC)
    return stamp.astimezone(tzinfo)


def parse(payload: dict, window_start: datetime, window_end: datetime, *, fetched_at: str) -> tuple[list[Signal], int]:
    skipped = 0
    signals: list[Signal] = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            skipped += 1
            continue
        venue = event.get("venue") or {}
        venue_name = str(venue.get("name") or "")
        title = str(event.get("title") or "SeatGeek event")
        blob = f"{title} {venue_name}".lower()
        if any(noise in blob for noise in TOUR_NOISE):
            skipped += 1
            continue
        if _is_sport(event):
            skipped += 1
            continue
        zone = zone_for_venue(venue_name)
        if zone is None:
            skipped += 1
            continue
        kickoff = _kickoff(event, window_start.tzinfo)
        if kickoff is None:
            skipped += 1
            continue
        duration = timedelta(hours=3)
        wave = timedelta(minutes=45)
        exit_start = kickoff + duration
        exit_end = exit_start + wave
        if exit_end < window_start or exit_start > window_end:
            continue
        stats = event.get("stats") or {}
        listing_count = stats.get("listing_count")
        signals.append(
            Signal(
                id=f"sg-{event.get('id') or exit_start.isoformat()}",
                kind="event_exit",
                zone=zone,
                starts_at=exit_start.isoformat(),
                ends_at=exit_end.isoformat(),
                magnitude=8000.0,
                basis="scheduled",
                source=SOURCE,
                fetched_at=fetched_at,
                expires_at=exit_end.isoformat(),
                evidence_quality=0.65,
                details={
                    "title": f"{title} exit at {venue_name}",
                    "venue": venue_name,
                    "kickoff": kickoff.isoformat(),
                    "listing_count": listing_count,
                    "listing_count_basis": "SeatGeek public listing_count; not attendance and not $/hr",
                    "exit_timing_basis": "assumed 3h show + 45m exit wave",
                    "url": event.get("url") or "",
                },
            )
        )
    collapsed, dupes = collapse_duplicate_exits(signals)
    return collapsed, skipped + dupes


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    client_id = _client_id()
    if not client_id:
        return [], FeedStatus(
            NAME,
            "needs_key",
            "env:SEATGEEK_CLIENT_ID",
            None,
            0,
            "set SEATGEEK_CLIENT_ID — Platform API concerts/theater in the Seattle box",
        )
    start, end = event_query_bounds(window_start, window_end)
    query = urlencode(
        {
            "client_id": client_id,
            "lat": LAT,
            "lon": LON,
            "range": RANGE,
            "per_page": "50",
            "sort": "datetime_utc.asc",
            "datetime_utc.gte": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datetime_utc.lte": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    cache_key = f"seatgeek_v2_{start:%Y%m%dT%H}_{end:%Y%m%dT%H}"
    try:
        payload, mode, fetched_at = fetch_json(
            f"{EVENTS_URL}?{query}",
            cache_key=cache_key,
            ttl_seconds=TTL_SECONDS,
        )
    except FeedError as error:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, str(error)[:300])
    if not isinstance(payload, dict):
        return [], FeedStatus(NAME, "error", SOURCE, fetched_at, 0, "unexpected payload")
    signals, skipped = parse(payload, window_start, window_end, fetched_at=fetched_at)
    total = payload.get("meta", {}).get("total")
    detail = f"{len(signals)} mapped exits"
    if skipped:
        detail += f"; {skipped} skipped (sports, tours, or unmapped venue)"
    if total is not None:
        detail += f"; SeatGeek total={total}"
    return signals, FeedStatus(NAME, mode, SOURCE, fetched_at, len(signals), detail)
