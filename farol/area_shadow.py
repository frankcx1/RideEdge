"""Experimental area decisions. Explicit opt-in, no production imports or publication.

Scores are inspectable positioning heuristics, never probabilities or headcounts.
Income and vehicle ownership remain descriptive until independently evaluated.
"""

from __future__ import annotations

import copy
import math
from datetime import timedelta

from farol import radar
from farol.besttime_filter import normalize_filter

VERSION = "area-shadow-v1"


def type_weight(kind):
    kind = str(kind or "").upper()
    if any(k in kind for k in ("BAR", "NIGHT_CLUB", "BREWERY")):
        return 1.0
    if "RESTAURANT" in kind:
        return 0.9
    if any(k in kind for k in ("CAFE", "COFFEE", "ICE_CREAM")):
        return 0.55
    if any(k in kind for k in ("MALL", "SHOPPING")):
        return 0.4
    if any(k in kind for k in ("GROCERY", "SUPERMARKET", "STORE", "FAST_FOOD")):
        return 0.2
    return 0.0  # retained as context, not automatically a rider-producing venue


def scheduled_open(venue, arrival):
    """Use supplied weekly periods only; missing/ambiguous periods mean unknown."""
    periods = (venue.get("opening_periods") or {}).get("24h")
    if not isinstance(periods, list) or not periods or type(venue.get("day_int")) is not int:
        return None
    local = arrival.astimezone(radar.PACIFIC)
    offset = (local.weekday() - venue["day_int"]) % 7
    if offset > 1:
        return None
    minute = offset * 1440 + local.hour * 60 + local.minute
    spans = []
    for period in periods:
        if not isinstance(period, dict):
            return None
        start, end = period.get("opens"), period.get("closes")
        sm, em = period.get("opens_minutes", 0), period.get("closes_minutes", 0)
        if not (
            all(radar.number(v) for v in (start, end, sm, em))
            and 6 <= start < 24
            and 0 <= end <= 24
            and 0 <= sm < 60
            and 0 <= em < 60
        ):
            return None
        start, end = start * 60 + sm, end * 60 + em
        if end <= start:
            end += 1440
        spans.append((start, end))
    # Ten-minute usable window is an explicit positioning rule, not a wait estimate.
    return any(start <= minute and minute + 10 <= end for start, end in spans)


def area_brief(center, receipts, at, route, neighborhood=None):
    """Merge by provider identity; keep null, zero, sample limits and provenance."""
    merged, coverage = {}, []
    for receipt_id, receipt in receipts:
        normalized = normalize_filter(receipt, receipt_id)
        coverage.append(
            {k: v for k, v in normalized.items() if k != "venues"} | {"receipt": receipt_id}
        )
        for venue in normalized["venues"]:
            if (
                radar.distance(
                    center.latitude, center.longitude, venue["latitude"], venue["longitude"]
                )
                > 1000 / 1609.344
            ):
                continue
            dest = merged.setdefault(venue["id"], copy.deepcopy(venue))
            if venue["live_percent"] is not None:
                dest.update(
                    live_percent=venue["live_percent"], live_retrieved_at=venue["retrieved_at"]
                )
                dest["provenance"]["live"] = venue["provenance"]["live"]
            if venue["typical_day"] is not None:
                dest.update(
                    typical_day=venue["typical_day"],
                    day_int=venue["day_int"],
                    typical_retrieved_at=venue["retrieved_at"],
                    opening_periods=venue["opening_periods"],
                )
                dest["provenance"]["typical"] = venue["provenance"]["typical"]
                dest["provenance"]["opening_periods"] = {
                    "receipt": receipt_id,
                    "field": venue["provenance"]["identity"]["field"]
                    + ".day_info.venue_open_close_v2",
                }
    arrival = at + timedelta(minutes=route["minutes"])
    local = arrival.astimezone(radar.PACIFIC)
    day_int = (local.weekday() - (local.hour < 6)) % 7
    index = (local.hour - 6) % 24
    venues = []
    for vid, venue in sorted(merged.items()):
        live_ok = radar.fresh(venue.get("live_retrieved_at"), arrival, 60)
        typical_ok = (
            radar.fresh(venue.get("typical_retrieved_at"), at, 14 * 24 * 60)
            and venue["day_int"] == day_int
        )
        typical = venue["typical_day"][index] if typical_ok else None
        live = venue["live_percent"] if live_ok else None
        is_open = scheduled_open(venue, arrival) if typical_ok else None
        venues.append(
            {
                "id": vid,
                "name": venue["name"],
                "type": venue["type"],
                "miles_from_center": round(
                    radar.distance(
                        center.latitude, center.longitude, venue["latitude"], venue["longitude"]
                    ),
                    3,
                ),
                "live_percent": live,
                "typical_percent_at_arrival": typical,
                "live_retrieved_at": venue.get("live_retrieved_at"),
                "typical_retrieved_at": venue.get("typical_retrieved_at"),
                "scheduled_open_at_arrival": is_open,
                "schedule_note": "Weekly provider schedule, not a real-time closure observation",
                "measurement_time": None,
                "provenance": venue["provenance"],
            }
        )
    return {
        "id": center.id,
        "name": center.label,
        "decision_time": at.isoformat(),
        "arrival_at": arrival.isoformat(),
        "route": route,
        "venues": venues,
        "coverage": coverage,
        "neighborhood": copy.deepcopy(neighborhood),
    }


def rank_areas(briefs, *, enabled=False, structural=False):
    if not enabled:
        raise ValueError("Area algorithm is experimental; explicit enabled=True is required")
    results = []
    for area in briefs:
        contributions = []
        for v in area["venues"]:
            value = (
                v["live_percent"]
                if v["live_percent"] is not None
                else v["typical_percent_at_arrival"]
            )
            live = v["live_percent"] is not None
            if value is None or value < 20 or v["scheduled_open_at_arrival"] is False:
                continue
            weight = type_weight(v["type"])
            # Thresholds classify activity within each venue, never compare its
            # absolute attendance with another venue. Corroboration saturates at 4.
            points = (24 if live else 8) * weight
            contributions.append(
                {
                    "id": v["id"],
                    "points": points,
                    "basis": "live activity" if live else "typical pattern",
                }
            )
        contributions.sort(key=lambda v: (-v["points"], v["id"]))
        activity = sum(
            v["points"] * discount for v, discount in zip(contributions[:4], (1, 0.6, 0.35, 0.2))
        )
        baseline = 0.0
        profile = area.get("neighborhood") or {}
        density = profile.get("metrics", {}).get("population_per_land_sq_mile", {})
        estimate, moe = density.get("estimate"), density.get("moe90_approx")
        if (
            structural
            and profile.get("state") == "available"
            and radar.number(estimate)
            and radar.number(moe)
            and estimate > 0
            and moe <= estimate * 0.5
        ):
            # Small bounded sensitivity experiment; geography approximation makes
            # this unsuitable for automatic production promotion.
            baseline = min(4.0, 4 * math.log1p(max(0, estimate - moe)) / math.log1p(15000))
        travel = area["route"]["minutes"] * 0.45
        results.append(
            {
                "id": area["id"],
                "activity_points": round(activity, 3),
                "structural_points": round(baseline, 3),
                "income_points": 0,
                "travel_penalty": round(travel, 3),
                "score": round(activity + baseline - travel, 3),
                "support": contributions[:4],
                "uncertainties": [
                    "No observed Uber requests, driver competition, or conversion rates.",
                    "Source samples are incomplete; missing activity is unknown.",
                    "Type weights and thresholds are test hypotheses, not learned probabilities.",
                ],
            }
        )
    return sorted(results, key=lambda v: (-v["score"], v["id"]))


def model_input(briefs, *, structural=False):
    """Identical observations, no algorithm score/order or preferred winner leaked."""
    aliases = {
        vid: f"v{i}" for i, vid in enumerate(sorted({v["id"] for a in briefs for v in a["venues"]}))
    }
    return {
        "decision_time": briefs[0]["decision_time"] if briefs else None,
        "limitations": [
            "Percentages are relative to each venue's own peak, not people counts.",
            "Missing live data is unknown; zero does not mean closed.",
            "No measured Uber demand or driver competition. Income is descriptive only.",
            "Schedules are typical weekly hours, not verified real-time opening.",
            "Neighborhood footprints are whole block groups, not exact 1 km circles.",
        ],
        "venue_columns": [
            "id",
            "name",
            "type",
            "live_percent",
            "typical_percent_at_arrival",
            "miles_from_center",
            "scheduled_open_at_arrival",
        ],
        "areas": [
            {
                "id": a["id"],
                "name": a["name"],
                "route": a["route"],
                "arrival_at": a["arrival_at"],
                "venues": [
                    [
                        aliases[v["id"]],
                        *[
                            v[k]
                            for k in (
                                "name",
                                "type",
                                "live_percent",
                                "typical_percent_at_arrival",
                                "miles_from_center",
                                "scheduled_open_at_arrival",
                            )
                        ],
                    ]
                    for v in a["venues"]
                    if v["live_percent"] is not None or (v["typical_percent_at_arrival"] or 0) > 0
                ],
                "omission_note": "Rows with unavailable live and zero/missing arrival pattern are omitted, not declared closed.",
                "omitted_rows": sum(
                    v["live_percent"] is None and not (v["typical_percent_at_arrival"] or 0) > 0
                    for v in a["venues"]
                ),
                "coverage": [
                    {k: c[k] for k in ("state", "retrieved_at", "returned", "possibly_truncated")}
                    for c in a["coverage"]
                ],
                "neighborhood": (
                    {
                        "state": (a.get("neighborhood") or {}).get("state", "unavailable"),
                        "period": "2020-2024",
                        "metrics": {
                            k: {f: value.get(f) for f in ("estimate", "moe90_approx")}
                            for k, value in (a.get("neighborhood") or {}).get("metrics", {}).items()
                        },
                        "income_role": "descriptive only; no automatic ranking bonus",
                    }
                    if structural
                    else None
                ),
            }
            for a in sorted(briefs, key=lambda a: a["id"])
        ],
    }
