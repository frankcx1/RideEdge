"""v0 sit-here ranker: personal weekday-hour × zone, minus reposition.

Chaudhari/Byers/Terzi (WSDM 2018): repositioning through the day beats chasing
surge. Haferkamp et al.: score = expected value − travel time − crowding.
This implementation uses only the driver's official receipts. SEA is not mixed
into the street board — airport FIFO is a separate game.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from itertools import pairwise

from farol.zones import load_zones

STREET_ZONES = (
    "kirkland_waterfront",
    "kirkland_rose_hill",
    "bellevue_core",
    "redmond_downtown",
    "totem_lake",
    "woodinville_wine",
)
ROAD_FACTOR = 1.3
ASSUMED_MPH = 27.0
MIN_TRIPS_FOR_HOUR_ZONE = 2
MAX_ON_SHIFT_GAP_MINUTES = 4 * 60


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(a))


def _zone_xy(zone_id: str) -> tuple[float, float] | None:
    record = next((zone for zone in load_zones().zones if zone.id == zone_id), None)
    if record is None:
        return None
    return record.latitude, record.longitude


_WEST_OF_LAKE_ZONES = {
    "seattle_core",
    "capitol_hill",
    "seattle_center",
    "fremont_ballard",
    "uw_district",
    "u_district",
    "central_district",
    "stadium_sodo",
    "sodo_stadiums",
}
_EAST_OF_LAKE_ZONES = {
    "kirkland_waterfront",
    "kirkland_rose_hill",
    "bellevue_core",
    "redmond_downtown",
    "totem_lake",
    "woodinville_wine",
    "marymoor",
    "cottage_lake",
    "issaquah",
}
_LAKE_BRIDGES = (
    (47.6405, -122.2575),  # SR-520 Evergreen Point Floating Bridge
    (47.5897, -122.2442),  # I-90 floating bridge
)


def reposition(from_zone: str, to_zone: str) -> tuple[float, float]:
    if from_zone == to_zone:
        return 0.0, 0.0
    start, end = _zone_xy(from_zone), _zone_xy(to_zone)
    if start is None or end is None:
        return 8.0, 18.0
    crosses_lake = (
        (from_zone in _WEST_OF_LAKE_ZONES and to_zone in _EAST_OF_LAKE_ZONES)
        or (from_zone in _EAST_OF_LAKE_ZONES and to_zone in _WEST_OF_LAKE_ZONES)
    )
    if crosses_lake:
        raw_miles = min(
            _haversine_miles(*start, b_lat, b_lon) + _haversine_miles(b_lat, b_lon, *end)
            for b_lat, b_lon in _LAKE_BRIDGES
        )
        miles = round(raw_miles * ROAD_FACTOR, 2)
        minutes = round(miles / ASSUMED_MPH * 60 + 4.0, 1)
        return miles, minutes
    miles = round(_haversine_miles(*start, *end) * ROAD_FACTOR, 2)
    minutes = round(miles / ASSUMED_MPH * 60, 1)
    return miles, minutes


def empty_miles_report(trips: list[dict]) -> dict:
    """Centroid-to-centroid deadhead between consecutive trips + unpaid gaps."""
    trips = [trip for trip in trips if float(trip.get("duration_minutes") or 0) > 0]
    if len(trips) < 2:
        return {
            "pairs": 0,
            "mean_unpaid_gap_minutes": 0,
            "mean_estimated_empty_miles": 0,
            "empty_miles_per_paid_mile": None,
            "note": "Need two consecutive trips to estimate empty miles.",
        }
    ordered = sorted(trips, key=lambda item: item["requested_at"])
    gaps = []
    empty = []
    off_duty_pairs = 0
    paid = sum(item["paid_miles"] for item in ordered)
    for previous, following in pairwise(ordered):
        start = datetime.fromisoformat(previous["ended_at"])
        nxt = datetime.fromisoformat(following["requested_at"])
        gap = max(0.0, (nxt - start).total_seconds() / 60)
        if gap > MAX_ON_SHIFT_GAP_MINUTES:
            off_duty_pairs += 1
            continue
        gaps.append(gap)
        miles, _ = reposition(previous["dropoff_zone"], following["pickup_zone"])
        empty.append(miles)
    total_empty = sum(empty)
    if not gaps:
        return {
            "pairs": 0,
            "off_duty_pairs": off_duty_pairs,
            "mean_unpaid_gap_minutes": 0,
            "mean_estimated_empty_miles": 0,
            "empty_miles_per_paid_mile": None,
            "kpi": "Shrink empty miles and unpaid minutes. That is the sit-here model's job.",
            "note": (
                "Gaps longer than 4 hours are treated as off-duty, not unpaid wait."
            ),
        }
    return {
        "pairs": len(gaps),
        "off_duty_pairs": off_duty_pairs,
        "mean_unpaid_gap_minutes": round(sum(gaps) / len(gaps), 1),
        "median_unpaid_gap_minutes": round(sorted(gaps)[len(gaps) // 2], 1),
        "mean_estimated_empty_miles": round(total_empty / len(empty), 2),
        "estimated_empty_miles": round(total_empty, 2),
        "paid_miles": round(paid, 2),
        "empty_miles_per_paid_mile": round(total_empty / paid, 2) if paid else None,
        "kpi": "Shrink empty miles and unpaid minutes. That is the sit-here model's job.",
        "note": (
            "Empty miles are zone-centroid estimates, not GPS traces. Gaps longer than "
            "4 hours are off-duty, not wait. Drivers Union WA (2026) found most Uber "
            "miles in this market are now empty."
        ),
    }


def _bucket_key(ts: datetime, zone: str) -> tuple[int, int, str]:
    return ts.weekday(), ts.hour, zone


def _trip_net_per_hour(trip: dict, vehicle_cost_per_mile: float) -> float:
    minutes = max(float(trip.get("duration_minutes") or 0), 8.0)
    net = float(trip["earnings"]) - float(trip.get("paid_miles") or 0) * vehicle_cost_per_mile
    return net / (minutes / 60.0)


def _historical_rate(
    trips: list[dict], weekday: int, hour: int, zone: str, vehicle_cost_per_mile: float
) -> dict:
    # Cancellation/zero-duration receipts count toward earnings totals, but
    # cannot establish the value or duration of a completed ride.
    trips = [trip for trip in trips if float(trip.get("duration_minutes") or 0) > 0]
    exact = [
        trip
        for trip in trips
        if datetime.fromisoformat(trip["requested_at"]).weekday() == weekday
        and datetime.fromisoformat(trip["requested_at"]).hour == hour
        and trip["pickup_zone"] == zone
    ]
    same_hour = [
        trip
        for trip in trips
        if datetime.fromisoformat(trip["requested_at"]).hour == hour and trip["pickup_zone"] == zone
    ]
    same_zone = [trip for trip in trips if trip["pickup_zone"] == zone]
    if len(exact) >= MIN_TRIPS_FOR_HOUR_ZONE:
        sample, grain = exact, "weekday_hour_zone"
    elif len(same_hour) >= MIN_TRIPS_FOR_HOUR_ZONE:
        sample, grain = same_hour, "hour_zone"
    elif same_zone:
        sample, grain = same_zone, "zone"
    else:
        return {"trips": 0, "mean_earnings": 0, "mean_net_per_hour": 0, "grain": "none"}
    mean = sum(item["earnings"] for item in sample) / len(sample)
    mean_rate = sum(_trip_net_per_hour(item, vehicle_cost_per_mile) for item in sample) / len(sample)
    return {
        "trips": len(sample),
        "mean_earnings": round(mean, 2),
        "mean_net_per_hour": round(mean_rate, 2),
        "grain": grain,
    }


def _candidate_street_zones(trips: list[dict], origin_zone: str) -> tuple[str, ...]:
    known = set(load_zones().by_id) - {"sea_airport"}
    counts: dict[str, int] = {}
    for trip in trips:
        if float(trip.get("duration_minutes") or 0) <= 0:
            continue
        pickup = str(trip.get("pickup_zone") or "")
        if pickup in known:
            counts[pickup] = counts.get(pickup, 0) + 1
    extra = sorted(
        zone
        for zone, count in counts.items()
        if zone not in STREET_ZONES and (count >= MIN_TRIPS_FOR_HOUR_ZONE or zone == origin_zone)
    )
    return (*STREET_ZONES, *extra)


def rank_next_hours(
    trips: list[dict],
    *,
    now: datetime,
    origin_zone: str,
    hours: int = 3,
    value_of_time_per_hour: float = 22.0,
    vehicle_cost_per_mile: float = 0.45,
    live_routes: dict[str, tuple[float, float]] | None = None,
    outcome_summaries: dict[str, dict] | None = None,
) -> dict:
    """Rank street zones for the next `hours`. Airport is excluded on purpose."""
    if outcome_summaries is None:
        try:
            from farol.history import summarize_zone_outcomes

            outcome_summaries = summarize_zone_outcomes(now=now)
        except Exception:
            outcome_summaries = {}
    dollars_per_minute = value_of_time_per_hour / 60
    candidate_zones = _candidate_street_zones(trips, origin_zone)
    rows = []
    for offset in range(hours):
        slot = now + timedelta(hours=offset)
        for zone in candidate_zones:
            hist = _historical_rate(
                trips, slot.weekday(), slot.hour, zone, vehicle_cost_per_mile
            )
            if offset == 0 and live_routes and zone in live_routes:
                miles, minutes = live_routes[zone]
                route_basis = "live"
            elif zone == origin_zone:
                miles, minutes = 0.0, 0.0
                route_basis = "live" if offset == 0 and live_routes else "assumed"
            else:
                miles, minutes = reposition(origin_zone, zone)
                route_basis = "assumed"
            travel_penalty = minutes * dollars_per_minute + miles * vehicle_cost_per_mile
            out_info = (outcome_summaries or {}).get(zone) or {}
            outcome_adj = float(out_info.get("score_adjustment") or 0.0) if offset == 0 else 0.0
            score = round(hist["mean_net_per_hour"] - travel_penalty + outcome_adj, 2)
            xy = _zone_xy(zone)
            maps_url = (
                f"https://www.google.com/maps/dir/?api=1&destination={xy[0]},{xy[1]}"
                if xy
                else ""
            )
            rows.append(
                {
                    "hour": slot.hour,
                    "weekday": slot.strftime("%A"),
                    "zone": zone,
                    "score": score,
                    "historical_mean_earnings": hist["mean_earnings"],
                    "historical_net_per_hour": hist["mean_net_per_hour"],
                    "rate_basis": "paid_trip_time_only" if hist["trips"] > 0 else "unknown",
                    "sample_trips": hist["trips"],
                    "grain": hist["grain"],
                    "reposition_minutes": minutes,
                    "reposition_miles": miles,
                    "route_basis": route_basis,
                    "travel_penalty": round(travel_penalty, 2),
                    "outcome_adjustment": outcome_adj,
                    "outcome_waiting_events": int(out_info.get("waiting_events") or 0),
                    "outcome_requests_received": int(out_info.get("requests_received") or 0)
                    + int(out_info.get("accepted_rides") or 0),
                    "outcome_note": str(out_info.get("note") or ""),
                    "thin": hist["trips"] < MIN_TRIPS_FOR_HOUR_ZONE,
                    "maps_url": maps_url,
                }
            )
    rows.sort(
        key=lambda item: (item["score"], item["sample_trips"], item["hour"] == now.hour),
        reverse=True,
    )
    seen_zones: set[str] = set()
    distinct_rows = []
    for item in rows:
        if item["zone"] not in seen_zones:
            seen_zones.add(item["zone"])
            distinct_rows.append(item)
    top = distinct_rows[:6] if len(distinct_rows) >= 6 else rows[:6]
    if hours == 1 and top and not any(item["zone"] == origin_zone for item in top):
        stay_row = next((item for item in rows if item["zone"] == origin_zone), None)
        if stay_row is not None:
            top = [*top[:5], stay_row]
    return {
        "origin_zone": origin_zone,
        "hours": hours,
        "doctrine": (
            "Do not chase Uber purple. "
            "Receipt-based ranking uses paid-trip earnings and duration, with a penalty "
            "for repositioning. Waiting and return-home time are missing; this is not a "
            "net shift-hour forecast. Sparse weekday-hour samples fall back to other "
            "hours or days in the same zone. SEA FIFO is a separate board."
        ),
        "ranked": top,
        "all_rows": rows,
        "empty_miles": empty_miles_report(trips),
    }
