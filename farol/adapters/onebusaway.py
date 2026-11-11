"""Puget Sound OneBusAway: Sound Transit Link/T Line situations.

Uses vehicles-for-agency/40 JSON (situations live in references). TEST key is
allowed for local Farol; swap ONEBUSAWAY_API_KEY when Sound Transit issues a
named key. Sports crowding and station-opening blurbs are skipped. Real Link
delays/suspensions attach to stadium zones and can offset doctrine AVOID.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from farol.adapters.base import FeedError, FeedStatus, fetch_json
from farol.signals import Signal

NAME = "onebusaway_transit"
SOURCE = "onebusaway:api.pugetsound.onebusaway.org agency 40"
BASE = "https://api.pugetsound.onebusaway.org/api/where"
AGENCY = "40"
TTL_SECONDS = 5 * 60
# 2 Line has been in revenue service across the lake since 2026-03-28.
# T Line is Tacoma — it must not boost Seattle stadium scoring.
LINE_ZONES = {
    "1": ("sodo_stadiums", "seattle_center", "uw_district", "capitol_hill"),
    "2": ("bellevue_core", "redmond_downtown", "uw_district", "capitol_hill"),
    "t": (),
}
STATION_ZONES: dict[str, str] = {
    "bellevue downtown": "bellevue_core",
    "east main": "bellevue_core",
    "wilburton": "bellevue_core",
    "spring district": "bellevue_core",
    "south bellevue": "bellevue_core",
    "mercer island": "bellevue_core",
    "downtown redmond": "redmond_downtown",
    "redmond technology": "redmond_downtown",
    "overlake village": "redmond_downtown",
    "westlake": "seattle_core",
    "symphony": "seattle_core",
    "pioneer square": "seattle_core",
    "int'l dist/chinatown": "seattle_core",
    "judkins park": "seattle_core",
    "capitol hill": "capitol_hill",
    "univ of washington": "uw_district",
    "u district": "uw_district",
    "roosevelt": "uw_district",
    "northgate": "uw_district",
    "stadium": "sodo_stadiums",
    "sodo": "sodo_stadiums",
    "angle lake": "sea_airport",
    "tukwila int'l blvd": "sea_airport",
}
STADIUM_ZONES = LINE_ZONES["1"]
DISRUPT_WORDS = (
    "delay",
    "delayed",
    "suspend",
    "no service",
    "bus bridge",
    "single track",
    "single-track",
    "reduced service",
    "outage",
    "not running",
    "stoppage",
    "without trains",
    "shuttle",
)
SKIP_WORDS = ("plan ahead", "will open", "holiday", "sunday schedule")


def _api_key() -> str:
    return os.getenv("ONEBUSAWAY_API_KEY", "").strip()


def _ms_to_dt(ms: object, tzinfo) -> datetime | None:
    try:
        value = int(ms)
    except (TypeError, ValueError):
        return None
    if value > 10_000_000_000:
        value = value / 1000.0
    return datetime.fromtimestamp(value, tz=UTC).astimezone(tzinfo)


def _blob(situation: dict) -> str:
    summary = ((situation.get("summary") or {}).get("value") or "")
    desc = ((situation.get("description") or {}).get("value") or "")
    return f"{summary} {desc}".lower()


def _lines(situation: dict) -> set[str]:
    ids = {str(affect.get("routeId") or "") for affect in situation.get("allAffects") or []}
    text = _blob(situation)
    lines: set[str] = set()
    if "40_TLINE" in ids or "t line" in text or "tacoma link" in text:
        lines.add("t")
    if "40_2LINE" in ids or "2 line" in text:
        lines.add("2")
    if "40_100479" in ids or "40_1LINE" in ids or "1 line" in text:
        lines.add("1")
    if "link" in text and not lines:
        lines.add("1")
    return lines


def _is_link(situation: dict) -> bool:
    return bool(_lines(situation))


def _zones_for(situation: dict) -> tuple[str, ...]:
    zones: list[str] = []
    for line in _lines(situation):
        zones.extend(LINE_ZONES.get(line, ()))
    seen: set[str] = set()
    unique = []
    for zone in zones:
        if zone not in seen:
            seen.add(zone)
            unique.append(zone)
    return tuple(unique)


def _is_disruption(situation: dict) -> bool:
    text = _blob(situation)
    if not any(word in text for word in DISRUPT_WORDS):
        return False
    if any(word in text for word in SKIP_WORDS) and "delay" not in text and "no service" not in text:
        return False
    return True


def _windows(situation: dict, tzinfo) -> list[tuple[datetime, datetime]]:
    rows = []
    for window in situation.get("activeWindows") or []:
        start = _ms_to_dt(window.get("from"), tzinfo)
        end = _ms_to_dt(window.get("to"), tzinfo)
        if start and end:
            rows.append((start, end))
    return rows


def parse(payload: dict, window_start: datetime, window_end: datetime, *, fetched_at: str) -> list[Signal]:
    situations = ((payload.get("data") or {}).get("references") or {}).get("situations") or []
    signals: list[Signal] = []
    for situation in situations:
        if not isinstance(situation, dict) or not _is_link(situation) or not _is_disruption(situation):
            continue
        summary = ((situation.get("summary") or {}).get("value") or "Link disruption").strip()
        severe = any(word in _blob(situation) for word in ("no service", "bus bridge", "suspend", "without trains"))
        magnitude = 20.0 if severe else 6.0
        spans = _windows(situation, window_start.tzinfo) or [(window_start, window_end)]
        for start, end in spans:
            if end < window_start or start > window_end:
                continue
            overlap_start = start if start > window_start else window_start
            overlap_end = end if end < window_end else window_end
            zones = _zones_for(situation)
            if not zones:
                continue
            for zone in zones:
                signals.append(
                    Signal(
                        id=f"oba-{situation.get('id')}-{zone}",
                        kind="transit_disruption",
                        zone=zone,
                        starts_at=overlap_start.isoformat(),
                        ends_at=overlap_end.isoformat(),
                        magnitude=magnitude,
                        basis="live",
                        source=SOURCE,
                        fetched_at=fetched_at,
                        expires_at=overlap_end.isoformat(),
                        evidence_quality=0.8,
                        details={
                            "title": summary[:200],
                            "severe": severe,
                            "situation_id": situation.get("id"),
                        },
                    )
                )
    return signals


def parse_station_arrivals(
    payload: dict,
    window_start: datetime,
    window_end: datetime,
    *,
    fetched_at: str,
) -> list[Signal]:
    """Extract live Sound Transit 1 Line & 2 Line next-train station arrivals per zone."""
    del window_end
    data = (payload.get("data") or {}) if isinstance(payload, dict) else {}
    refs = data.get("references") or {}
    routes = {
        str(r.get("id") or ""): str(r.get("shortName") or r.get("longName") or "")
        for r in (refs.get("routes") or [])
        if isinstance(r, dict)
    }
    trips = {
        str(t.get("id") or ""): (
            str(t.get("routeId") or ""),
            str(t.get("tripHeadsign") or ""),
        )
        for t in (refs.get("trips") or [])
        if isinstance(t, dict)
    }
    stops = {
        str(s.get("id") or ""): (
            str(s.get("name") or ""),
            s.get("lat"),
            s.get("lon"),
        )
        for s in (refs.get("stops") or [])
        if isinstance(s, dict)
    }

    by_zone: dict[str, list[dict]] = {}
    for vehicle in data.get("list") or []:
        if not isinstance(vehicle, dict):
            continue
        trip_id = str(vehicle.get("tripId") or "")
        route_id, headsign = trips.get(trip_id, ("", ""))
        route_name = routes.get(route_id, "")
        if route_id not in {"40_100479", "40_1LINE", "40_2LINE"} and not (
            "1 line" in route_name.lower() or "2 line" in route_name.lower()
        ):
            continue
        line_label = "2 Line" if ("2" in route_name or route_id == "40_2LINE") else "1 Line"
        ts = vehicle.get("tripStatus") or {}
        next_stop_id = str(ts.get("nextStop") or "")
        offset_raw = ts.get("nextStopTimeOffset")
        try:
            offset_sec = int(offset_raw)
        except (TypeError, ValueError):
            continue
        if offset_sec < -60 or offset_sec > 900:
            continue
        station_name, lat, lon = stops.get(next_stop_id, ("", None, None))
        if not station_name:
            continue
        zone = STATION_ZONES.get(station_name.strip().lower())
        if not zone:
            continue
        eta_min = max(1, round(max(0, offset_sec) / 60))
        by_zone.setdefault(zone, []).append({
            "line": line_label,
            "headsign": headsign or "Link",
            "station": station_name,
            "eta_minutes": eta_min,
            "offset_seconds": offset_sec,
            "lat": lat,
            "lon": lon,
        })

    signals: list[Signal] = []
    for zone, trains in by_zone.items():
        trains.sort(key=lambda item: item["offset_seconds"])
        top_trains = trains[:3]
        first = top_trains[0]
        parts = [
            f"{t['line']} at {t['station']} in ~{t['eta_minutes']}m (to {t['headsign']})"
            for t in top_trains
        ]
        title = "Link Light Rail arriving: " + "; ".join(parts)
        starts = window_start
        ends = window_start + timedelta(minutes=20)
        signals.append(
            Signal(
                id=f"oba-link-arr-{zone}-{window_start.strftime('%Y%m%d%H%M')}",
                kind="special_event",
                zone=zone,
                starts_at=starts.isoformat(),
                ends_at=ends.isoformat(),
                magnitude=9500.0,
                basis="live",
                source=SOURCE,
                fetched_at=fetched_at,
                expires_at=ends.isoformat(),
                evidence_quality=0.82,
                details={
                    "title": title[:240],
                    "venue": f"{first['station']} Link Station",
                    "category": "light_rail",
                    "trains": top_trains,
                    "notes": (
                        "Live Sound Transit Link GPS arrival feed (OneBusAway). "
                        "Riders exiting trains often request last-mile Uber rides home or to hotels; "
                        "stage near the station kiss-and-ride curb 1–2 minutes before arrival."
                    ),
                },
            )
        )
    return signals


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    key = _api_key()
    if not key:
        return [], FeedStatus(
            NAME,
            "needs_key",
            "env:ONEBUSAWAY_API_KEY",
            None,
            0,
            "set ONEBUSAWAY_API_KEY — Puget Sound OBA (TEST is fine until ST issues a named key)",
        )
    url = f"{BASE}/vehicles-for-agency/{AGENCY}.json?key={key}"
    try:
        payload, mode, fetched_at = fetch_json(
            url,
            cache_key="onebusaway_st40_vehicles",
            ttl_seconds=TTL_SECONDS,
        )
    except FeedError as error:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, str(error)[:300])
    if not isinstance(payload, dict) or payload.get("code") not in (200, None):
        return [], FeedStatus(
            NAME,
            "error",
            SOURCE,
            fetched_at,
            0,
            f"OBA code {payload.get('code') if isinstance(payload, dict) else 'invalid'}",
        )
    disruptions = parse(payload, window_start, window_end, fetched_at=fetched_at)
    arrivals = parse_station_arrivals(payload, window_start, window_end, fetched_at=fetched_at)
    signals = disruptions + arrivals
    n_sit = len(((payload.get("data") or {}).get("references") or {}).get("situations") or [])
    detail = f"{len(arrivals)} station arrival zone(s), {len(disruptions)} Link disruptions ({n_sit} ST alerts)"
    return signals, FeedStatus(NAME, mode, SOURCE, fetched_at, len(signals), detail)


# Ordered South -> North / East station sequences for upstream ETA propagation
LINE_1_ORDER = [
    "Federal Way Downtown", "Star Lake", "Kent Des Moines", "Angle Lake",
    "SeaTac/Airport", "Tukwila Int'l Blvd", "Rainier Beach", "Othello",
    "Columbia City", "Mount Baker", "Beacon Hill", "SODO", "Stadium",
    "Int'l Dist/Chinatown", "Pioneer Square", "Symphony", "Westlake",
    "Capitol Hill", "Univ of Washington", "U District", "Roosevelt",
    "Northgate", "Pinehurst", "Shoreline South/148th", "Shoreline North/185th",
    "Mountlake Terrace", "Lynnwood City Center",
]

LINE_2_ORDER = [
    "Downtown Redmond", "Redmond Technology", "Overlake Village", "Bel-Red",
    "Spring District", "Wilburton", "Bellevue Downtown", "East Main",
    "South Bellevue", "Mercer Island", "Judkins Park", "Int'l Dist/Chinatown",
    "Pioneer Square", "Symphony", "Westlake", "Capitol Hill",
    "Univ of Washington", "U District", "Roosevelt", "Northgate",
    "Pinehurst", "Shoreline South/148th", "Shoreline North/185th",
    "Mountlake Terrace", "Lynnwood City Center",
]

TRAIN_STATION_CATALOG = [
    {"id": "bellevue_downtown", "name": "Bellevue Downtown Station", "match": "bellevue downtown", "lat": 47.615183, "lon": -122.191303, "zone": "bellevue_core", "lines": ["2 Line"]},
    {"id": "east_main", "name": "East Main Station", "match": "east main", "lat": 47.608403, "lon": -122.191099, "zone": "bellevue_core", "lines": ["2 Line"]},
    {"id": "wilburton", "name": "Wilburton Station", "match": "wilburton", "lat": 47.617909, "lon": -122.183806, "zone": "bellevue_core", "lines": ["2 Line"]},
    {"id": "spring_district", "name": "Spring District Station", "match": "spring district", "lat": 47.623772, "lon": -122.178901, "zone": "bellevue_core", "lines": ["2 Line"]},
    {"id": "south_bellevue", "name": "South Bellevue Station", "match": "south bellevue", "lat": 47.586932, "lon": -122.190604, "zone": "bellevue_core", "lines": ["2 Line"]},
    {"id": "mercer_island", "name": "Mercer Island Station", "match": "mercer island", "lat": 47.588003, "lon": -122.232737, "zone": "bellevue_core", "lines": ["2 Line"]},
    {"id": "redmond_technology", "name": "Redmond Technology Station", "match": "redmond technology", "lat": 47.645199, "lon": -122.133673, "zone": "redmond_downtown", "lines": ["2 Line"]},
    {"id": "overlake_village", "name": "Overlake Village Station", "match": "overlake village", "lat": 47.636151, "lon": -122.139236, "zone": "redmond_downtown", "lines": ["2 Line"]},
    {"id": "downtown_redmond", "name": "Downtown Redmond Station", "match": "downtown redmond", "lat": 47.671467, "lon": -122.117864, "zone": "redmond_downtown", "lines": ["2 Line"]},
    {"id": "westlake", "name": "Westlake Station", "match": "westlake", "lat": 47.611759, "lon": -122.335785, "zone": "seattle_core", "lines": ["1 Line", "2 Line"]},
    {"id": "symphony", "name": "Symphony Station", "match": "symphony", "lat": 47.607246, "lon": -122.335754, "zone": "seattle_core", "lines": ["1 Line", "2 Line"]},
    {"id": "pioneer_square", "name": "Pioneer Square Station", "match": "pioneer square", "lat": 47.603199, "lon": -122.331581, "zone": "seattle_core", "lines": ["1 Line", "2 Line"]},
    {"id": "intl_dist", "name": "Int'l Dist/Chinatown Station", "match": "int'l dist/chinatown", "lat": 47.597660, "lon": -122.328217, "zone": "seattle_core", "lines": ["1 Line", "2 Line"]},
    {"id": "king_street_amtrak", "name": "King Street Station (Amtrak)", "match": "king street", "lat": 47.598400, "lon": -122.329900, "zone": "seattle_core", "lines": ["Amtrak"]},
    {"id": "judkins_park", "name": "Judkins Park Station", "match": "judkins park", "lat": 47.590311, "lon": -122.304989, "zone": "seattle_core", "lines": ["2 Line"]},
    {"id": "capitol_hill", "name": "Capitol Hill Station", "match": "capitol hill", "lat": 47.619621, "lon": -122.320038, "zone": "capitol_hill", "lines": ["1 Line", "2 Line"]},
    {"id": "univ_of_washington", "name": "Univ of Washington Station", "match": "univ of washington", "lat": 47.650312, "lon": -122.303736, "zone": "uw_district", "lines": ["1 Line", "2 Line"]},
    {"id": "u_district", "name": "U District Station", "match": "u district", "lat": 47.659875, "lon": -122.314194, "zone": "uw_district", "lines": ["1 Line", "2 Line"]},
    {"id": "roosevelt", "name": "Roosevelt Station", "match": "roosevelt", "lat": 47.676107, "lon": -122.316041, "zone": "uw_district", "lines": ["1 Line", "2 Line"]},
    {"id": "northgate", "name": "Northgate Station", "match": "northgate", "lat": 47.703414, "lon": -122.328244, "zone": "uw_district", "lines": ["1 Line", "2 Line"]},
    {"id": "stadium", "name": "Stadium Station", "match": "stadium", "lat": 47.591824, "lon": -122.327354, "zone": "sodo_stadiums", "lines": ["1 Line"]},
    {"id": "sodo", "name": "SODO Station", "match": "sodo", "lat": 47.580792, "lon": -122.327473, "zone": "sodo_stadiums", "lines": ["1 Line"]},
    {"id": "seatac_airport", "name": "SeaTac/Airport Station", "match": "seatac/airport", "lat": 47.444530, "lon": -122.297050, "zone": "sea_airport", "lines": ["1 Line"]},
    {"id": "tukwila", "name": "Tukwila Int'l Blvd Station", "match": "tukwila int'l blvd", "lat": 47.463924, "lon": -122.288002, "zone": "sea_airport", "lines": ["1 Line"]},
    {"id": "angle_lake", "name": "Angle Lake Station", "match": "angle lake", "lat": 47.423025, "lon": -122.297765, "zone": "sea_airport", "lines": ["1 Line"]},
]


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(min(1.0, a)))


def nearby_train_stations(
    lat: float,
    lon: float,
    *,
    radius_miles: float = 5.0,
    now: datetime | None = None,
) -> list[dict]:
    """Return all Link & Amtrak train stations within `radius_miles` with their incoming train schedule."""
    from zoneinfo import ZoneInfo
    from farol.adapters.base import read_cache
    from farol.evidence import format_clock

    pacific = ZoneInfo("America/Los_Angeles")
    current = (now or datetime.now(pacific)).astimezone(pacific)

    candidates = []
    for station in TRAIN_STATION_CATALOG:
        dist = round(_haversine_miles(lat, lon, station["lat"], station["lon"]), 2)
        if dist <= radius_miles:
            candidates.append({**station, "distance_miles": dist})
    candidates.sort(key=lambda item: item["distance_miles"])
    if not candidates:
        return []

    # Load cached OneBusAway vehicles payload — enforce 10-minute telemetry freshness (R11)
    from datetime import UTC
    from farol.evidence import parse_time

    current_utc = current.astimezone(UTC)
    oba_cached = read_cache("onebusaway_st40_vehicles")
    oba_fetched_dt = parse_time((oba_cached or {}).get("fetched_at")) if isinstance(oba_cached, dict) else None
    oba_age_sec = (
        (current_utc - oba_fetched_dt.astimezone(UTC)).total_seconds()
        if (oba_fetched_dt is not None and oba_fetched_dt.tzinfo is not None)
        else None
    )
    oba_fresh = oba_age_sec is not None and -120.0 <= oba_age_sec <= 600.0
    oba_data = (((oba_cached or {}).get("payload") or {}).get("data") or {}) if oba_fresh else {}
    refs = oba_data.get("references") or {}
    routes = {
        str(r.get("id") or ""): str(r.get("shortName") or r.get("longName") or "")
        for r in (refs.get("routes") or [])
        if isinstance(r, dict)
    }
    trips = {
        str(t.get("id") or ""): (
            str(t.get("routeId") or ""),
            str(t.get("tripHeadsign") or ""),
        )
        for t in (refs.get("trips") or [])
        if isinstance(t, dict)
    }
    stops = {
        str(s.get("id") or ""): str(s.get("name") or "")
        for s in (refs.get("stops") or [])
        if isinstance(s, dict)
    }

    # Index active Link trains by (line_label, next_stop_lower, offset_sec, headsign)
    active_trains = []
    elapsed_since_fetch = max(0.0, oba_age_sec or 0.0)
    for vehicle in oba_data.get("list") or []:
        if not isinstance(vehicle, dict):
            continue
        trip_id = str(vehicle.get("tripId") or "")
        route_id, headsign = trips.get(trip_id, ("", ""))
        route_name = routes.get(route_id, "")
        if route_id not in {"40_100479", "40_1LINE", "40_2LINE"} and not (
            "1 line" in route_name.lower() or "2 line" in route_name.lower()
        ):
            continue
        line_label = "2 Line" if ("2" in route_name or route_id == "40_2LINE") else "1 Line"
        ts = vehicle.get("tripStatus") or {}
        # Check per-vehicle lastUpdateTime (ms) if provided
        veh_update_ms = ts.get("lastUpdateTime") or vehicle.get("lastUpdateTime")
        veh_elapsed_sec = elapsed_since_fetch
        if isinstance(veh_update_ms, (int, float)) and veh_update_ms > 1_000_000_000_000:
            veh_dt = datetime.fromtimestamp(float(veh_update_ms) / 1000.0, tz=UTC)
            veh_age = (current_utc - veh_dt).total_seconds()
            if veh_age > 600.0 or veh_age < -120.0:
                continue
            veh_elapsed_sec = max(0.0, veh_age)
        next_stop_name = stops.get(str(ts.get("nextStop") or ""), "").strip()
        try:
            raw_offset_sec = int(ts.get("nextStopTimeOffset"))
        except (TypeError, ValueError):
            continue
        adjusted_offset_sec = int(round(raw_offset_sec - veh_elapsed_sec))
        if not next_stop_name or adjusted_offset_sec < -60 or adjusted_offset_sec > 1200:
            continue
        active_trains.append({
            "line": line_label,
            "headsign": headsign or "Link",
            "next_stop": next_stop_name,
            "next_stop_lower": next_stop_name.lower(),
            "offset_seconds": max(15, adjusted_offset_sec),
        })

    line1_idx = {name.lower(): idx for idx, name in enumerate(LINE_1_ORDER)}
    line2_idx = {name.lower(): idx for idx, name in enumerate(LINE_2_ORDER)}

    out = []
    for st in candidates:
        st_match = st["match"].lower()
        trains_for_station: list[dict] = []

        if st["id"] == "king_street_amtrak":
            # Pull cached Amtrak trains using canonical cache key (R21)
            from farol.adapters import amtrak_sea
            am_cached = read_cache("amtraker_v3_trains") or read_cache("amtrak_v3_trains")
            am_fetched_dt = parse_time((am_cached or {}).get("fetched_at")) if isinstance(am_cached, dict) else None
            am_fresh = (
                am_fetched_dt is not None
                and am_fetched_dt.tzinfo is not None
                and -120.0 <= (current_utc - am_fetched_dt.astimezone(UTC)).total_seconds() <= 1800.0
            )
            if am_fresh and isinstance(am_cached, dict) and isinstance(am_cached.get("payload"), dict):
                am_sigs = amtrak_sea.parse(
                    am_cached["payload"],
                    current - timedelta(minutes=15),
                    current + timedelta(hours=6),
                    fetched_at=str(am_cached.get("fetched_at") or current.isoformat()),
                )
                for sig in am_sigs[:4]:
                    arr_str = sig.details.get("arrival_time") or sig.starts_at
                    try:
                        arr_dt = datetime.fromisoformat(str(arr_str)).astimezone(pacific)
                        eta_m = max(1, int(round((arr_dt - current).total_seconds() / 60.0)))
                        train_no = sig.details.get("train_number") or sig.details.get("train_num") or ""
                        trains_for_station.append({
                            "line": f"Amtrak #{train_no}".strip(),
                            "headsign": f"from {sig.details.get('origin', 'Corridor')}",
                            "eta_minutes": eta_m,
                            "arrival_clock": format_clock(arr_dt),
                            "status": "GPS live",
                        })
                    except ValueError:
                        continue
        else:
            for tr in active_trains:
                order_map = line2_idx if tr["line"] == "2 Line" else line1_idx
                if st_match not in order_map or tr["next_stop_lower"] not in order_map:
                    continue
                target_pos = order_map[st_match]
                train_pos = order_map[tr["next_stop_lower"]]
                going_north = "lynnwood" in tr["headsign"].lower() or "northgate" in tr["headsign"].lower() or "seattle" in tr["headsign"].lower()
                if target_pos == train_pos:
                    stops_away = 0
                elif going_north and target_pos > train_pos:
                    stops_away = target_pos - train_pos
                elif (not going_north) and target_pos < train_pos:
                    stops_away = train_pos - target_pos
                else:
                    continue
                if stops_away > 6:
                    continue
                total_sec = tr["offset_seconds"] + stops_away * 155
                eta_m = max(1, int(round(total_sec / 60.0)))
                arr_dt = current + timedelta(seconds=total_sec)
                from_label = "from Seattle" if (tr["line"] == "2 Line" and not going_north and st["zone"] in {"bellevue_core", "redmond_downtown"}) else f"to {tr['headsign']}"
                trains_for_station.append({
                    "line": tr["line"],
                    "headsign": from_label,
                    "eta_minutes": eta_m,
                    "arrival_clock": format_clock(arr_dt),
                    "status": "GPS live" if stops_away <= 1 else f"GPS ({stops_away} stops away)",
                })

            trains_for_station.sort(key=lambda item: item["eta_minutes"])
            deduped = []
            seen_keys = set()
            for item in trains_for_station:
                k = (item["line"], item["headsign"], item["eta_minutes"])
                if k not in seen_keys:
                    seen_keys.add(k)
                    deduped.append(item)
            trains_for_station = deduped[:4]
            # R11: Never fabricate scheduled arrivals using `last_eta + step*8`.
            # When live telemetry is absent or expired, `trains` stays empty.

        out.append({
            "id": st["id"],
            "name": st["name"],
            "zone": st["zone"],
            "distance_miles": st["distance_miles"],
            "lines": st["lines"],
            "maps_url": f"https://www.google.com/maps/dir/?api=1&destination={st['lat']},{st['lon']}",
            "next_eta_minutes": trains_for_station[0]["eta_minutes"] if trains_for_station else None,
            "telemetry_fresh": oba_fresh if st["id"] != "king_street_amtrak" else bool(trains_for_station),
            "trains": trains_for_station[:4],
        })
    return out
