import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from farol.adapters import gather_signals, is_wamu_exit, mock_feeds_active
from farol.adapters.routes import TTL_SECONDS as ROUTE_TTL_SECONDS
from farol.brain import apply as apply_brain
from farol.dashboard import FIXTURES
from farol.evidence import parse_time
from farol.narration_contract import duration_text
from farol.ratecard import public as rate_card
from farol.signals import Anchor, RouteEstimate, Signal, load_anchors
from farol.trips import personal_insights, sit_here
from farol.zones import canonical_zone, load_zones

MIN_OPPORTUNITY_SCORE = 5.0
DEFAULT_VALUE_OF_TIME = 22.0
PRIMARY_KINDS = {
    "closing_wave",
    "event_exit",
    "special_event",
    "cruise_disembark",
    "airport_arrivals",
}

ROAD_FACTOR = 1.3
ASSUMED_AVERAGE_MPH = 27.0
STAY_MARGIN = 4.0
SEATTLE_SIDE = {
    "sodo_stadiums",
    "seattle_center",
    "capitol_hill",
    "fremont_ballard",
    "sea_airport",
}


def _fixture_routes(vehicle_cost_per_mile: float) -> dict[str, RouteEstimate]:
    payload = json.loads((FIXTURES / "tonight_routes.json").read_text(encoding="utf-8"))
    return {
        item["destination_anchor_id"]: RouteEstimate(
            origin_zone=payload["origin_zone"],
            destination_anchor_id=item["destination_anchor_id"],
            traffic_minutes=item["traffic_minutes"],
            distance_miles=item["distance_miles"],
            vehicle_cost=round(item["distance_miles"] * vehicle_cost_per_mile, 2),
            basis=payload["basis"],
            source=payload["source"],
            fetched_at=payload["fetched_at"],
        )
        for item in payload["routes"]
    }


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_miles = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return radius_miles * 2 * math.asin(math.sqrt(a))


def home_origin() -> tuple[str, float, float]:
    registry = load_zones()
    return "kirkland_home", registry.origin_latitude, registry.origin_longitude


def _assumed_route(
    anchor: Anchor,
    origin_zone: str,
    origin_lat: float,
    origin_lon: float,
    vehicle_cost_per_mile: float,
    as_of: str,
) -> RouteEstimate:
    """Distance-based estimate until a traffic feed exists; explicitly assumed basis."""
    miles = round(
        _haversine_miles(origin_lat, origin_lon, anchor.latitude, anchor.longitude) * ROAD_FACTOR,
        1,
    )
    minutes = round(miles / ASSUMED_AVERAGE_MPH * 60, 0)
    return RouteEstimate(
        origin_zone=origin_zone,
        destination_anchor_id=anchor.id,
        traffic_minutes=minutes,
        distance_miles=miles,
        vehicle_cost=round(miles * vehicle_cost_per_mile, 2),
        basis="assumed",
        source="farol:zone-distance estimate (no traffic feed)",
        fetched_at=as_of,
    )


def _route_for(
    anchor: Anchor,
    fixture_routes: dict[str, RouteEstimate] | None,
    live_routes: dict[str, RouteEstimate] | None,
    origin_zone: str,
    origin_lat: float,
    origin_lon: float,
    vehicle_cost_per_mile: float,
    as_of: str,
) -> RouteEstimate:
    if fixture_routes is not None and anchor.id in fixture_routes:
        return fixture_routes[anchor.id]
    if live_routes and anchor.id in live_routes:
        route = live_routes[anchor.id]
        fetched, current = parse_time(route.fetched_at), parse_time(as_of)
        # A recorded/live leg is only current inside the route adapter's TTL.
        # Allow one minute of collection latency, but reject unknown/future clocks.
        fresh = bool(fetched and current and fetched.tzinfo and current.tzinfo
                     and -60 <= (current - fetched).total_seconds() <= ROUTE_TTL_SECONDS)
        if route.basis != "live" or fresh:
            return route
    return _assumed_route(
        anchor, origin_zone, origin_lat, origin_lon, vehicle_cost_per_mile, as_of
    )


def _signal_value(signal: Signal) -> float:
    if signal.details.get("context_only"):
        return 0
    if signal.kind == "closing_wave":
        return signal.magnitude * 3
    if signal.kind == "event_exit":
        return min(signal.magnitude / 1000, 20)
    if signal.kind == "special_event":
        return min(signal.magnitude / 1000, 14)
    if signal.kind == "cruise_disembark":
        return min(signal.magnitude / 1000, 12)
    if signal.kind == "airport_arrivals":
        return min(signal.magnitude, 10)
    if signal.kind == "doctrine_penalty":
        return -signal.magnitude
    if signal.kind == "highway_alert":
        return -min(signal.magnitude, 8)
    if signal.kind == "travel_delay":
        return -min(signal.magnitude / 2, 6)
    if signal.kind == "transit_disruption":
        return min(signal.magnitude, 20)
    return 0


def _bundle_value(local_signals: list) -> float:
    """Do not sum every named bar in a zone as if each were a separate 70k let-out."""
    closes = [item for item in local_signals if item.kind == "closing_wave"]
    traffic = [item for item in local_signals if item.kind in {"highway_alert", "travel_delay"}]
    others = [item for item in local_signals
              if item.kind not in {"closing_wave", "highway_alert", "travel_delay"}]
    # Corridor alerts are copied into several zones, not matched to the actual
    # route. Adding every alert double-counts exposure and can swamp all demand
    # signals. Google already prices traffic minutes; retain the strongest
    # corridor caution as a bounded heuristic, not an inferred route closure.
    traffic_caution = min((_signal_value(item) for item in traffic), default=0)
    other_score = sum(_signal_value(item) for item in others) + traffic_caution
    if not closes:
        return other_score
    peak = max(item.magnitude for item in closes)
    named = {
        item.details.get("venue_id") or item.id
        for item in closes
        if "last-call harvest" in str(item.details.get("title") or "")
    }
    extra = min(max(0, len(named) - 1), 5) * 1.2
    return peak * 3 + extra + other_score


def _closing_primaries(primary_signals: list) -> list:
    """One closing-wave opportunity per zone (facts still list every bar)."""
    others = [item for item in primary_signals if item.kind != "closing_wave"]
    by_zone: dict[str, list] = {}
    for item in primary_signals:
        if item.kind != "closing_wave":
            continue
        by_zone.setdefault(canonical_zone(item.zone), []).append(item)
    collapsed = []
    for rows in by_zone.values():
        collapsed.append(max(rows, key=lambda item: (item.magnitude, item.ends_at)))
    return others + collapsed


def _confidence(signals: list[Signal]) -> float:
    signals = [signal for signal in signals if not signal.details.get("context_only")]
    if not signals:
        return 0
    quality = sum(signal.evidence_quality for signal in signals) / len(signals)
    assumption_penalty = 0.12 * sum(signal.basis == "assumed" for signal in signals)
    return round(max(0.1, min(0.95, quality - assumption_penalty)), 2)


def _anchor_for(zone: str, anchors: list[Anchor]) -> Anchor | None:
    wanted = canonical_zone(zone)
    matches = [anchor for anchor in anchors if canonical_zone(anchor.zone) == wanted]
    if not matches:
        return None
    return next((anchor for anchor in matches if anchor.approval_status == "approved"), matches[0])


def _facts(signals: list[Signal], weather: list[Signal]) -> list[dict]:
    rows = []
    traffic = [item for item in signals if item.kind in {"highway_alert", "travel_delay"}]
    facts_signals = [item for item in signals if item not in traffic]
    for signal in [*facts_signals, *weather]:
        details = signal.details or {}
        row = {
            "text": details.get("title", signal.kind.replace("_", " ").title()),
            "basis": signal.basis,
            "source": signal.source,
            "signal_id": signal.id,
            "kind": signal.kind,
        }
        if signal.kind == "driver_intel" and details.get("notes"):
            row["text"] += ": " + str(details["notes"])
        if details.get("exit_timing_basis"):
            row["text"] += "; exit timing: " + duration_text(details["exit_timing_basis"])
        if details.get("attendance_basis"):
            row["text"] += "; attendance: " + str(details["attendance_basis"])
        for key in ("count", "flights", "per_hour", "page_full", "span_minutes"):
            if details.get(key) is not None:
                row[key] = details[key]
        rows.append(row)
    if traffic:
        strongest = min(traffic, key=_signal_value)
        description = strongest.details.get("headline") or strongest.details.get("title") or strongest.kind
        rows.append({
            "text": (f"{len(traffic)} published corridor alerts/delays overlap this zone window; "
                     f"exposure on this specific route is unverified. Strongest caution: {description}"),
            "basis": strongest.basis, "source": strongest.source,
            "signal_id": strongest.id, "kind": "traffic_caution",
        })
    return rows


def _event_pickup_fact(primary: Signal, local_signals: list[Signal]) -> dict | None:
    if primary.kind != "event_exit":
        return None
    if any(item.kind == "doctrine_penalty" for item in local_signals):
        text = (
            "Stadium/arena exit risk: watch an outer pickup area where riders can walk out "
            "and the car has a clear way out. Traffic controls and street access still need "
            "checking; a specific pickup curb needs driver approval."
        )
    elif is_wamu_exit(primary):
        text = (
            "Theater exit: assess local pickup access separately from a stadium crowd. "
            "Check nearby events and the way out; attendance and competing driver numbers "
            "are unverified."
        )
    else:
        return None
    return {
        "text": text, "basis": "assumed", "source": "farol:pickup-strategy",
        "signal_id": primary.id, "kind": "pickup_strategy",
    }


def _warnings(mock: bool, feeds: list[dict], anchors: list[Anchor]) -> list[str]:
    warnings = []
    if mock:
        warnings.append("Fixture feeds are active; this is not a live brief.")
    else:
        errors = [feed["adapter"] for feed in feeds if feed["mode"] == "error"]
        stale = [feed["adapter"] for feed in feeds if feed["mode"] == "stale_cache"]
        awaiting = [feed["adapter"] for feed in feeds if feed["mode"] == "needs_key"]
        warming = [feed["adapter"] for feed in feeds if feed["mode"] == "warming"]
        if errors:
            warnings.append(f"Feeds unavailable this refresh: {', '.join(errors)}.")
        if stale:
            warnings.append(f"Feeds serving stale cache: {', '.join(stale)}.")
        if awaiting:
            warnings.append(f"Feeds awaiting API keys: {', '.join(awaiting)}.")
        if warming:
            warnings.append(
                f"Research still running: {', '.join(warming)}. Refresh in a minute."
            )
    warnings.append(
        "Opportunity scores are heuristics, not Uber demand or a $/hr forecast. "
        "Hourly earnings are uncalibrated; your time floor has not been assessed."
    )
    if not any(anchor.approval_status == "approved" for anchor in anchors):
        warnings.append("All current anchors require driver approval, so navigation is disabled.")
    return warnings


@dataclass(frozen=True)
class ScoringSnapshot:
    """Captured inputs for deterministic scoring without any network requests."""

    signals: list[Signal]
    feeds: list[dict]
    anchors: list[Anchor]
    routes: dict[str, RouteEstimate]


def score_window(
    *,
    current: datetime,
    hours: float,
    vehicle_cost_per_mile: float,
    origin_zone: str,
    origin_lat: float,
    origin_lon: float,
    include_llm: bool = True,
    include_on_demand: bool = False,
    snapshot: ScoringSnapshot | None = None,
) -> dict:
    mock = mock_feeds_active() if snapshot is None else False
    window_end = current + timedelta(hours=hours)
    if snapshot is None:
        signals, feeds = gather_signals(
            current, window_end, include_llm=include_llm,
            include_on_demand=include_on_demand,
        )
        anchors = load_anchors(FIXTURES / "anchors.json")
    else:
        signals, feeds = list(snapshot.signals), list(snapshot.feeds)
        anchors = list(snapshot.anchors)
    fixture_routes = _fixture_routes(vehicle_cost_per_mile) if mock else None
    live_routes = snapshot.routes if snapshot is not None else None
    if not mock and snapshot is None:
        from farol.adapters import routes as google_routes

        live_routes, route_status = google_routes.matrix(
            origin_zone,
            origin_lat,
            origin_lon,
            anchors,
            vehicle_cost_per_mile,
            current.isoformat(),
        )
        feeds = [*feeds, route_status.public()]
    as_of = current.isoformat()
    weather = [signal for signal in signals if signal.kind == "precipitation"]
    _, home_lat, home_lon = home_origin()
    opportunities = []
    unanchored_zones: set[str] = set()
    primary_signals = _closing_primaries(
        [signal for signal in signals if signal.kind in PRIMARY_KINDS
         and not signal.details.get("context_only")]
    )
    identity_counts = Counter((canonical_zone(row.zone), row.starts_at) for row in primary_signals)
    for primary in primary_signals:
        zone = canonical_zone(primary.zone)
        starts_at, ends_at = primary.starts_at, primary.ends_at
        window_start = parse_time(starts_at)
        window_stop = parse_time(ends_at)
        if window_start is None or window_stop is None:
            continue
        local_signals = []
        for signal in signals:
            if canonical_zone(signal.zone) != canonical_zone(zone) or signal.kind == "precipitation":
                continue
            sig_start = parse_time(signal.starts_at)
            sig_end = parse_time(signal.ends_at)
            if sig_start is None or sig_end is None:
                continue
            if sig_start <= window_stop and sig_end >= window_start:
                local_signals.append(signal)
        anchor = _anchor_for(zone, anchors)
        if anchor is None:
            unanchored_zones.add(zone)
            continue
        route = _route_for(
            anchor,
            fixture_routes,
            live_routes,
            origin_zone,
            origin_lat,
            origin_lon,
            vehicle_cost_per_mile,
            as_of,
        )
        raw_signal_score = _bundle_value(local_signals)
        route_penalty = route.traffic_minutes * 0.45 + route.vehicle_cost
        if route.basis == "assumed" and not mock:
            route_penalty += 1.5
        homeward = 0.0
        if (current.hour >= 23 or current.hour < 4) and zone in SEATTLE_SIDE:
            homeward = round(
                _haversine_miles(anchor.latitude, anchor.longitude, home_lat, home_lon)
                * vehicle_cost_per_mile
                * 0.5,
                2,
            )
            route_penalty += homeward
        rain_overlap = False
        for item in weather:
            rain_start = parse_time(item.starts_at)
            rain_end = parse_time(item.ends_at)
            if rain_start is None or rain_end is None:
                continue
            if rain_start <= window_stop and rain_end >= window_start:
                rain_overlap = True
                break
        weather_adjustment = 2.5 if rain_overlap else 0
        arrive_at = current + timedelta(minutes=route.traffic_minutes)
        missed_window = arrive_at > window_stop
        score = round(raw_signal_score + weather_adjustment - route_penalty, 2)
        if missed_window:
            score = round(score - 10, 2)
        confidence = _confidence(local_signals + weather)
        if route.basis != "live":
            confidence = round(max(0.1, confidence - 0.1), 2)
        action = "MOVE" if score >= 5 and anchor.approval_status == "approved" else "WATCH"
        if score < 0 or missed_window:
            action = "AVOID"
        # HERE and narrators lead with the first fact. Keep this window's own
        # event first even when another show in the same area overlaps it.
        primary_first = [primary, *(row for row in local_signals if row.id != primary.id)]
        facts = _facts(primary_first, weather if rain_overlap else [])
        pickup_fact = _event_pickup_fact(primary, local_signals)
        if pickup_fact:
            facts.append(pickup_fact)
        if missed_window:
            facts.append(
                {
                    "text": "Would arrive after this window — chasing it burns empty miles",
                    "basis": "assumed",
                    "source": "farol:arrival-window",
                    "signal_id": primary.id,
                }
            )
        opportunities.append({
            "id": f"{zone}-{starts_at}" + (
                f"-{primary.id}" if identity_counts[(zone, starts_at)] > 1 else ""
            ),
            "zone": zone,
            "primary_signal_id": primary.id,
            "venue_name": str(primary.details.get("venue") or ""),
            "event_starts_at": primary.details.get("kickoff"),
            "show_duration_minutes": (
                round((window_start - parse_time(primary.details["kickoff"])).total_seconds() / 60, 1)
                if primary.details.get("kickoff") and parse_time(primary.details["kickoff"])
                and parse_time(primary.details["kickoff"]).tzinfo
                and window_start >= parse_time(primary.details["kickoff"]) else None
            ),
            "window_basis": "estimated",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "action": action,
            "score": score,
            "expected_net_per_hour": None,
            "expected_rate_basis": "unavailable",
            "confidence": confidence,
            "anchor": asdict(anchor),
            "navigation_available": anchor.approval_status == "approved" and action == "MOVE",
            "route": asdict(route),
            "facts": facts,
            "audit": {
                "signal_score": round(raw_signal_score, 2),
                "weather_adjustment": weather_adjustment,
                "route_penalty": round(route_penalty, 2),
                "homeward_return": homeward,
                "missed_window": missed_window,
                "formula": "signal + weather - (traffic_minutes*0.45 + vehicle_cost + late homeward)",
            },
        })
    stay_score = max(
        (item["score"] for item in opportunities if item["zone"] == canonical_zone(origin_zone)),
        default=0.0,
    )
    for item in opportunities:
        if item["action"] != "MOVE":
            continue
        if item["zone"] == canonical_zone(origin_zone):
            continue
        if item["score"] < stay_score + STAY_MARGIN:
            item["action"] = "WATCH"
            item["navigation_available"] = False
            item["audit"]["stay_hysteresis"] = True
            item["facts"] = [
                *item["facts"],
                {
                    "text": f"Stay beats this move by less than {STAY_MARGIN} points",
                    "basis": "assumed",
                    "source": "farol:stay-hysteresis",
                    "signal_id": item["id"],
                },
            ]
    opportunities.sort(key=lambda item: item["starts_at"])
    ranked = sorted(opportunities, key=lambda item: item["score"], reverse=True)
    return {
        "mock": mock,
        "as_of": as_of,
        "window_end": window_end.isoformat(),
        "signals": signals,
        "feeds": feeds,
        "anchors": anchors,
        "opportunities": opportunities,
        "ranked": ranked,
        "unanchored_zones": sorted(unanchored_zones),
    }


def tonight_brief(
    *,
    now: datetime | None = None,
    hours: float = 6,
    vehicle_cost_per_mile: float = 0.45,
    value_of_time_per_hour: float = DEFAULT_VALUE_OF_TIME,
) -> dict:
    mock = mock_feeds_active()
    if now is not None:
        current = now
    elif mock:
        fixture = json.loads((FIXTURES / "tonight_signals.json").read_text(encoding="utf-8"))
        current = datetime.fromisoformat(fixture["fixture_now"])
    else:
        current = datetime.now().astimezone()
    origin_zone, origin_lat, origin_lon = home_origin()
    scored = score_window(
        current=current,
        hours=hours,
        vehicle_cost_per_mile=vehicle_cost_per_mile,
        origin_zone=origin_zone,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
    )
    return apply_brain(brief_from_scored(
        scored, vehicle_cost_per_mile=vehicle_cost_per_mile,
        value_of_time_per_hour=value_of_time_per_hour,
    ))


def brief_from_scored(
    scored: dict, *, vehicle_cost_per_mile: float = 0.45,
    value_of_time_per_hour: float = DEFAULT_VALUE_OF_TIME,
    include_personal: bool = True,
) -> dict:
    """Build the production engine decision without fetching feeds or calling an LLM."""
    current = datetime.fromisoformat(scored["as_of"])
    mock = scored["mock"]
    opportunities = scored["opportunities"]
    ranked = scored["ranked"]
    signals = scored["signals"]
    feeds = scored["feeds"]
    anchors = scored["anchors"]
    as_of = scored["as_of"]
    window_end = scored["window_end"]
    unanchored_zones = scored["unanchored_zones"]
    candidates = [
        item for item in ranked
        if item["action"] != "AVOID" and item["score"] >= MIN_OPPORTUNITY_SCORE
    ]
    best = candidates[0] if candidates else None
    # A signal score has no calibrated conversion to dollars. Do not promise that
    # a shift clears the driver's floor, or call weak feed coverage unprofitable.
    shift_action = "CHECK WINDOW" if best else "NO CLEAR SIGNAL"
    timing = "none"
    if best:
        timing = (
            "later" if datetime.fromisoformat(best["starts_at"]) > current + timedelta(minutes=30)
            else "now"
        )
    signal_explanation = (
        f"The strongest reachable signal window is {'later tonight' if timing == 'later' else 'nearby in time'}. "
        "Review its timing and evidence before heading out."
        if best else
        "The available feeds do not show a clear reachable opportunity. "
        "That does not establish that driving would be unprofitable."
    )
    basis_counts = {basis: 0 for basis in ("scheduled", "live", "assumed")}
    for signal in signals:
        basis_counts[signal.basis] += 1
    brief = {
        "mode": "TONIGHT BRIEF · FIXTURE FEEDS" if mock else "TONIGHT BRIEF · LIVE FEEDS",
        "as_of": as_of,
        "window_end": window_end,
        "mock_feeds": mock,
        "shift_decision": {
            "action": shift_action,
            "best_window": None
            if best is None
            else {"starts_at": best["starts_at"], "ends_at": best["ends_at"]},
            "best_zone": None if best is None else best["zone"],
            "value_of_time_per_hour": value_of_time_per_hour,
            "basis": "signal_only",
            "signal_timing": timing,
            "earnings_status": "uncalibrated",
            "value_of_time_met": None,
            "explanation": signal_explanation,
            "earnings_explanation": (
                f"Whether this clears your ${value_of_time_per_hour:.0f}/hr floor is unknown. "
                "Receipts show past earnings; total shift time and all driving miles "
                "are needed to measure net earnings per hour."
            ),
        },
        "opportunities": opportunities,
        "ranked_opportunity_ids": [item["id"] for item in ranked],
        "basis_counts": basis_counts,
        "feeds": feeds,
        "unanchored_zones": unanchored_zones,
        "warnings": _warnings(mock, feeds, anchors),
        "brain": None,
        "narration": None,
        "rate_card": rate_card(),
        "personal": personal_insights(vehicle_cost_per_mile=vehicle_cost_per_mile) if include_personal else None,
        "sit_here": sit_here(
            now=current,
            origin_zone=load_zones().home_zone,
            hours=3,
            value_of_time_per_hour=value_of_time_per_hour,
            vehicle_cost_per_mile=vehicle_cost_per_mile,
        ) if include_personal else None,
        "watch": [
            {
                "title": signal.details.get("title", signal.kind),
                "text": signal.details.get("notes", ""),
                "source": signal.source,
                "basis": signal.basis,
                "zone": signal.zone,
            }
            for signal in signals
            if signal.kind == "driver_intel" or signal.details.get("watchlist")
        ],
    }
    return brief
