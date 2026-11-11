"""Google Routes API: traffic-aware minutes from a pin to approved-anchor candidates.

Uses computeRouteMatrix + TRAFFIC_AWARE (Routes Matrix Pro SKU as of 2026),
billed per origin×destination element. One request per HERE/Tonight refresh,
cached ~15 minutes. Never TRAFFIC_AWARE_OPTIMAL.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime

from farol.adapters.base import FeedError, FeedStatus, MemoryCache, fetch_json
from farol.dashboard import FIXTURES
from farol.signals import Anchor, RouteEstimate, load_anchors
from farol.zones import load_zones

NAME = "google_routes_traffic"
SOURCE = "google:routes.googleapis.com computeRouteMatrix TRAFFIC_AWARE"
MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
TTL_SECONDS = 15 * 60
FIELD_MASK = "originIndex,destinationIndex,duration,distanceMeters,status"
METERS_PER_MILE = 1609.344
_private_cache = MemoryCache(TTL_SECONDS)


def expire_private_cache():
    _private_cache.expire()


def clear_private_cache():
    _private_cache.clear()


def google_maps_key() -> str:
    return os.getenv("GOOGLE_MAPS_API_KEY", "").strip()


def _duration_minutes(raw: str | None) -> float | None:
    if not raw or not str(raw).endswith("s"):
        return None
    try:
        return round(float(str(raw)[:-1]) / 60.0, 0)
    except ValueError:
        return None


def parse_matrix(
    payload: list,
    *,
    origin_zone: str,
    anchors: list[Anchor],
    vehicle_cost_per_mile: float,
    fetched_at: str,
    basis: str = "live",
) -> dict[str, RouteEstimate]:
    routes: dict[str, RouteEstimate] = {}
    if not isinstance(payload, list):
        return routes
    for row in payload:
        if not isinstance(row, dict):
            continue
        status = row.get("status") or {}
        if status.get("code") not in (None, 0, "OK"):
            continue
        index = row.get("destinationIndex", 0)
        if not isinstance(index, int) or index < 0 or index >= len(anchors):
            continue
        minutes = _duration_minutes(row.get("duration"))
        meters = row.get("distanceMeters")
        if minutes == 0 and meters is None:
            meters = 0
        if minutes is None or not isinstance(meters, (int, float)):
            continue
        miles = round(float(meters) / METERS_PER_MILE, 1)
        anchor = anchors[index]
        routes[anchor.id] = RouteEstimate(
            origin_zone=origin_zone,
            destination_anchor_id=anchor.id,
            traffic_minutes=minutes,
            distance_miles=miles,
            vehicle_cost=round(miles * vehicle_cost_per_mile, 2),
            basis=basis if basis in {"scheduled", "live", "assumed"} else "assumed",
            source=SOURCE,
            fetched_at=fetched_at,
        )
    return routes


def _cache_key(lat: float, lon: float, anchors: list[Anchor]) -> str:
    parts = [f"{anchor.id}:{anchor.latitude:.5f}:{anchor.longitude:.5f}" for anchor in anchors]
    signature = hashlib.sha256(",".join(parts).encode()).hexdigest()[:16]
    return f"routes_matrix_{lat:.3f}_{lon:.3f}_{signature}"


def matrix(
    origin_zone: str,
    origin_lat: float,
    origin_lon: float,
    anchors: list[Anchor],
    vehicle_cost_per_mile: float,
    as_of: str,
    *,
    public_origin: bool = False,
) -> tuple[dict[str, RouteEstimate], FeedStatus]:
    """Origins are private unless the caller explicitly identifies a public place.

    Device and configured-home origins must leave public_origin=False. Public
    venue caches retain the legacy disk/history behavior; private routes are
    bounded to process memory for at most 15 minutes and never written to history.
    """
    key = google_maps_key()
    if not key:
        return {}, FeedStatus(
            NAME,
            "needs_key",
            "env:GOOGLE_MAPS_API_KEY",
            None,
            0,
            "set GOOGLE_MAPS_API_KEY — traffic-priced reposition",
        )
    if not anchors:
        return {}, FeedStatus(NAME, "static", SOURCE, as_of, 0, "no anchors")
    body = {
        "origins": [
            {"waypoint": {"location": {"latLng": {"latitude": origin_lat, "longitude": origin_lon}}}}
        ],
        "destinations": [
            {
                "waypoint": {
                    "location": {"latLng": {"latitude": anchor.latitude, "longitude": anchor.longitude}}
                }
            }
            for anchor in anchors
        ],
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
    }
    try:
        payload, mode, fetched_at = fetch_json(
            MATRIX_URL,
            cache_key=(_cache_key(origin_lat, origin_lon, anchors) if public_origin else
                       "private_routes_" + hashlib.sha256(json_key(origin_lat, origin_lon, anchors)).hexdigest()),
            ttl_seconds=TTL_SECONDS,
            method="POST",
            body=body,
            headers={
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            memory_cache=None if public_origin else _private_cache,
        )
    except FeedError as error:
        detail = str(error)[:300] if public_origin else "Traffic provider unavailable; private origin not retained"
        return {}, FeedStatus(NAME, "error", SOURCE, None, 0, detail)
    rows = payload if isinstance(payload, list) else []
    route_basis = "live" if mode in {"live", "cache"} else "assumed"
    routes = parse_matrix(
        rows,
        origin_zone=origin_zone,
        anchors=anchors,
        vehicle_cost_per_mile=vehicle_cost_per_mile,
        fetched_at=fetched_at,
        basis=route_basis,
    )
    if public_origin and route_basis == "live" and routes:
        from farol.changes import retain_routes
        from farol.zones import canonical_zone

        retain_routes(origin_zone, routes, fetched_at)
        canonical = canonical_zone(origin_zone)
        if canonical and canonical != origin_zone:
            retain_routes(canonical, routes, fetched_at)
    return routes, FeedStatus(
        NAME,
        mode,
        SOURCE,
        fetched_at,
        len(routes),
        f"{len(routes)}/{len(anchors)} traffic-aware legs from {origin_zone}",
    )


def json_key(lat: float, lon: float, anchors: list[Anchor]) -> bytes:
    # Full precision avoids mixing nearby device origins; this index is memory-only.
    return repr((lat, lon, [(a.id, a.latitude, a.longitude) for a in anchors])).encode()


def fetch(window_start: datetime, window_end: datetime) -> tuple[list, FeedStatus]:
    """Collector entry: warm the home→anchor matrix. Produces no Signal rows."""
    del window_end
    key = google_maps_key()
    if not key:
        status = FeedStatus(
            NAME,
            "needs_key",
            "env:GOOGLE_MAPS_API_KEY",
            None,
            0,
            "set GOOGLE_MAPS_API_KEY — traffic-priced reposition",
        )
        return [], status
    registry = load_zones()
    anchors = load_anchors(FIXTURES / "anchors.json")
    _, status = matrix(
        "kirkland_home",
        registry.origin_latitude,
        registry.origin_longitude,
        anchors,
        vehicle_cost_per_mile=float(os.getenv("VEHICLE_COST_PER_MILE", "0.45") or 0.45),
        as_of=window_start.isoformat(),
    )
    return [], status
