"""Google Places API (New): live closing hours for named venues.

Place Details with a tight field mask (regularOpeningHours / currentOpeningHours).
That is an Enterprise SKU — cache hard, never poll per ping, never request Atmosphere
fields. Venues without a place_id are skipped so we do not Text-Search on a timer.
"""

from __future__ import annotations

import os
from datetime import datetime

from farol.adapters.base import FeedError, FeedStatus, fetch_json
from farol.adapters.venues import load_venues
from farol.adapters.venues import parse as parse_venue_hours
from farol.signals import Signal

NAME = "google_places_closing"
SOURCE = "google:places.googleapis.com Place Details (New)"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
TTL_SECONDS = 12 * 60 * 60
FIELD_MASK = "id,displayName,regularOpeningHours,currentOpeningHours"
# Places (New) day 0 = Sunday.
GOOGLE_DAY = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def google_maps_key() -> str:
    return os.getenv("GOOGLE_MAPS_API_KEY", "").strip()


def close_map_from_hours(payload: dict) -> dict[str, str]:
    """Map Google periods onto venues.json weekday keys using the open (evening) day."""
    hours = payload.get("currentOpeningHours") or payload.get("regularOpeningHours") or {}
    closes: dict[str, str] = {}
    for period in hours.get("periods") or []:
        opened = period.get("open") or {}
        closed = period.get("close") or {}
        if "day" not in opened or "hour" not in closed:
            continue
        day = int(opened["day"])
        if not 0 <= day <= 6:
            continue
        hour = int(closed.get("hour") or 0)
        minute = int(closed.get("minute") or 0)
        closes[GOOGLE_DAY[day]] = f"{hour:02d}:{minute:02d}"
    if closes.get("sat") == "23:59":
        overnight = [
            value
            for key, value in closes.items()
            if key != "sat" and value < "12:00"
        ]
        if overnight:
            closes["sat"] = overnight[0]
    return closes


def overlay_venues(venues: list[dict], hours_by_place: dict[str, dict]) -> list[dict]:
    overlaid = []
    for venue in venues:
        place_id = str(venue.get("place_id") or "").strip()
        payload = hours_by_place.get(place_id)
        if not payload:
            continue
        closes = close_map_from_hours(payload)
        if not closes:
            continue
        name = ((payload.get("displayName") or {}).get("text")) or venue["name"]
        updated = dict(venue)
        updated["close"] = closes
        updated["basis"] = "scheduled"
        updated["source"] = SOURCE
        updated["evidence_quality"] = max(float(venue.get("evidence_quality") or 0.6), 0.78)
        updated["name"] = name
        overlaid.append(updated)
    return overlaid


def _details(place_id: str) -> tuple[dict, str, str]:
    return fetch_json(
        DETAILS_URL.format(place_id=place_id),
        cache_key=f"places_details_{place_id}",
        ttl_seconds=TTL_SECONDS,
        headers={
            "X-Goog-Api-Key": google_maps_key(),
            "X-Goog-FieldMask": FIELD_MASK,
        },
    )


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    key = google_maps_key()
    if not key:
        return [], FeedStatus(
            NAME,
            "needs_key",
            "env:GOOGLE_MAPS_API_KEY",
            None,
            0,
            "set GOOGLE_MAPS_API_KEY — Place Details closing hours",
        )
    catalog = [venue for venue in load_venues() if str(venue.get("place_id") or "").strip()]
    if not catalog:
        return [], FeedStatus(NAME, "static", SOURCE, None, 0, "no venues with place_id")
    hours_by_place: dict[str, dict] = {}
    fetched_by_place: dict[str, str] = {}
    modes: list[str] = []
    fetched_at = ""
    errors: list[str] = []
    for venue in catalog:
        place_id = str(venue["place_id"]).strip()
        try:
            payload, mode, fetched_at = _details(place_id)
        except FeedError as error:
            errors.append(str(error))
            continue
        if isinstance(payload, dict):
            hours_by_place[place_id] = payload
            fetched_by_place[place_id] = fetched_at
            modes.append(mode)
    overlaid = overlay_venues(catalog, hours_by_place)
    signals = [signal for venue in overlaid for signal in parse_venue_hours(
        window_start, window_end, fetched_at=fetched_by_place[str(venue["place_id"])],
        venues=[venue],
    )]
    if not hours_by_place and errors:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, "; ".join(errors)[:300])
    mode = "live"
    if modes and all(item == "cache" for item in modes):
        mode = "cache"
    elif modes and all(item == "stale_cache" for item in modes):
        mode = "stale_cache"
    elif "live" not in modes and modes:
        mode = modes[0]
    detail = f"{len(overlaid)}/{len(catalog)} venues with Google hours"
    if errors:
        detail += f"; {len(errors)} failed"
    return signals, FeedStatus(NAME, mode, SOURCE, fetched_at or None, len(signals), detail)
