"""Resolve 'I'm here' to a zone and a sit-here line.

The driver names a town or cross street. Python owns the ranking from official
receipts minus reposition. A Grok Bot may speak this card; it may not invent a
neighborhood $/hr or an Uber heatmap.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from farol import tonight
from farol.evidence import format_clock
from farol.recommend import STREET_ZONES, _haversine_miles
from farol.tonight import score_window
from farol.trips import load_observed_trips, sit_here
from farol.zones import PickupCenter, canonical_zone, load_zones

ACTION_PLAIN = {
    "WAIT": "Stay here",
    "STAY": "Stay here",
    "WATCH": "No clear recommendation to move yet",
    "MOVE": "Worth the drive",
    "AVOID": "Skip this",
    "DRIVE": "Worth going out",
    "SKIP": "Stay in / skip",
    "WAIT TO START": "Don't start yet",
}

ARRIVAL_RADIUS_MILES = 0.25
ARRIVAL_RADIUS_MINUTES = 2.0

EASTSIDE_ZONES = {
    "bellevue_core",
    "kirkland_waterfront",
    "kirkland_downtown",
    "kirkland_rose_hill",
    "kirkland_totem_lake",
    "totem_lake",
    "redmond_downtown",
    "redmond_core",
    "woodinville_wine",
    "woodinville",
    "marymoor",
    "cottage_lake",
    "issaquah",
}
SEATTLE_LAKE_ZONES = {
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


def _sr520_toll_dollars(dt: datetime) -> float:
    """WSTC SR 520 variable Good To Go! toll schedule estimate by local hour/weekday."""
    local = dt.astimezone()
    hr = local.hour
    if hr >= 23 or hr < 5:
        return 1.25
    is_weekend = local.weekday() >= 5
    if is_weekend:
        return 2.65 if 11 <= hr < 18 else 1.85
    if 7 <= hr < 10 or 15 <= hr < 19:
        return 4.50
    if 10 <= hr < 15 or 19 <= hr < 21:
        return 3.70
    return 2.20


def _road_cost_summary(
    origin_zone: str,
    dest_zone: str,
    miles: float | None,
    vehicle_cost_per_mile: float,
    dt: datetime,
) -> dict:
    dist = float(miles or 0.0)
    empty_cost = round(dist * vehicle_cost_per_mile, 2)
    crosses_lake = (origin_zone in EASTSIDE_ZONES and dest_zone in SEATTLE_LAKE_ZONES) or (
        origin_zone in SEATTLE_LAKE_ZONES and dest_zone in EASTSIDE_ZONES
    )
    sr520_toll = _sr520_toll_dollars(dt) if crosses_lake else 0.0
    return {
        "empty_miles": round(dist, 1),
        "empty_drive_cost": empty_cost,
        "crosses_lake": crosses_lake,
        "sr520_toll_dollars": sr520_toll,
        "total_move_cost_with_sr520": round(empty_cost + sr520_toll, 2),
        "cost_note": (
            f"Empty drive ${empty_cost:.2f} (+${sr520_toll:.2f} if via SR 520; $0 toll via I-90)"
            if crosses_lake
            else (f"Empty drive ${empty_cost:.2f} ({dist:.1f} mi)" if dist > 0 else "Stay put — $0 empty drive")
        ),
    }

COORD_RE = re.compile(r"(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)")

# Longer phrases first at match time. Keep this Eastside-driver grain, not Seattle-wide.
PLACES: tuple[tuple[str, str, str], ...] = (
    ("the lime", "kirkland_rose_hill", "The Lime, Rose Hill Plaza"),
    ("rose hill plaza", "kirkland_rose_hill", "Rose Hill Plaza"),
    ("85th and 122nd", "kirkland_rose_hill", "NE 85th St & 122nd Ave NE"),
    ("122nd and 85th", "kirkland_rose_hill", "122nd Ave NE & NE 85th St"),
    ("85th and 124th", "kirkland_rose_hill", "NE 85th St & 124th Ave NE"),
    ("124th and 85th", "kirkland_rose_hill", "124th Ave NE & NE 85th St"),
    ("405 and 85th", "kirkland_rose_hill", "I-405 & NE 85th"),
    ("slater and 85th", "kirkland_rose_hill", "Slater Ave & NE 85th"),
    ("124th and 405", "totem_lake", "I-405 & NE 124th"),
    ("405 and 124th", "totem_lake", "I-405 & NE 124th"),
    ("totem lake village", "totem_lake", "Village at Totem Lake"),
    ("village at totem lake", "totem_lake", "Village at Totem Lake"),
    ("totem lake blvd", "totem_lake", "Totem Lake Blvd"),
    ("sample residential street", "totem_lake", "Kingsgate / sample residential street"),
    ("sample street", "totem_lake", "Kingsgate / sample residential street"),
    ("kingsgate", "totem_lake", "Kingsgate"),
    ("ne 124th", "totem_lake", "NE 124th St"),
    ("parkplace", "kirkland_waterfront", "Kirkland Parkplace"),
    ("park place", "kirkland_waterfront", "Kirkland Parkplace"),
    ("peter kirk", "kirkland_waterfront", "Peter Kirk Park"),
    ("kirkland marina", "kirkland_waterfront", "Kirkland Marina"),
    ("lake street", "kirkland_waterfront", "Lake St / Kirkland waterfront"),
    ("central way", "kirkland_waterfront", "Central Way"),
    ("downtown kirkland", "kirkland_waterfront", "Downtown Kirkland"),
    ("juanita village", "kirkland_waterfront", "Juanita is not its own Farol zone yet"),
    ("juanita", "kirkland_waterfront", "Juanita is not its own Farol zone yet"),
    ("houghton", "kirkland_waterfront", "Houghton / Kirkland waterfront"),
    ("finn hill", "kirkland_waterfront", "Finn Hill, mapped to Kirkland waterfront"),
    ("rose hill", "kirkland_rose_hill", "Kirkland Rose Hill"),
    ("bridle trails", "kirkland_rose_hill", "Bridle Trails / Rose Hill"),
    ("lincoln square", "bellevue_core", "Lincoln Square"),
    ("bellevue square", "bellevue_core", "Bellevue Square"),
    ("bellevue downtown", "bellevue_core", "Downtown Bellevue"),
    ("405 and 8th", "bellevue_core", "I-405 & NE 8th"),
    ("8th and 405", "bellevue_core", "NE 8th & I-405"),
    ("redmond town center", "redmond_downtown", "Redmond Town Center"),
    ("marymoor", "marymoor", "Marymoor Park — event geometry not a street WAIT pin"),
    ("husky stadium", "uw_district", "Husky Stadium — event pickup, not a legal WAIT pin yet"),
    ("u-district", "uw_district", "University District"),
    ("u district", "uw_district", "University District"),
    ("udistrict", "uw_district", "University District"),
    ("university of washington", "uw_district", "UW campus / Husky Stadium"),
    ("montlake", "uw_district", "Montlake / Husky Stadium"),
    ("kirkland performance center", "kirkland_waterfront", "Kirkland Performance Center"),
    ("meydenbauer", "bellevue_core", "Meydenbauer Center"),
    ("village theatre", "issaquah", "Village Theatre Issaquah"),
    ("5th avenue", "seattle_core", "5th Avenue Theatre"),
    ("woodland park zoo", "fremont_ballard", "Woodland Park Zoo / ZooTunes"),
    ("zootunes", "fremont_ballard", "ZooTunes"),
    ("hec ed", "uw_district", "Hec Edmundson Pavilion"),
    ("huskies", "uw_district", "UW Huskies / Husky Stadium"),
    ("uw", "uw_district", "UW / Husky Stadium"),
    ("hollywood schoolhouse", "woodinville_wine", "Woodinville Hollywood District"),
    ("chateau ste michelle", "woodinville_wine", "Chateau Ste. Michelle area"),
    ("woodinville", "woodinville_wine", "Woodinville wine district"),
    ("cottage lake", "cottage_lake", "Cottage Lake"),
    ("cell phone lot", "sea_airport", "SEA cell phone / staging — FIFO board, not streets"),
    ("seatac", "sea_airport", "SEA airport — FIFO board, not streets"),
    ("sea airport", "sea_airport", "SEA airport — FIFO board, not streets"),
    ("totem lake", "totem_lake", "Totem Lake"),
    ("kirkland", "kirkland_waterfront", "Kirkland (defaulting to waterfront; say Rose Hill if you are on 122nd/85th)"),
    ("bellevue", "bellevue_core", "Bellevue core"),
    ("redmond", "redmond_downtown", "Redmond downtown"),
)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _zone_payload(
    zone_id: str,
    matched: str,
    note: str,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    origin_kind: str = "zone_centroid",
    place_id: str | None = None,
) -> dict:
    registry = load_zones()
    zone = registry.by_id[zone_id]
    return {
        "zone": zone.id,
        "label": zone.label,
        "cluster": zone.cluster,
        "latitude": latitude if latitude is not None else zone.latitude,
        "longitude": longitude if longitude is not None else zone.longitude,
        "matched": matched,
        "note": note,
        "street_board": zone.id in STREET_ZONES,
        "origin_kind": origin_kind,
        "place_id": place_id or zone.id,
    }


def _nearest(latitude: float, longitude: float) -> dict:
    registry = load_zones()
    best = None
    best_miles = None
    for zone in registry.zones:
        miles = _haversine_miles(latitude, longitude, zone.latitude, zone.longitude)
        if best_miles is None or miles < best_miles:
            best_miles = miles
            best = zone
    assert best is not None
    home_miles = _haversine_miles(
        latitude, longitude, registry.origin_latitude, registry.origin_longitude
    )
    origin_kind = "gps_pin"
    place_id = f"pin_{best.id}"
    if home_miles <= ARRIVAL_RADIUS_MILES:
        origin_kind = "residential_home"
        place_id = "example_public_origin"
    else:
        for pc in registry.pickup_centers:
            if _haversine_miles(latitude, longitude, pc.latitude, pc.longitude) <= 0.35:
                origin_kind = "pickup_center"
                place_id = pc.id
                break
    note = f"nearest named zone, {best_miles:.1f} mi from pin"
    return _zone_payload(
        best.id,
        f"{latitude:.4f},{longitude:.4f}",
        note,
        latitude=latitude,
        longitude=longitude,
        origin_kind=origin_kind,
        place_id=place_id,
    )


RESIDENTIAL_HOME_PHRASES = {"sample residential street", "sample street", "kingsgate"}
BROAD_AREA_PHRASES = {"totem lake", "kirkland", "bellevue", "redmond", "woodinville"}
PICKUP_CENTER_PHRASES: dict[str, str] = {
    "totem lake village": "totem_lake_village",
    "village at totem lake": "totem_lake_village",
    "totem lake blvd": "totem_lake_village",
    "downtown kirkland": "kirkland_waterfront",
    "kirkland marina": "kirkland_waterfront",
    "lake street": "kirkland_waterfront",
    "central way": "kirkland_waterfront",
    "parkplace": "kirkland_waterfront",
    "park place": "kirkland_waterfront",
    "kirkland performance center": "kirkland_waterfront",
    "the lime": "kirkland_rose_hill",
    "rose hill plaza": "kirkland_rose_hill",
    "85th and 124th": "kirkland_rose_hill",
    "124th and 85th": "kirkland_rose_hill",
    "lincoln square": "bellevue_core",
    "bellevue square": "bellevue_core",
    "bellevue downtown": "bellevue_core",
    "meydenbauer": "bellevue_core",
    "redmond town center": "redmond_downtown",
    "hollywood schoolhouse": "woodinville_wine",
    "chateau ste michelle": "woodinville_wine",
}
NEIGHBORHOOD_COORDS: dict[str, tuple[float, float]] = {
    "juanita": (47.703, -122.209),
    "juanita village": (47.703, -122.209),
    "houghton": (47.662, -122.198),
    "finn hill": (47.721, -122.231),
    "bridle trails": (47.652, -122.164),
    "rose hill": (47.6794, -122.1813),
    "ne 124th": (47.711, -122.176),
    "peter kirk": (47.678, -122.202),
}


def _is_center_approved(pc: PickupCenter, anchors: list) -> bool:
    for anchor in anchors:
        aid = str(getattr(anchor, "id", "") or "")
        azone = str(getattr(anchor, "zone", "") or "")
        astatus = str(getattr(anchor, "approval_status", "") or "")
        if (aid and aid in {pc.anchor_id, pc.id}) or (not pc.anchor_id and azone == pc.zone):
            if astatus == "approved":
                return True
    return False


def resolve(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("say where you are: a town, a cross street, or lat,lon")
    coords = COORD_RE.search(raw.replace("(", " ").replace(")", " "))
    if coords:
        latitude, longitude = float(coords.group(1)), float(coords.group(2))
        if not (47 <= latitude <= 48.2 and -123 <= longitude <= -121.5):
            raise ValueError("Location is outside Farol's Seattle/Eastside coverage")
        return _nearest(latitude, longitude)
    blob = _normalize(raw)
    registry = load_zones()
    if blob in {"home", "at home", "i m at home", "i m home", "i am home"}:
        return _zone_payload(
            registry.home_zone,
            "home",
            f"home zone ({registry.home_zone.replace('_', ' ')})",
            latitude=registry.origin_latitude,
            longitude=registry.origin_longitude,
            origin_kind="residential_home",
            place_id="example_public_origin",
        )
    for phrase, zone_id, note in sorted(PLACES, key=lambda item: len(item[0]), reverse=True):
        if phrase in blob:
            if phrase in RESIDENTIAL_HOME_PHRASES:
                return _zone_payload(
                    zone_id,
                    phrase,
                    note,
                    latitude=registry.origin_latitude,
                    longitude=registry.origin_longitude,
                    origin_kind="residential_home",
                    place_id="example_public_origin",
                )
            pc_id = PICKUP_CENTER_PHRASES.get(phrase)
            if pc_id is not None:
                pc = next((c for c in registry.pickup_centers if c.id == pc_id), None)
                if pc is not None:
                    return _zone_payload(
                        zone_id,
                        phrase,
                        note,
                        latitude=pc.latitude,
                        longitude=pc.longitude,
                        origin_kind="pickup_center",
                        place_id=pc.id,
                    )
            if phrase not in BROAD_AREA_PHRASES:
                ncoords = NEIGHBORHOOD_COORDS.get(phrase)
                return _zone_payload(
                    zone_id,
                    phrase,
                    note,
                    latitude=ncoords[0] if ncoords else None,
                    longitude=ncoords[1] if ncoords else None,
                    origin_kind="neighborhood",
                    place_id=_normalize(phrase).replace(" ", "_"),
                )
            return _zone_payload(zone_id, phrase, note, origin_kind="zone_centroid", place_id=zone_id)
    slug = blob.replace(" ", "_")
    canon = canonical_zone(slug)
    if canon in registry.by_id:
        zone = registry.by_id[canon]
        return _zone_payload(canon, slug, zone.label, origin_kind="zone_centroid", place_id=canon)
    raise ValueError(
        f"couldn't place {raw!r} on the Farol map. Try Kirkland, Rose Hill, "
        "85th and 122nd, Bellevue, Redmond, Totem Lake, Woodinville, or SEA."
    )


def is_calibrated_historical_move(
    stay_row: dict | None,
    target_row: dict | None,
    *,
    stay_samples: int,
    max_reposition_minutes: float,
    drive_minutes: float,
    min_score_advantage: float = 12.0,
) -> bool:
    """Return True when target has calibrated non-thin history and beats origin after travel cost."""
    if not target_row:
        return False
    target_samples = int(target_row.get("sample_trips") or 0)
    target_grain = str(target_row.get("grain") or "none")
    target_thin = (
        bool(target_row.get("thin", True))
        or target_grain == "none"
        or (target_samples < 5 and (target_samples < 3 or target_grain == "zone"))
    )
    if target_thin:
        return False
    if not (0 < drive_minutes <= max_reposition_minutes):
        return False
    target_score = float(target_row.get("score") or target_row.get("historical_net_per_hour") or 0.0)
    stay_thin = bool((stay_row or {}).get("thin", True)) or stay_samples < 2
    stay_score = (
        float((stay_row or {}).get("score") or (stay_row or {}).get("historical_net_per_hour") or 0.0)
        if not stay_thin
        else 0.0
    )
    if stay_thin:
        return target_samples >= 5 and target_score >= max(stay_score + min_score_advantage, 38.0)
    if target_grain in {"none", "zone"}:
        return False
    return target_score >= stay_score + min_score_advantage


def _evaluate_positioning_candidates(
    place: dict,
    now_rows: list[dict],
    current: datetime | None,
    *,
    max_reposition_minutes: float = 20.0,
    vehicle_cost_per_mile: float = 0.45,
    origin_trip_samples: int = 0,
) -> tuple[dict | None, list[dict]]:
    registry = load_zones()
    live_anchors = tonight.load_anchors()
    now_dt = (current or datetime.now().astimezone()).astimezone()
    hr = now_dt.hour
    origin_lat = float(place["latitude"])
    origin_lon = float(place["longitude"])
    is_residential = place.get("origin_kind") == "residential_home"
    row_by_zone = {r["zone"]: r for r in now_rows}
    stay_row = row_by_zone.get(place["zone"])
    stay_samples = origin_trip_samples if is_residential else int((stay_row or {}).get("sample_trips") or 0)
    stay_score = float((stay_row or {}).get("score") or 0.0) if stay_samples > 0 else 0.0

    candidates: list[dict] = []
    rejected: list[dict] = []

    for pc in registry.pickup_centers:
        start_hr, end_hr = pc.active_start_hour, pc.active_end_hour
        in_hours = start_hr <= hr <= end_hr
        is_curb_approved = _is_center_approved(pc, live_anchors)
        if not in_hours:
            rejected.append({"id": pc.id, "zone": pc.zone, "reason": f"outside_active_hours ({start_hr}:00-{end_hr}:00)"})
            continue
        straight_miles = _haversine_miles(origin_lat, origin_lon, pc.latitude, pc.longitude)
        if straight_miles <= ARRIVAL_RADIUS_MILES:
            rejected.append({"id": pc.id, "zone": pc.zone, "reason": "already_within_arrival_radius"})
            continue
        road_miles = round(max(straight_miles * 1.35, 0.5), 2)
        road_minutes = round(max(road_miles * 2.8 + 0.5, 2.5), 1)
        z_row = row_by_zone.get(pc.zone)
        if z_row and float(z_row.get("reposition_minutes") or 0.0) > road_minutes:
            road_minutes = round(float(z_row["reposition_minutes"]), 1)
            road_miles = round(float(z_row.get("reposition_miles") or road_miles), 2)
        if road_minutes > max_reposition_minutes:
            rejected.append({"id": pc.id, "zone": pc.zone, "reason": f"exceeds_max_reposition_minutes ({road_minutes} > {max_reposition_minutes})"})
            continue

        tier_base = float(pc.suitability_score)
        travel_penalty = road_minutes * 0.85 + road_miles * vehicle_cost_per_mile * 2.0
        hist_samples = int((z_row or {}).get("sample_trips") or 0)
        hist_score = float((z_row or {}).get("score") or 0.0)
        hist_bonus = 0.0
        basis = "positioning_heuristic"
        if pc.zone != place["zone"] and is_calibrated_historical_move(
            stay_row,
            z_row,
            stay_samples=stay_samples,
            max_reposition_minutes=max_reposition_minutes,
            drive_minutes=road_minutes,
            min_score_advantage=10.0,
        ):
            hist_bonus = min((hist_score - stay_score) * 0.25, 25.0)
            basis = "historical_and_positioning"

        suitability_rank = round(tier_base - travel_penalty + hist_bonus, 2)
        curb_note = (
            pc.staging_spot
            if is_curb_approved
            else f"{pc.label} area (specific legal waiting curb requires driver approval)"
        )
        candidates.append({
            "id": pc.id,
            "anchor_id": pc.anchor_id or pc.id,
            "zone": pc.zone,
            "name": pc.label,
            "latitude": pc.latitude,
            "longitude": pc.longitude,
            "reposition_minutes": road_minutes,
            "reposition_miles": road_miles,
            "suitability_rank": suitability_rank,
            "recommendation_basis": basis,
            "staging_approved": is_curb_approved,
            "navigation_available": is_curb_approved,
            "staging_notes": curb_note,
            "suitability_reason": (
                f"Nearby pickup center ({curb_note}) open {start_hr}:00–{end_hr}:00; "
                "current rider demand is unverified."
            ),
            "sample_trips": hist_samples if basis != "positioning_heuristic" else 0,
            "score": hist_score if (basis != "positioning_heuristic" and hist_samples > 0) else 0.0,
            "historical_zone_score": hist_score,
            "historical_mean_earnings": float((z_row or {}).get("historical_mean_earnings") or 0.0),
            "grain": str((z_row or {}).get("grain") or "none"),
            "thin": bool((z_row or {}).get("thin", True)),
        })

    candidates.sort(key=lambda c: (-c["suitability_rank"], c["reposition_minutes"]))
    return (candidates[0] if candidates else None), rejected


def _pick_action(
    place: dict,
    now_rows: list[dict],
    opportunities: list[dict] | None = None,
    *,
    current: datetime | None = None,
    driver_mode: str = "active_working",
    max_reposition_minutes: float = 20.0,
    vehicle_cost_per_mile: float = 0.45,
    origin_trip_samples: int = 0,
) -> tuple[str, dict | None, dict | None]:
    if not now_rows:
        return "WATCH", None, None
    stay = next((row for row in now_rows if row["zone"] == place["zone"]), None)
    best = now_rows[0]
    if place["zone"] == "sea_airport":
        return "WATCH", stay, best
    if driver_mode in {"offline", "break", "on_break", "wait_at_home", "waiting_at_home"}:
        if (
            place.get("origin_kind") != "residential_home"
            and stay
            and int(stay.get("sample_trips") or 0) > 0
            and driver_mode not in {"offline", "break", "on_break"}
        ):
            return "WAIT", stay, stay
        return "WATCH", stay, best

    is_residential = place.get("origin_kind") == "residential_home"
    row_by_zone = {r["zone"]: r for r in now_rows}
    stay_samples = origin_trip_samples if is_residential else int((stay or {}).get("sample_trips") or 0)
    stay_score = float((stay or {}).get("score") or 0.0) if stay_samples > 0 else 0.0
    now_dt = current.astimezone() if current else None

    # Compute local opportunity score on the same event/window point scale (never mix $/hr with event points)
    local_opp_score = 0.0
    for opp in opportunities or []:
        if str(opp.get("zone") or "") != place["zone"] or is_residential:
            continue
        route = opp.get("route") or {}
        mins = route.get("traffic_minutes")
        miles = route.get("distance_miles")
        mins_f = float(mins) if isinstance(mins, (int, float)) else 0.0
        miles_f = float(miles) if isinstance(miles, (int, float)) else 0.0
        if mins_f <= ARRIVAL_RADIUS_MINUTES and miles_f <= ARRIVAL_RADIUS_MILES:
            local_opp_score = max(local_opp_score, float(opp.get("score") or 0.0))

    qualifying_opps: list[tuple[float, dict, float, float]] = []
    for opp in opportunities or []:
        opp_zone = str(opp.get("zone") or "")
        if not opp_zone or opp_zone == "sea_airport":
            continue
        if opp.get("action") != "MOVE":
            continue
        opp_score = float(opp.get("score") or 0.0)
        if opp_score < 6.0:
            continue
        anchor = opp.get("anchor") or {}
        nav_ok = bool(opp.get("navigation_available")) or anchor.get("approval_status") == "approved"
        if not nav_ok:
            continue
        route = opp.get("route") or {}
        mins = route.get("traffic_minutes")
        miles = route.get("distance_miles")
        if not isinstance(mins, (int, float)) or float(mins) < 0 or float(mins) > max_reposition_minutes:
            continue
        mins_f = float(mins)
        miles_f = float(miles) if isinstance(miles, (int, float)) else round(mins_f * 0.35, 2)
        if (
            opp_zone == place["zone"]
            and mins_f <= ARRIVAL_RADIUS_MINUTES
            and miles_f <= ARRIVAL_RADIUS_MILES
            and not is_residential
        ):
            continue
        if now_dt and opp.get("ends_at"):
            try:
                ends_dt = datetime.fromisoformat(str(opp["ends_at"]))
                if now_dt + timedelta(minutes=mins_f + 10.0) > ends_dt:
                    continue
            except ValueError:
                pass
        if opp_score > local_opp_score + 2.0:
            qualifying_opps.append((opp_score, opp, mins_f, miles_f))

    if qualifying_opps:
        qualifying_opps.sort(key=lambda item: (-item[0], item[2]))
        opp_score, top_opp, mins_f, miles_f = qualifying_opps[0]
        opp_zone = str(top_opp["zone"])
        base_row = dict(row_by_zone.get(opp_zone) or best or {})
        anchor = top_opp.get("anchor") or {}
        base_row.update({
            "zone": opp_zone,
            "score": opp_score,
            "reposition_minutes": round(mins_f, 1),
            "reposition_miles": round(miles_f, 2),
            "route_basis": str((top_opp.get("route") or {}).get("basis") or "live"),
            "recommendation_basis": "live_opportunity",
            "opportunity_id": top_opp.get("id"),
            "destination_id": str(anchor.get("id") or top_opp.get("id") or opp_zone),
            "destination_label": str(anchor.get("name") or opp_zone.replace("_", " ")),
            "staging_approved": True,
            "navigation_available": True,
        })
        return "MOVE", stay, base_row

    if place.get("origin_kind") == "pickup_center" and driver_mode == "active_working" and stay_samples == 0:
        registry = load_zones()
        live_anchors = tonight.load_anchors()
        pc = next(
            (c for c in registry.pickup_centers if c.id == place.get("place_id") or c.zone == place["zone"]),
            None,
        )
        now_hr = (current or datetime.now().astimezone()).astimezone().hour
        if pc is not None and pc.active_start_hour <= now_hr <= pc.active_end_hour:
            is_curb_approved = _is_center_approved(pc, live_anchors)
            positioned_stay = dict(stay or best or {})
            positioned_stay.update({
                "zone": place["zone"],
                "score": 0.0,
                "reposition_minutes": 0.0,
                "reposition_miles": 0.0,
                "recommendation_basis": "positioned_pickup_center",
                "destination_id": pc.id,
                "destination_label": pc.label,
                "staging_approved": is_curb_approved,
                "navigation_available": is_curb_approved,
                "suitability_reason": (
                    f"Positioned at {pc.label} pickup center (open {pc.active_start_hour}:00–{pc.active_end_hour}:00); "
                    "hold a bounded 15-minute wait while current rider demand is unverified."
                ),
            })
            return "WAIT", positioned_stay, positioned_stay

    if not is_residential:
        cal_candidate = next(
            (
                row
                for row in now_rows
                if row["zone"] != place["zone"]
                and is_calibrated_historical_move(
                    stay,
                    row,
                    stay_samples=stay_samples,
                    max_reposition_minutes=max_reposition_minutes,
                    drive_minutes=float(row.get("reposition_minutes") or 0.0),
                    min_score_advantage=12.0,
                )
            ),
            None,
        )
        if cal_candidate is not None:
            registry = load_zones()
            live_anchors = tonight.load_anchors()
            pc = next((c for c in registry.pickup_centers if c.zone == cal_candidate["zone"]), None)
            is_curb_approved = _is_center_approved(pc, live_anchors) if pc is not None else False
            dest_z = registry.by_id.get(cal_candidate["zone"])
            hist_best = dict(cal_candidate)
            hist_best.update({
                "recommendation_basis": "historical_and_positioning",
                "destination_id": pc.id if pc is not None else cal_candidate["zone"],
                "destination_label": pc.label if pc is not None else (dest_z.label if dest_z else cal_candidate["zone"].replace("_", " ")),
                "staging_approved": is_curb_approved,
                "navigation_available": is_curb_approved,
            })
            return "MOVE", stay, hist_best

    if not is_residential:
        if stay and stay_samples > 0 and (
            best["zone"] == place["zone"]
            or stay["score"] >= best["score"] - 2
            or not bool(stay.get("thin", True))
            or place.get("zone") not in STREET_ZONES
        ):
            return "WAIT", stay, best
        if stay_samples == 0 and not tonight.mock_feeds_active():
            try:
                from farol.awareness import saved_besttime
                from farol.besttime_live import _is_reading_fresh, _typical_for_hour

                bt_rep = saved_besttime(current) or {}
                now_dt = current or datetime.now().astimezone()
                for v_item in bt_rep.get("venues") or []:
                    req = v_item.get("requested") or {}
                    if req.get("zone") != place["zone"]:
                        continue
                    fc = v_item.get("forecast") or {}
                    lv = v_item.get("live") or {}
                    lv_ok = (
                        bool(lv.get("available"))
                        and isinstance(lv.get("busyness"), (int, float))
                        and _is_reading_fresh(lv.get("retrieved_at"), now_dt, 90 * 60)
                    )
                    pct_v = lv.get("busyness") if lv_ok else _typical_for_hour(fc, now_dt)
                    if isinstance(pct_v, (int, float)) and pct_v >= 35:
                        return "WAIT", stay, best
            except Exception:
                pass

    if is_residential and driver_mode == "active_working":
        if stay and stay_samples >= 2 and stay_score >= 20.0 and (best["zone"] == place["zone"] or stay_score >= float(best.get("score") or 0.0) - 2.0):
            return "WAIT", stay, stay
        cand, _rejected = _evaluate_positioning_candidates(
            place,
            now_rows,
            current,
            max_reposition_minutes=min(max_reposition_minutes, 15.0),
            vehicle_cost_per_mile=vehicle_cost_per_mile,
            origin_trip_samples=origin_trip_samples,
        )
        if cand is not None:
            base_row = dict(row_by_zone.get(cand["zone"]) or stay or best or {})
            base_row.update({
                "zone": cand["zone"],
                "score": cand["score"],
                "reposition_minutes": cand["reposition_minutes"],
                "reposition_miles": cand["reposition_miles"],
                "route_basis": "estimated_positioning",
                "recommendation_basis": cand["recommendation_basis"],
                "destination_id": cand["id"],
                "destination_label": cand["name"],
                "staging_approved": cand["staging_approved"],
                "navigation_available": cand["navigation_available"],
                "suitability_reason": cand["suitability_reason"],
            })
            return "MOVE", stay, base_row

    return "WATCH", stay, best


def _drive_plain(minutes: object, *, already_there: bool, basis: str | None = None) -> str:
    if basis == "assumed" and isinstance(minutes, (int, float)):
        return f"Estimated {round(minutes)} min drive from this pin; current traffic unknown."
    if already_there and minutes == 0:
        return "You're already there — no drive."
    if isinstance(minutes, (int, float)):
        return f"About {round(minutes)} min drive from this pin."
    return "Drive time unknown."


def _score_plain(score: float, *, airport: bool) -> str:
    if airport:
        if score >= 8:
            strength = "strong"
        elif score >= 5:
            strength = "moderate"
        elif score >= 0:
            strength = "light"
        else:
            strength = "low"
        return f"Activity level: {strength} for this airport feed."
    if score < 0:
        return "Low-value window — skip."
    if score >= 8:
        return "High-activity window if you are nearby."
    if score >= 5:
        return "Worth checking if you are already close."
    return "Lighter activity — does not justify an empty drive."


def _flight_examples(flights: list, count: int) -> str:
    if not flights:
        return ""
    bits = []
    for row in flights[:4]:
        ident = str(row.get("ident") or "?")
        origin = str(row.get("origin") or "?")
        bits.append(f"{ident} from {origin}")
    extra = count - min(count, 4)
    line = "Examples: " + ", ".join(bits)
    if extra > 0:
        line += f" (and {extra} more — not a full airport schedule)."
    else:
        line += "."
    return line


def _human_nearby(place: dict, item: dict) -> dict:
    airport = place["zone"] == "sea_airport"
    zone = item["zone"]
    facts = item.get("facts") or []
    primary = facts[0] if facts else {}
    title = primary.get("text") or zone.replace("_", " ")
    basis = primary.get("basis") or "assumed"
    route = item.get("route") or {}
    minutes = route.get("traffic_minutes")
    dist_miles = route.get("distance_miles")
    same_zone = zone == place["zone"]
    already_here = (
        same_zone
        and place.get("origin_kind") != "residential_home"
        and (minutes is None or float(minutes) <= ARRIVAL_RADIUS_MINUTES)
        and (dist_miles is None or float(dist_miles) <= ARRIVAL_RADIUS_MILES)
    )
    drive = _drive_plain(minutes, already_there=already_here, basis=route.get("basis"))
    when = ""
    start = format_clock(item.get("starts_at"))
    end = format_clock(item.get("ends_at"))
    if start and end:
        when = f"{start}–{end}"
    count = primary.get("count")
    flights = primary.get("flights") or []
    if airport or primary.get("kind") == "airport_arrivals":
        n = int(count or 0)
        headline = title if n else "No live inbound wave on this check."
        if n and when and "landing" not in headline.lower():
            headline = f"{n} planes landing about {when}"
        examples = _flight_examples(flights, n)
        score_line = _score_plain(float(item.get("score") or 0), airport=True)
        per_hour = primary.get("per_hour")
        page_full = primary.get("page_full")
        pace = ""
        if isinstance(per_hour, (int, float)):
            if per_hour >= 20:
                pace = f"That's a stacked inbound (~{per_hour:.0f}/hour)."
            elif per_hour >= 14:
                pace = f"That's a busy inbound (~{per_hour:.0f}/hour)."
            elif per_hour >= 9:
                pace = f"That's a typical SEA pace (~{per_hour:.0f}/hour), not a dump."
            else:
                pace = f"That's a light inbound (~{per_hour:.0f}/hour)."
        cap = ""
        if page_full:
            cap = (
                "This on-demand pull is two pages (up to 30 planes in the next 90 min) "
                "and that snapshot is still full."
            )
        detail = " ".join(
            part for part in (
                pace,
                cap,
                examples,
                drive,
                score_line,
                "Farol cannot see how many Uber cars are already in line.",
            ) if part
        )
        plain = f"{headline}. {detail}".strip()
        action_plain = "Airport queue — watch; Farol has no stall pin yet"
    else:
        headline = title
        score_line = _score_plain(float(item.get("score") or 0), airport=False)
        when_line = f"Window {when}." if when else ""
        detail = " ".join(part for part in (when_line, drive, score_line) if part)
        plain = f"{headline}. {detail}".strip()
        raw_act = item.get("action") or ""
        action_plain = "Watch this area" if raw_act == "WATCH" else ACTION_PLAIN.get(raw_act, raw_act or "Watch")
    anchor = item.get("anchor") or {}
    maps_url = str(anchor.get("maps_url") or "")
    if not maps_url:
        z_obj = load_zones().by_id.get(zone)
        if z_obj:
            maps_url = f"https://www.google.com/maps/dir/?api=1&destination={z_obj.latitude},{z_obj.longitude}"
    raw_source = str(primary.get("source") or item.get("source") or "")
    is_live_source = (
        basis == "live"
        and not raw_source.startswith(("farol:", "fixtures/", "synthetic:"))
    )
    source_type = "live" if is_live_source else ("scheduled" if basis == "scheduled" else "estimated")
    freshness_label = (
        "Live feed"
        if source_type == "live"
        else ("Scheduled window" if source_type == "scheduled" else "Estimated / unverified")
    )
    return {
        "id": item["id"],
        "zone": zone,
        "zone_label": zone.replace("_", " "),
        "is_same_zone": same_zone,
        "is_already_here": already_here,
        "action": item["action"],
        "action_plain": action_plain,
        "score": item["score"],
        "starts_at": item["starts_at"],
        "ends_at": item["ends_at"],
        "window_label": when,
        "minutes_away": minutes,
        "miles_away": dist_miles,
        "route_basis": route.get("basis"),
        "title": title,
        "headline": headline,
        "detail": detail,
        "plain": plain,
        "basis": basis,
        "source_type": source_type,
        "freshness_label": freshness_label,
        "count": count,
        "maps_url": maps_url,
    }


def _is_routine_transit_inventory(item: dict) -> bool:
    facts = item.get("facts") or []
    if not facts:
        return False
    for f in facts:
        kind = str(f.get("kind") or "")
        src = str(f.get("source") or "")
        txt = str(f.get("text") or "").lower()
        if kind == "transit_disruption":
            continue
        if kind in {"transit_arrival_wave", "ferry_arrival"} or src.startswith(("onebusaway", "wsf", "amtrak", "wsdot:Ferries")):
            return True
        if (
            "trains arriving" in txt
            or "link light rail arriving" in txt
            or "ferry arriving" in txt
            or "ferry arrival" in txt
            or "station arrival" in txt
        ):
            return True
    return False


def nearby_from_window(place: dict, opportunities: list[dict]) -> list[dict]:
    """Live calendar in reach. SEA FIFO stays off the street board and vice versa."""
    airport = place["zone"] == "sea_airport"
    rows = []
    for item in sorted(opportunities, key=lambda row: row["score"], reverse=True):
        zone = item["zone"]
        if airport and zone != "sea_airport":
            continue
        if not airport and zone == "sea_airport":
            continue
        if not airport and _is_routine_transit_inventory(item):
            continue
        rows.append(_human_nearby(place, item))
    return rows[:6]


def _spoken(place: dict, action: str, stay: dict | None, best: dict | None, board: dict, nearby: list[dict]) -> str:
    where = place["label"]
    if place["zone"] == "sea_airport":
        bits = [
            "You're looking at Sea-Tac.",
            "This is the airport pickup queue (FIFO), not Eastside last-call. Don't mix the two.",
        ]
        if nearby:
            bits.append(nearby[0]["plain"])
        else:
            bits.append(
                "No qualifying inbound wave is available in this check. "
                "Missing feed data does not mean the airport is quiet."
            )
            bits.append("Farol cannot see how many Uber cars are already in line.")
        return " ".join(bits)
    bits = [f"You're in {where}."]
    if place["note"] and place["note"] not in where:
        bits.append(place["note"] + ".")
    if action == "MOVE" and best:
        dest_label = str(best.get("destination_label") or best["zone"].replace("_", " "))
        mins = float(best.get("reposition_minutes") or 0.0)
        miles = float(best.get("reposition_miles") or 0.0)
        basis = str(best.get("recommendation_basis") or "")
        if basis == "positioning_heuristic":
            bits.append(
                f"Position near {dest_label} (about {mins:.0f} min / {miles:.1f} mi). "
                "You're starting from a residential area; this is a nearby pickup center to try while current rider demand is unverified."
            )
        elif basis == "live_opportunity":
            bits.append(
                f"MOVE to {dest_label} (about {mins:.0f} min / {miles:.1f} mi). "
                "Active pickup window clears travel cost."
            )
        else:
            bits.append(
                f"MOVE to {dest_label} (about {mins:.0f} min / {miles:.1f} mi). "
                "Paid-trip archive and staging checks support repositioning."
            )
    elif action == "WAIT" and stay:
        if stay.get("recommendation_basis") == "positioned_pickup_center":
            dest_label = str(stay.get("destination_label") or where)
            bits.append(
                f"WAIT at {dest_label} for a bounded 15-minute check. "
                "You are positioned at an active pickup center; current rider demand and local trip history are unverified."
            )
        else:
            grain_label = {
                "weekday_hour_zone": "this weekday and hour",
                "hour_zone": "this hour across weekdays",
                "zone": "this zone across hours and days",
                "none": "this zone",
            }.get(stay["grain"], "this zone")
            bits.append(
                f"WAIT here this hour. Your receipts for {grain_label} average "
                f"${stay['historical_mean_earnings']:.2f} per pickup "
                f"({stay['sample_trips']} trips, {stay['grain']}"
                f"{', thin sample' if stay['thin'] else ''})."
            )
    elif best and stay and best["zone"] != place["zone"]:
        bits.append(
            f"No clear recommendation to move yet. Watch {best['zone'].replace('_', ' ')} — about {best['reposition_minutes']:.0f} min / "
            f"{best['reposition_miles']:.1f} mi. Navigation stays off until you approve a curb. "
            f"Staying scores {stay['score']:.1f}; heading there scores {best['score']:.1f} after drive time."
        )
    elif best:
        bits.append(
            f"No clear recommendation to move yet. Best street board this hour is {best['zone'].replace('_', ' ')} "
            f"(score {best['score']:.1f})."
        )
    else:
        bits.append("No clear recommendation to move yet.")
    bits.append("Do not chase Uber purple. Empty miles are the KPI.")
    if nearby:
        top = nearby[0]
        if top.get("zone") and top.get("zone") != place["zone"]:
            bits.append(
                f"Activity listed in {top.get('zone_label', top.get('zone'))} does not establish pickup demand here in {where}: "
                f"{top.get('plain') or top.get('title')}."
            )
        else:
            bits.append(top.get("plain") or f"Right now: {top.get('title')}.")
    ranked = board.get("ranked") or []
    if ranked:
        line = "; ".join(
            f"{row['zone'].replace('_', ' ')} {row['hour']:02d}:00 score {row['score']:.1f}"
            for row in ranked[:3]
        )
        bits.append("Next hours: " + line + ".")
    return " ".join(bits)


def advise(
    at: str,
    *,
    now: datetime | None = None,
    value_of_time_per_hour: float = 25.0,
    vehicle_cost_per_mile: float = 0.45,
    trips: list[dict] | None = None,
    scored_window: dict | None = None,
    driver_mode: str = "active_working",
    max_reposition_minutes: float = 20.0,
) -> dict:
    place = resolve(at)
    current = now or datetime.now().astimezone()
    observed = trips if trips is not None else load_observed_trips()
    scored = scored_window if scored_window is not None else score_window(
        current=current,
        hours=3,
        vehicle_cost_per_mile=vehicle_cost_per_mile,
        origin_zone=place["zone"],
        origin_lat=place["latitude"],
        origin_lon=place["longitude"],
        include_llm=False,
        include_on_demand=place["zone"] == "sea_airport",
    )
    live_routes: dict[str, tuple[float, float]] = {}
    for item in scored.get("opportunities", []):
        route = item.get("route") or {}
        zone = item.get("zone")
        miles = route.get("distance_miles")
        minutes = route.get("traffic_minutes")
        if (
            zone
            and route.get("basis") == "live"
            and isinstance(miles, (int, float))
            and isinstance(minutes, (int, float))
        ):
            prev = live_routes.get(zone)
            if prev is None or minutes < prev[1]:
                live_routes[zone] = (float(miles), float(minutes))
    if scored_window is None and not tonight.mock_feeds_active():
        try:
            from farol.changes import latest_routes

            cached_routes, _ = latest_routes(place["zone"], vehicle_cost_per_mile)
            if cached_routes:
                anchor_zone_by_id = {
                    str(a.id): canonical_zone(a.zone) for a in tonight.load_anchors()
                }
                for anc_id, est in cached_routes.items():
                    z_id = anchor_zone_by_id.get(str(anc_id))
                    if z_id and est.basis == "live":
                        prev = live_routes.get(z_id)
                        if prev is None or est.traffic_minutes < prev[1]:
                            live_routes[z_id] = (float(est.distance_miles), float(est.traffic_minutes))
        except Exception:
            pass
    now_board = sit_here(
        now=current,
        origin_zone=place["zone"],
        hours=1,
        value_of_time_per_hour=value_of_time_per_hour,
        vehicle_cost_per_mile=vehicle_cost_per_mile,
        trips=observed,
        live_routes=live_routes or None,
    )
    later = sit_here(
        now=current,
        origin_zone=place["zone"],
        hours=3,
        value_of_time_per_hour=value_of_time_per_hour,
        vehicle_cost_per_mile=vehicle_cost_per_mile,
        trips=observed,
        live_routes=live_routes or None,
    )
    if place["zone"] != "sea_airport" and any(
        row["zone"] == place["zone"] and not row["thin"] for row in now_board["ranked"]
    ):
        place["street_board"] = True
    origin_trip_samples = sum(
        1
        for t in observed
        if isinstance(t, dict)
        and str(t.get("origin_place_id") or t.get("pickup_place_id") or "") == str(place.get("place_id") or "")
    )
    now_rows_for_pick = [
        r for r in (now_board.get("all_rows") or now_board["ranked"]) if r.get("hour") == current.hour
    ] or now_board["ranked"]
    seen_ranked = {(r.get("zone"), r.get("hour")) for r in later["ranked"]}
    for r in now_rows_for_pick:
        if (r.get("zone"), r.get("hour")) not in seen_ranked and float(r.get("score") or 0.0) > 0.0:
            later["ranked"].append(r)
            seen_ranked.add((r.get("zone"), r.get("hour")))
    action, stay, best = _pick_action(
        place,
        now_rows_for_pick,
        scored.get("opportunities", []),
        current=current,
        driver_mode=driver_mode,
        max_reposition_minutes=max_reposition_minutes,
        vehicle_cost_per_mile=vehicle_cost_per_mile,
        origin_trip_samples=origin_trip_samples,
    )
    nearby = nearby_from_window(place, scored["opportunities"])
    from farol.adapters.onebusaway import nearby_train_stations

    nearby_stations = nearby_train_stations(
        place["latitude"],
        place["longitude"],
        radius_miles=5.0,
        now=current,
    )
    spoken = _spoken(place, action, stay, best, later, nearby)
    warnings = [
        "Parked pin is reduced to a named zone for ranking. Google Routes uses that pin for traffic minutes. Coordinates are not sent to Grok.",
        "Receipts rank sit-here; live calendars and traffic price the drive. Not Uber demand.",
        "MOVE/WAIT pins stay demo_only until you approve a legal curb.",
    ]
    for item in scored.get("opportunities", []):
        for fact in item.get("facts") or []:
            text = str(fact.get("text") or "")
            if "CROSS-LAKE BRIDGE CLOSURE" in text or "bridge closed" in text.lower():
                warnings.append(f"CROSS-LAKE BRIDGE ALERT: {text}")
                break
    recheck_minutes = 15 if action == "WAIT" else 10
    recheck_at = (current + timedelta(minutes=recheck_minutes)).isoformat()
    best_zone = str((best or {}).get("zone") or place["zone"])
    best_miles = float((best or {}).get("reposition_miles") or 0.0)
    road_cost = _road_cost_summary(
        place["zone"], best_zone, best_miles, vehicle_cost_per_mile, current
    )
    is_residential = place.get("origin_kind") == "residential_home"
    stay_samples = origin_trip_samples if is_residential else int((stay or {}).get("sample_trips") or 0)
    best_samples = int((best or {}).get("sample_trips") or 0)
    rec_basis = str(
        (best or {}).get("recommendation_basis")
        or (stay or {}).get("recommendation_basis")
        or ("paid_trip_archive" if stay_samples > 0 else "uncalibrated")
    )
    advantage_known = (
        (stay_samples >= 2 and best_samples >= 2 and rec_basis not in {"positioning_heuristic", "positioned_pickup_center"})
        or rec_basis in {"live_opportunity", "historical_and_positioning"}
    )
    stay_evidence = (
        f"Paid-trip archive: ${float((stay or {}).get('historical_mean_earnings') or 0.0):.2f}/pickup across {stay_samples} trip(s) ({(stay or {}).get('grain', 'none')})"
        if stay_samples > 0
        else (
            "Positioned at active pickup center; local paid-trip history and live Uber demand are unverified — hold a bounded 15-minute wait before rechecking."
            if rec_basis == "positioned_pickup_center"
            else (
                "Residential home origin (0 origin-verified driveway pickups; broad zone trips do not establish driveway waiting)."
                if is_residential
                else "Earnings unknown (0 historical trips in this zone)"
            )
        )
    )
    if (stay or {}).get("outcome_note"):
        stay_evidence += f" · {(stay or {}).get('outcome_note')}"
    next_obs = (
        nearby[0]["plain"]
        if nearby
        else f"Recheck live feeds and wait exposure at {format_clock(recheck_at) or recheck_at}"
    )
    rec_id = f"here-{place['zone']}-{int(current.timestamp())}"
    local_live_ev = any(
        bool(w.get("is_already_here")) and w.get("source_type") == "live" and float(w.get("score") or 0.0) > 0.0
        for w in nearby
    )
    local_sched_ev = any(
        bool(w.get("is_already_here")) and w.get("source_type") != "live" and float(w.get("score") or 0.0) > 0.0
        for w in nearby
    )
    decision_state = (
        "AIRPORT_LOT"
        if place["zone"] == "sea_airport"
        else "MOVE"
        if action == "MOVE"
        else "STAY"
        if (action == "WAIT" and (stay_samples > 0 or local_live_ev or local_sched_ev or rec_basis == "positioned_pickup_center"))
        else "WATCH"
    )
    dest_id = str((best or {}).get("destination_id") or (place.get("place_id", place["zone"]) if action != "MOVE" else best_zone))
    dest_label = str((best or {}).get("destination_label") or (place["label"] if action != "MOVE" else best_zone.replace("_", " ")))
    suitability_reason = str((best or {}).get("suitability_reason") or (stay or {}).get("suitability_reason") or "")
    staging_approved = bool((best or {}).get("staging_approved", False))
    navigation_available = bool((best or {}).get("navigation_available", staging_approved))
    if place["zone"] != "sea_airport":
        try:
            reg_here = load_zones()
            anc_here = tonight.load_anchors()
            target_z = best_zone if action == "MOVE" else place["zone"]
            pc_here = next((c for c in reg_here.pickup_centers if c.id == dest_id or c.zone == target_z), None)
            anc_match = next(
                (a for a in anc_here if (a.id == dest_id or a.zone == target_z) and a.approval_status == "approved"),
                None,
            )
            if pc_here is not None and _is_center_approved(pc_here, anc_here):
                staging_approved = True
                navigation_available = True
                if dest_id == target_z:
                    dest_id = pc_here.id
                nav_lat, nav_lon = pc_here.latitude, pc_here.longitude
            elif anc_match is not None:
                staging_approved = True
                navigation_available = True
                if dest_id == target_z:
                    dest_id = anc_match.id
                nav_lat, nav_lon = anc_match.latitude, anc_match.longitude
            elif navigation_available and pc_here is not None:
                nav_lat, nav_lon = pc_here.latitude, pc_here.longitude
            else:
                nav_lat, nav_lon = None, None
            if best is not None and navigation_available and nav_lat is not None and nav_lon is not None:
                best = dict(best)
                best["staging_approved"] = True
                best["navigation_available"] = True
                best["destination_id"] = dest_id
                if not best.get("maps_url"):
                    best["maps_url"] = (
                        f"https://www.google.com/maps/dir/?api=1&travelmode=driving&destination={nav_lat:.6f},{nav_lon:.6f}"
                    )
        except Exception:
            pass
    decision_kind = (
        "airport_queue"
        if place["zone"] == "sea_airport"
        else "move_for_opportunity"
        if action == "MOVE" and rec_basis == "live_opportunity"
        else "move_for_positioning"
        if action == "MOVE" and rec_basis == "positioning_heuristic"
        else "move_for_calibrated_history"
        if action == "MOVE"
        else "stay_bounded_wait"
        if action == "WAIT" and rec_basis == "positioned_pickup_center"
        else "stay_verified"
        if action == "WAIT"
        else "insufficient_evidence"
    )
    if rec_basis in {"positioning_heuristic", "positioned_pickup_center"} and suitability_reason:
        adv_note = suitability_reason
    elif rec_basis == "historical_and_positioning" and best_samples > 0:
        best_mean = float((best or {}).get("historical_mean_earnings") or 0.0)
        best_net_hr = float((best or {}).get("historical_net_per_hour") or 0.0)
        best_mins = float((best or {}).get("reposition_minutes") or 0.0)
        stay_cmp = (
            f"stay {float((stay or {}).get('score') or 0.0):.1f} ({stay_samples} trips)"
            if stay_samples >= 2 and not bool((stay or {}).get("thin", True))
            else f"thin local sample ({stay_samples} trip in {place['label']})"
            if stay_samples > 0
            else f"0 local trips in {place['label']}"
        )
        adv_note = (
            f"Paid-trip archive in {dest_label}: ${best_mean:.2f}/pickup (~${best_net_hr:.0f}/paid-hr across {best_samples} trips, "
            f"score {float((best or {}).get('score') or 0.0):.1f} after {best_mins:.0f}m drive vs {stay_cmp})"
        )
    elif advantage_known:
        adv_note = f"Alternative score {(best or {}).get('score', 0.0):.1f} vs stay {(stay or {}).get('score', 0.0):.1f} (paid-trip/window basis)"
    else:
        adv_note = "Alternative advantage is uncalibrated (sparse or missing wait/trip history); avoid deadheading on unknown odds."

    bt_live_zones_here: set[str] = set()
    bt_typical_zones_here: set[str] = set()
    chosen_target_zone = best_zone if action == "MOVE" else place["zone"]
    bt_note_items: list[str] = []
    if not tonight.mock_feeds_active():
        try:
            from farol.awareness import saved_besttime
            from farol.besttime_live import _is_reading_fresh, _typical_for_hour

            bt_rep = saved_besttime(current) or {}
            for v_item in bt_rep.get("venues") or []:
                req = v_item.get("requested") or {}
                vz = str(req.get("zone") or "")
                fc = v_item.get("forecast") or {}
                lv = v_item.get("live") or {}
                lv_ok = (
                    bool(lv.get("available"))
                    and isinstance(lv.get("busyness"), (int, float))
                    and _is_reading_fresh(lv.get("retrieved_at"), current, 90 * 60)
                )
                typ_val = _typical_for_hour(fc, current)
                if lv_ok:
                    bt_live_zones_here.add(vz)
                    pct_v = int(lv["busyness"])
                    tag_v = f"{req.get('name')} (live {pct_v}%)"
                elif isinstance(typ_val, (int, float)) and typ_val >= 40:
                    bt_typical_zones_here.add(vz)
                    pct_v = int(typ_val)
                    tag_v = f"{req.get('name')} (typical {pct_v}%)"
                else:
                    continue
                if vz == chosen_target_zone and pct_v >= 45:
                    bt_note_items.append((pct_v, tag_v))
            bt_note_items.sort(key=lambda item: item[0], reverse=True)
        except Exception:
            bt_note_items = []
    bt_suffix = (
        " · Venue activity: " + ", ".join(lbl for _, lbl in bt_note_items[:2])
        if bt_note_items
        else ""
    )
    if action == "WAIT" and bt_note_items and place["zone"] != "sea_airport":
        decision_state = "STAY"
        if stay_samples == 0 and rec_basis == "uncalibrated":
            rec_basis = "scheduled_catalyst"
            stay_evidence = "Venue activity: " + ", ".join(lbl for _, lbl in bt_note_items[:2])
            bt_suffix = ""

    if place["zone"] == "sea_airport":
        card_headline = "Sea-Tac Airport Queue"
        card_reason = "Confirm Uber SEA FIFO / ReMatch eligibility in Driver app; queue wait cannot be inferred from flight counts."
    elif action == "MOVE" and rec_basis == "positioning_heuristic":
        card_headline = f"Position near {dest_label}"
        card_reason = f"Positioning suggestion · live demand unknown — {suitability_reason or 'move from residential start to nearby active pickup center.'}{bt_suffix}"
    elif action == "MOVE":
        card_headline = f"Move to {dest_label}"
        card_reason = f"{adv_note}{bt_suffix}"
    elif action == "WAIT" and rec_basis == "positioned_pickup_center":
        card_headline = f"Wait at {dest_label}"
        card_reason = f"{suitability_reason or stay_evidence}{bt_suffix}"
    elif action == "WAIT":
        card_headline = f"Stay in {place['label']}"
        card_reason = f"{stay_evidence}{bt_suffix}"
    else:
        card_headline = f"Hold in {place['label']} · insufficient evidence"
        card_reason = f"{stay_evidence}. {adv_note}"

    alternatives_considered: list[dict] = []
    for row in (now_board.get("ranked") or [])[:5]:
        r_zone = str(row.get("zone") or "")
        r_samples = int(row.get("sample_trips") or 0)
        r_grain = str(row.get("grain") or "none")
        r_mins = float(row.get("reposition_minutes") or 0.0)
        if r_zone == place["zone"]:
            status_str = "selected_stay" if action != "MOVE" else "current_origin"
            reason_str = stay_evidence
        elif action == "MOVE" and r_zone == best_zone:
            status_str = "selected_move"
            reason_str = adv_note
        elif r_mins > max_reposition_minutes:
            status_str = "rejected"
            reason_str = f"exceeds_max_reposition_minutes ({r_mins:.1f} > {max_reposition_minutes:.1f})"
        elif bool(row.get("thin", True)) or r_grain == "none" or (r_samples < 5 and (r_samples < 3 or r_grain == "zone")):
            status_str = "rejected"
            reason_str = f"uncalibrated_or_thin_history (target {r_samples}t/{r_grain}, origin {stay_samples}t)"
        else:
            status_str = "rejected"
            reason_str = f"below_move_margin (score {float(row.get('score') or 0.0):.1f} vs stay {float((stay or {}).get('score') or 0.0):.1f})"
        alternatives_considered.append({
            "zone": r_zone,
            "status": status_str,
            "reposition_minutes": r_mins,
            "sample_trips": r_samples,
            "grain": r_grain,
            "reason": reason_str,
        })

    try:
        from farol.collect import build_source_coverage_inventory

        active_sources: set[str] = set()
        for opp in scored.get("opportunities", []) or []:
            for fact in opp.get("facts") or []:
                if fact.get("source"):
                    active_sources.add(str(fact["source"]))
        source_coverage = build_source_coverage_inventory(
            now=current,
            chosen_zone=best_zone if action == "MOVE" else place["zone"],
            chosen_action=action,
            chosen_basis=rec_basis,
            active_signal_sources=active_sources,
            bt_live_zones=bt_live_zones_here,
            bt_typical_zones=bt_typical_zones_here,
            live_route_zones=set(live_routes.keys()),
        )
    except Exception:
        source_coverage = []

    stay_or_move_card = {
        "recommendation_id": rec_id,
        "evidence_version": "v2",
        "action": action,
        "decision_state": decision_state,
        "decision_kind": decision_kind,
        "headline": card_headline,
        "reason": card_reason,
        "recommendation_basis": rec_basis,
        "origin_kind": place.get("origin_kind", "zone_centroid"),
        "origin_place_id": place.get("place_id", place["zone"]),
        "destination_id": dest_id,
        "destination_label": dest_label,
        "staging_approved": staging_approved,
        "navigation_available": navigation_available,
        "suitability_reason": suitability_reason,
        "local_live_evidence": local_live_ev,
        "local_scheduled_evidence": local_sched_ev,
        "stay_zone": place["zone"],
        "stay_evidence": stay_evidence,
        "alternative_zone": best_zone,
        "alternative_cost": road_cost,
        "advantage_known": advantage_known,
        "advantage_note": adv_note,
        "alternatives_considered": alternatives_considered,
        "next_observation": next_obs,
        "recheck_minutes": recheck_minutes,
        "recheck_at": recheck_at,
    }
    airport_decision = {
        "zone": "sea_airport",
        "eligibility_required": "Confirm Uber SEA FIFO / ReMatch eligibility in Driver app before heading to 160th St holding lot.",
        "queue_wait": "unknown (Uber lot queue length and wait time cannot be inferred from flight counts)",
        "inbound_flights": nearby[0].get("count") if (place["zone"] == "sea_airport" and nearby) else None,
        "travel_cost": _road_cost_summary(place["zone"], "sea_airport", None, vehicle_cost_per_mile, current),
    }
    return {
        "as_of": current.isoformat(),
        "recommendation_id": rec_id,
        "evidence_version": "v2",
        "recheck_minutes": recheck_minutes,
        "recheck_at": recheck_at,
        "road_cost": road_cost,
        "stay_or_move_card": stay_or_move_card,
        "source_coverage": source_coverage,
        "airport_decision": airport_decision,
        "query": at,
        "place": {
            "zone": place["zone"],
            "label": place["label"],
            "cluster": place["cluster"],
            "matched": place["matched"],
            "note": place["note"],
            "street_board": place["street_board"],
            "origin_kind": place.get("origin_kind", "zone_centroid"),
            "place_id": place.get("place_id", place["zone"]),
        },
        "action": action,
        "action_plain": (
            "Airport queue"
            if place["zone"] == "sea_airport"
            else (
                f"Position near {dest_label}"
                if action == "MOVE" and rec_basis == "positioning_heuristic"
                else ACTION_PLAIN.get(action, action)
            )
        ),
        "stay": stay,
        "best": best,
        "sit_here": later,
        "nearby": nearby,
        "nearby_stations": nearby_stations,
        "feeds": scored.get("feeds", []),
        "spoken": spoken,
        "card": (
            f"FAROL HERE CARD\n"
            f"as_of: {current.isoformat()}\n"
            f"place: {place['label']} ({place['zone']})\n"
            f"action: {action}\n"
            f"nav: off until a curb is driver-approved\n"
            f"doctrine: {later['doctrine']}\n"
            f"spoken: {spoken}\n"
        ),
        "warnings": warnings,
    }
