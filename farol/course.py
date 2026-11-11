"""All-Hands API Blast + 6-Hour AI Shift Course Planner for RideEdge.

Enforces the same conservative trust boundaries as the main engine:
- Earnings remain None (unknown) unless backed by observed historical trips in that zone/hour;
  measured 0.0 remains 0.0, and no heuristic-to-dollar fabrication is performed (R01).
- Staging navigation is gated on approved anchors (`load_anchors()`), distances start from the
  supplied origin pin, and events must be reachable before they end (R02).
- Only positive demand signal kinds are scored positively; `doctrine_penalty` reduces score,
  and `context_only` signals are excluded from scoring (R03).
- AI formatting routes through `local_runtime.session`, verifies the loaded Qwen model, and
  rejects ungrounded dollar claims or unapproved curbs (R04).
- Plan caching is keyed by `(origin_label, hour_bucket, evidence_signature, version)` and
  expires after 30 minutes (R05).
- Outbound HTTP counts reflect actual live transport calls made (R23).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from farol import local_runtime
from farol.adapters.base import FeedError, cache_dir
from farol.adapters.flightaware import seatac_6h_forecast
from farol.adapters.onebusaway import nearby_train_stations
from farol.besttime import save
from farol.besttime_live import _active_dir, _read_json, _typical_for_hour, poll_besttime_venues
from farol.collect import feed_health_view, refresh_once
from farol.local import local_url
from farol.signals import load_anchors
from farol.trips import load_observed_trips, sit_here
from farol.zones import canonical_zone, load_zones, zone_record

PACIFIC = ZoneInfo("America/Los_Angeles")

POSITIVE_SIGNAL_KINDS = frozenset({
    "event_exit",
    "special_event",
    "ferry_arrival",
    "cruise_turnaround",
    "transit_arrival",
    "convention",
    "dining_wave",
    "nightlife_wave",
    "shift_change",
    "surge",
})

PENALTY_SIGNAL_KINDS = frozenset({
    "doctrine_penalty",
    "highway_alert",
    "travel_delay",
})

ACTION_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {"type": "string", "enum": ["structured_selection"]},
        "immediate_stop_id": {"type": "string", "enum": ["stop_0"]},
        "pivot_stop_id": {"type": "string"},
        "late_stop_id": {"type": "string"},
    },
    "required": [
        "mode",
        "immediate_stop_id",
        "pivot_stop_id",
        "late_stop_id",
    ],
    "additionalProperties": False,
}


def build_action_plan_selection_schema(stops: list[dict]) -> dict:
    stop_ids = [f"stop_{i}" for i in range(len(stops))] or ["stop_0"]
    pivot_ids = stop_ids[1:] if len(stop_ids) > 1 else ["stop_0"]
    return {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["structured_selection"]},
            "immediate_stop_id": {"type": "string", "enum": ["stop_0"]},
            "pivot_stop_id": {"type": "string", "enum": pivot_ids},
            "late_stop_id": {"type": "string", "enum": stop_ids},
        },
        "required": [
            "mode",
            "immediate_stop_id",
            "pivot_stop_id",
            "late_stop_id",
        ],
        "additionalProperties": False,
    }


def _distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(min(1.0, a)))


def _parse_iso_aware(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(UTC)


def _is_fresh_iso(value: object, now: datetime, *, max_minutes: float) -> bool:
    dt = _parse_iso_aware(value)
    if dt is None:
        return False
    age_sec = (now.astimezone(UTC) - dt).total_seconds()
    return -300.0 <= age_sec <= (max_minutes * 60.0)


def _format_clock(dt: datetime) -> str:
    local = dt.astimezone(PACIFIC)
    h12 = local.hour % 12 or 12
    ampm = "AM" if local.hour < 12 else "PM"
    return f"{h12}:{local.minute:02d} {ampm}"


def _format_clock_with_sec(dt: datetime) -> str:
    local = dt.astimezone(PACIFIC)
    h12 = local.hour % 12 or 12
    ampm = "AM" if local.hour < 12 else "PM"
    return f"{h12}:{local.minute:02d}:{local.second:02d} {ampm}"


def _format_hour_window(start_dt: datetime, end_dt: datetime) -> str:
    return f"{_format_clock(start_dt)} – {_format_clock(end_dt)}"


def _fire_all_apis_parallel(origin_area: str, pull_all: bool = True) -> dict:
    """Fire BestTime Radar (Eastside + Seattle), FlightAware 6h pull, and push feeds concurrently."""
    started = time.perf_counter()
    now = datetime.now(UTC)
    snap_path = cache_dir() / "awareness_snapshot.json"
    snap = _read_json(snap_path) or {}

    snap_stale = True
    raw_collected = snap.get("collected_at")
    dt_collected = _parse_iso_aware(raw_collected)
    if dt_collected is not None:
        snap_stale = (now - dt_collected).total_seconds() > 600

    results: dict = {
        "besttime_eastside": None,
        "besttime_seattle": None,
        "flightaware_6h": None,
        "push_refreshed": False,
        "live_http_requests": 0,
        "cache_hits": 0,
        "failed_sources": [],
    }

    def _run_bt_eastside():
        try:
            return poll_besttime_venues(area="Bellevue", max_venues=4, force_live=pull_all)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "http_requests_made": 0}

    def _run_bt_seattle():
        try:
            return poll_besttime_venues(area="Seattle", max_venues=4, force_live=pull_all)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "http_requests_made": 0}

    def _run_flightaware():
        try:
            return seatac_6h_forecast(now, pull=pull_all)
        except Exception as exc:
            fallback = seatac_6h_forecast(now, pull=False)
            if isinstance(fallback, dict):
                fallback = {**fallback, "error": str(exc), "http_requests_made": 0}
            return fallback

    def _run_push():
        if pull_all and snap_stale:
            try:
                from farol import collect

                before_usage = collect.status().get("last_run_usage") or {}
                before_stamp = before_usage.get("completed_at")
                snap_res = refresh_once(include_flightaware=False)
                after_usage = collect.status().get("last_run_usage") or {}
                after_stamp = after_usage.get("completed_at")
                if after_stamp and after_stamp != before_stamp:
                    providers = after_usage.get("providers") or {}
                    attempts = sum(
                        int((v or {}).get("http_attempts") or 0)
                        for v in providers.values()
                        if isinstance(v, dict)
                    )
                    return {"refreshed": True, "http_requests_made": attempts}
                if isinstance(snap_res, dict):
                    if "http_requests_made" in snap_res:
                        return {"refreshed": True, "http_requests_made": int(snap_res.get("http_requests_made") or 0)}
                    feeds = snap_res.get("feeds") or []
                    live_cnt = sum(1 for f in feeds if isinstance(f, dict) and f.get("mode") == "live")
                    return {"refreshed": True, "http_requests_made": live_cnt}
                if isinstance(snap_res, list):
                    live_cnt = sum(
                        int(f.get("http_requests_made") or (1 if f.get("mode") == "live" else 0))
                        for f in snap_res
                        if isinstance(f, dict)
                    )
                    return {"refreshed": True, "http_requests_made": live_cnt}
                return {"refreshed": True, "http_requests_made": 0}
            except Exception as exc:
                return {"refreshed": False, "error": str(exc), "http_requests_made": 0}
        return {"refreshed": False, "http_requests_made": 0}

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_bt_e = pool.submit(_run_bt_eastside)
        f_bt_s = pool.submit(_run_bt_seattle)
        f_fa = pool.submit(_run_flightaware)
        f_push = pool.submit(_run_push)

        bt_e = f_bt_e.result()
        bt_s = f_bt_s.result()
        fa_res = f_fa.result()
        push_res = f_push.result()

        results["besttime_eastside"] = bt_e
        results["besttime_seattle"] = bt_s
        results["flightaware_6h"] = fa_res
        results["push_refreshed"] = bool(isinstance(push_res, dict) and push_res.get("refreshed"))

        live_reqs = 0
        for label, bt_obj in (("besttime_eastside", bt_e), ("besttime_seattle", bt_s)):
            if isinstance(bt_obj, dict):
                if bt_obj.get("ok") is False:
                    results["failed_sources"].append(label)
                if "http_requests_made" in bt_obj:
                    live_reqs += int(bt_obj.get("http_requests_made") or 0)
                else:
                    live_reqs += (
                        int(bt_obj.get("radar_requests") or 0)
                        + int(bt_obj.get("polled_live_requests") or 0)
                        + int(bt_obj.get("polled_weekly_requests") or 0)
                    )

        if isinstance(fa_res, dict):
            if fa_res.get("cached", True):
                results["cache_hits"] += 1
            elif "http_requests_made" in fa_res:
                live_reqs += int(fa_res.get("http_requests_made") or 0)
            elif fa_res.get("state") == "ready":
                live_reqs += len(fa_res.get("hours") or [])

        if isinstance(push_res, dict):
            live_reqs += int(push_res.get("http_requests_made") or 0)
            if push_res.get("error"):
                results["failed_sources"].append("push_collector")

        results["live_http_requests"] = live_reqs

    results["blast_elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    return results


def _match_airport_bucket(fa_hours: list[dict], hr_start: datetime, hr_end: datetime, step_idx: int) -> dict:
    """Match airport forecast bucket by absolute timestamp overlap; only fall back positionally if fresh & untimestamped."""
    start_utc = hr_start.astimezone(UTC)
    end_utc = hr_end.astimezone(UTC)
    for bucket in fa_hours:
        if not isinstance(bucket, dict):
            continue
        b_start = _parse_iso_aware(bucket.get("starts_at"))
        b_end = _parse_iso_aware(bucket.get("ends_at"))
        if b_start is not None and b_end is not None:
            if b_start < end_utc and b_end > start_utc:
                return bucket
    # If buckets have explicit timestamps and none matched, do not reuse positional index
    if any(isinstance(b, dict) and (b.get("starts_at") or b.get("ends_at")) for b in fa_hours):
        return {}
    return fa_hours[step_idx] if step_idx < len(fa_hours) and isinstance(fa_hours[step_idx], dict) else {}


def build_6h_shift_course(
    origin_area: str = "Bellevue",
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    pull_all: bool = True,
    vehicle_cost: float = 0.45,
    driver_mode: str = "active_working",
    minutes_available: int | None = None,
    reposition_under_minutes: int | None = None,
    finish_near: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Blast all APIs (including BestTime Radar + FlightAware) and chart a formatted shift course."""
    from farol import here as _here_mod

    current_utc = (now or datetime.now(UTC)).astimezone(UTC)
    local_now = current_utc.astimezone(PACIFIC)
    registry = load_zones()

    has_exact_pin = latitude is not None and longitude is not None
    place: dict
    if has_exact_pin:
        assert latitude is not None and longitude is not None
        try:
            place = _here_mod.resolve(f"{float(latitude):.6f}, {float(longitude):.6f}")
        except ValueError:
            origin_zone_tmp = min(
                registry.zones,
                key=lambda z: _distance_miles(latitude, longitude, z.latitude, z.longitude),
            )
            place = _here_mod._zone_payload(
                origin_zone_tmp.id,
                f"{latitude:.4f},{longitude:.4f}",
                origin_zone_tmp.label,
                latitude=float(latitude),
                longitude=float(longitude),
                origin_kind="gps_pin",
                place_id=f"pin_{origin_zone_tmp.id}",
            )
        if origin_area and origin_area.strip():
            try:
                named_place = _here_mod.resolve(origin_area)
                if named_place.get("origin_kind") in {"residential_home", "pickup_center"}:
                    dist_named = _distance_miles(
                        float(latitude),
                        float(longitude),
                        float(named_place["latitude"]),
                        float(named_place["longitude"]),
                    )
                    if dist_named <= 0.45:
                        place["origin_kind"] = named_place["origin_kind"]
                        place["place_id"] = named_place["place_id"]
            except ValueError:
                pass
        origin_zone = registry.by_id.get(place["zone"]) or registry.by_id["bellevue_core"]
        cur_lat, cur_lon = float(latitude), float(longitude)
    else:
        try:
            place = _here_mod.resolve(origin_area)
            origin_zone = registry.by_id.get(place["zone"]) or registry.by_id["bellevue_core"]
            cur_lat, cur_lon = float(place["latitude"]), float(place["longitude"])
            if (
                place.get("origin_kind") in {"residential_home", "pickup_center", "neighborhood"}
                and (abs(cur_lat - origin_zone.latitude) > 0.002 or abs(cur_lon - origin_zone.longitude) > 0.002)
            ):
                has_exact_pin = True
        except ValueError:
            zid = canonical_zone(origin_area)
            origin_zone = registry.by_id.get(zid) or registry.by_id["bellevue_core"]
            cur_lat, cur_lon = origin_zone.latitude, origin_zone.longitude
            place = _here_mod._zone_payload(
                origin_zone.id,
                origin_area,
                origin_zone.label,
                origin_kind="zone_centroid",
                place_id=origin_zone.id,
            )

    eff_minutes_available = (
        max(30, min(720, int(minutes_available)))
        if minutes_available is not None and int(minutes_available) > 0
        else 360
    )
    eff_reposition_under = (
        max(5, min(180, int(reposition_under_minutes)))
        if reposition_under_minutes is not None and int(reposition_under_minutes) > 0
        else 20
    )
    finish_zone = zone_record(finish_near) if (finish_near and finish_near.strip()) else None

    if pull_all:
        blast = _fire_all_apis_parallel(origin_zone.id, pull_all=True)
    else:
        blast = {"blast_elapsed_ms": 0, "live_http_requests": 0, "cache_hits": 0, "failed_sources": []}

    raw_fa = blast.get("flightaware_6h") or seatac_6h_forecast(current_utc, pull=False)
    fa_fresh = (
        isinstance(raw_fa, dict)
        and raw_fa.get("state") == "ready"
        and (
            not raw_fa.get("fetched_at")
            or _is_fresh_iso(raw_fa.get("fetched_at"), current_utc, max_minutes=60.0)
        )
    )
    fa_forecast = raw_fa if fa_fresh else {"state": "stale", "hours": [], "best_hour_label": "", "best_lot_arrival_time": ""}

    bt_report = _read_json(_active_dir() / "report.json") or {}
    bt_venues = bt_report.get("venues") or []
    snap = _read_json(cache_dir() / "awareness_snapshot.json") or {}
    raw_signals = snap.get("signals") or []
    health_view = feed_health_view(current_utc) or {}

    try:
        anchors = load_anchors()
    except Exception:
        anchors = []
    approved_anchors_by_zone: dict[str, object] = {}
    for anc in anchors:
        if getattr(anc, "approval_status", "") == "approved" and getattr(anc, "zone", "") not in approved_anchors_by_zone:
            approved_anchors_by_zone[anc.zone] = anc

    # Load driver's historical earnings archive for descriptive baseline $/hr
    trips = load_observed_trips()
    origin_trip_samples = sum(
        1
        for t in trips
        if isinstance(t, dict)
        and str(t.get("origin_place_id") or t.get("pickup_place_id") or "") == str(place.get("place_id") or "")
    )
    is_residential_origin = place.get("origin_kind") == "residential_home"
    live_routes_step0: dict[str, tuple[float, float]] = {}
    if not _here_mod.tonight.mock_feeds_active():
        try:
            from farol.changes import latest_routes

            cached_routes, _ = latest_routes(origin_zone.id, vehicle_cost)
            if cached_routes:
                anchor_zone_by_id = {
                    str(a.id): canonical_zone(a.zone) for a in anchors
                }
                for anc_id, est in cached_routes.items():
                    z_id = anchor_zone_by_id.get(str(anc_id))
                    if z_id and est.basis == "live":
                        prev_rt = live_routes_step0.get(z_id)
                        if prev_rt is None or est.traffic_minutes < prev_rt[1]:
                            live_routes_step0[z_id] = (float(est.distance_miles), float(est.traffic_minutes))
        except Exception:
            live_routes_step0 = {}
    sit_board = sit_here(
        now=local_now,
        origin_zone=origin_zone.id,
        hours=6,
        value_of_time_per_hour=25.0,
        vehicle_cost_per_mile=vehicle_cost,
        trips=trips,
        live_routes=live_routes_step0 or None,
    )
    now_sit_rows: list[dict] = []
    if not sit_board.get("all_rows"):
        try:
            sit_now_1h = sit_here(
                now=local_now,
                origin_zone=origin_zone.id,
                hours=1,
                value_of_time_per_hour=25.0,
                vehicle_cost_per_mile=vehicle_cost,
                trips=trips,
                live_routes=live_routes_step0 or None,
            )
            now_sit_rows = list(sit_now_1h.get("ranked") or [])
        except Exception:
            now_sit_rows = []
    hist_by_zone_hour: dict[tuple[str, int], dict] = {}
    all_hist_rows = (sit_board.get("all_rows") or []) + (sit_board.get("ranked") or []) + now_sit_rows
    for row in all_hist_rows:
        if not isinstance(row, dict):
            continue
        z_id = str(row.get("zone") or "")
        h_val = int(row.get("hour") or 0)
        sample_cnt = int(row.get("sample_trips") or 0)
        if sample_cnt <= 0:
            continue
        existing = hist_by_zone_hour.get((z_id, h_val))
        if existing is None or float(row.get("historical_net_per_hour") or 0.0) > float(existing.get("historical_net_per_hour") or 0.0):
            hist_by_zone_hour[(z_id, h_val)] = row

    try:
        from farol.history import summarize_zone_outcomes

        outcome_by_zone = summarize_zone_outcomes(now=current_utc)
    except Exception:
        outcome_by_zone = {}

    train_stations = nearby_train_stations(cur_lat, cur_lon, radius_miles=5.0, now=current_utc)

    base_hour_utc = current_utc.replace(minute=0, second=0, microsecond=0)
    if (base_hour_utc + timedelta(hours=1) - current_utc) < timedelta(minutes=15):
        base_hour_utc = base_hour_utc + timedelta(hours=1)
    horizon_end_utc = current_utc + timedelta(minutes=eff_minutes_available)
    horizon_end = horizon_end_utc.astimezone(PACIFIC)
    max_slots = max(6, int(math.ceil(eff_minutes_available / 60.0)) + 2)
    fa_hours = fa_forecast.get("hours") or []
    stops: list[dict] = []
    prev_zone = origin_zone
    prev_lat, prev_lon = cur_lat, cur_lon
    used_zones_recently: list[str] = []
    bt_live_zones_seen: set[str] = set()
    bt_typical_zones_seen: set[str] = set()
    active_signal_sources: set[str] = set()

    for step_idx in range(max_slots):
        slot_hour_utc = base_hour_utc + timedelta(hours=step_idx)
        hr_start_utc = current_utc if step_idx == 0 else slot_hour_utc
        if step_idx > 0 and hr_start_utc >= horizon_end_utc:
            break
        hr_end_utc = slot_hour_utc + timedelta(hours=1)
        if hr_end_utc <= hr_start_utc:
            hr_end_utc = hr_start_utc + timedelta(hours=1)
        if hr_end_utc > horizon_end_utc:
            hr_end_utc = horizon_end_utc
        if step_idx > 0 and (hr_end_utc - hr_start_utc) < timedelta(minutes=15):
            if stops:
                stops[-1]["ends_at"] = horizon_end.isoformat()
                prev_start = _parse_iso_aware(stops[-1].get("starts_at"))
                if prev_start is not None:
                    stops[-1]["window_label"] = _format_hour_window(prev_start.astimezone(PACIFIC), horizon_end)
            break
        slot_hour = slot_hour_utc.astimezone(PACIFIC)
        hr_start = hr_start_utc.astimezone(PACIFIC)
        hr_end = hr_end_utc.astimezone(PACIFIC)
        is_final_step = hr_end_utc >= (horizon_end_utc - timedelta(minutes=14))
        hr_next = (slot_hour_utc + timedelta(hours=1)).astimezone(PACIFIC)
        fa_bucket = _match_airport_bucket(fa_hours, hr_start, hr_end, step_idx)

        best_candidate: dict | None = None
        lookup_hr = local_now.hour if step_idx == 0 else slot_hour.hour
        prev_hist_row = hist_by_zone_hour.get((prev_zone.id, lookup_hr)) or hist_by_zone_hour.get((prev_zone.id, slot_hour.hour))
        prev_hist_samples = (
            origin_trip_samples
            if (step_idx == 0 and is_residential_origin)
            else int((prev_hist_row or {}).get("sample_trips") or 0)
        )

        for z in registry.zones:
            approved_anc = approved_anchors_by_zone.get(z.id)
            dest_lat = float(getattr(approved_anc, "latitude", z.latitude)) if approved_anc else z.latitude
            dest_lon = float(getattr(approved_anc, "longitude", z.longitude)) if approved_anc else z.longitude

            hist_row_early = hist_by_zone_hour.get((z.id, lookup_hr)) or hist_by_zone_hour.get((z.id, slot_hour.hour))
            if step_idx == 0:
                if z.id == origin_zone.id and not has_exact_pin:
                    dist_mi = 0.0
                    drive_mins = 0
                elif not has_exact_pin and hist_row_early is not None and hist_row_early.get("reposition_minutes") is not None:
                    dist_mi = float(hist_row_early.get("reposition_miles") or _distance_miles(cur_lat, cur_lon, dest_lat, dest_lon))
                    drive_mins = max(1, int(round(float(hist_row_early["reposition_minutes"]))))
                else:
                    dist_mi = _distance_miles(cur_lat, cur_lon, dest_lat, dest_lon)
                    drive_mins = 0 if dist_mi < 0.15 else max(2, int(round(dist_mi * 2.1 + (4 if dist_mi > 3.5 else 0))))
            else:
                if z.id == prev_zone.id:
                    dist_mi = 0.0
                    drive_mins = 0
                else:
                    dist_mi = _distance_miles(prev_lat, prev_lon, dest_lat, dest_lon)
                    drive_mins = max(2, int(round(dist_mi * 2.1 + (4 if dist_mi > 3.5 else 0))))

            earliest_arrival = hr_start + timedelta(minutes=drive_mins)
            if z.id != prev_zone.id:
                if eff_reposition_under is not None and drive_mins > eff_reposition_under:
                    continue
                step_bound_end = horizon_end if step_idx == 0 else hr_end
                if earliest_arrival + timedelta(minutes=15) > step_bound_end:
                    continue

            # A. BestTime Hotspots & Spillout Waves in this zone at `slot_hour`
            zone_venues_active = []
            zone_spillouts = []
            bt_score = 0.0

            for v_item in bt_venues:
                req = v_item.get("requested") or {}
                if req.get("zone") != z.id:
                    continue
                fc = v_item.get("forecast") or {}
                lv = v_item.get("live") or {}
                fc_fresh = not fc.get("retrieved_at") or _is_fresh_iso(
                    fc.get("retrieved_at"), current_utc, max_minutes=14 * 24 * 60.0
                )
                pct_hr = _typical_for_hour(fc, slot_hour) if fc_fresh else None
                live_retrieved_dt = _parse_iso_aware(lv.get("retrieved_at"))
                live_same_hour = (
                    live_retrieved_dt is not None
                    and live_retrieved_dt.astimezone(PACIFIC).hour == slot_hour.hour
                    and _is_fresh_iso(lv.get("retrieved_at"), current_utc, max_minutes=60.0)
                )
                live_fresh = (
                    step_idx == 0
                    and bool(lv.get("available"))
                    and isinstance(lv.get("busyness"), (int, float))
                    and _is_fresh_iso(lv.get("retrieved_at"), current_utc, max_minutes=90.0)
                )
                if live_fresh:
                    pct_hr = int(lv["busyness"])
                    bt_live_zones_seen.add(z.id)
                elif (
                    step_idx == 0
                    and pct_hr is None
                    and live_same_hour
                    and isinstance(lv.get("typical_this_hour"), (int, float))
                ):
                    pct_hr = int(lv["typical_this_hour"])
                    bt_typical_zones_seen.add(z.id)
                elif isinstance(pct_hr, (int, float)) and pct_hr >= 35:
                    bt_typical_zones_seen.add(z.id)

                pct_nxt = _typical_for_hour(fc, hr_next) if fc_fresh else None
                if not isinstance(pct_hr, (int, float)) or pct_hr < 35:
                    continue

                # On Step 0, weekly typical patterns are context for future hours or current zone,
                # not an immediate live trigger to relocate to a remote zone (R6-01).
                if step_idx == 0 and z.id != prev_zone.id and not live_fresh:
                    continue

                pct_hr_int = int(pct_hr)
                drop = (pct_hr_int - int(pct_nxt)) if isinstance(pct_nxt, (int, float)) else 0
                source_tag = "live" if live_fresh else "typical"
                v_label = f"{req.get('name')} ({source_tag} {pct_hr_int}%)"
                if drop >= 15 and pct_hr_int >= 45:
                    v_label = f"{req.get('name')} ({source_tag} {pct_hr_int}%→{int(pct_nxt)}%)"
                    zone_spillouts.append((live_fresh, v_label))
                    bt_score += (pct_hr_int * 0.45) + (drop * 0.8)
                else:
                    bt_score += pct_hr_int * 0.30

                zone_venues_active.append((pct_hr_int, v_label, req, live_fresh))

            zone_venues_active.sort(key=lambda x: x[0], reverse=True)
            bt_score = min(bt_score, 48.0)

            # B. Events / Concerts / Sports / Ferries / Transit active & reachable in `hr_start..hr_end`
            event_catalysts = []
            event_score = 0.0
            penalty_score = 0.0
            for sig in raw_signals:
                if sig.get("zone") != z.id:
                    continue
                details = sig.get("details") or {}
                if details.get("context_only"):
                    continue
                kind = str(sig.get("kind") or "")
                s_dt_utc = _parse_iso_aware(sig.get("starts_at"))
                e_dt_utc = _parse_iso_aware(sig.get("ends_at"))
                if s_dt_utc is None or e_dt_utc is None:
                    continue
                s_dt = s_dt_utc.astimezone(PACIFIC)
                e_dt = e_dt_utc.astimezone(PACIFIC)
                if e_dt <= hr_start or s_dt >= hr_end:
                    continue

                if kind in PENALTY_SIGNAL_KINDS:
                    mag_pen = float(sig.get("magnitude") or 5.0)
                    penalty_score += min(25.0, max(2.0, mag_pen))
                    if sig.get("source"):
                        active_signal_sources.add(str(sig["source"]))
                    continue

                if kind not in POSITIVE_SIGNAL_KINDS:
                    continue

                # Arrival feasibility check (R02): driver must arrive at least 10m before window ends
                if e_dt < earliest_arrival + timedelta(minutes=10):
                    continue

                # On Step 0, remote opportunity moves require an approved anchor (matching here._pick_action)
                if step_idx == 0 and z.id != prev_zone.id and approved_anc is None:
                    continue

                title = str(details.get("title") or details.get("venue") or kind)
                if title.startswith("BestTime foot traffic"):
                    continue
                if step_idx == 0 and (
                    title.startswith("Link Light Rail arriving")
                    or str(sig.get("source") or "").startswith("onebusaway:station_arrivals")
                ):
                    continue
                if sig.get("source"):
                    active_signal_sources.add(str(sig["source"]))
                mag = float(sig.get("magnitude") or 1000.0)
                if kind == "event_exit":
                    event_score += min(38.0, 14.0 + mag / 1200.0)
                    event_catalysts.append(f"🎟 Exit: {title}")
                elif kind in {"ferry_arrival", "cruise_turnaround"}:
                    event_score += 20.0
                    event_catalysts.append(f"⛴ Maritime: {title}")
                elif kind == "surge":
                    event_score += 22.0
                    event_catalysts.append(f"⚡ Surge: {title}")
                else:
                    event_score += min(24.0, 10.0 + mag / 2000.0)
                    event_catalysts.append(f"📍 {title}")

            # C. Sea-Tac Airport Flight Bank in `hr_start`
            flight_score = 0.0
            flight_note = ""
            planes = int(fa_bucket.get("estimated_planes") or 0)
            long_haul = int(fa_bucket.get("long_haul_count") or 0)
            is_peak_flight_hr = bool(fa_bucket.get("is_peak"))
            if z.id == "sea_airport" and planes > 0 and (step_idx > 0 or origin_zone.id == "sea_airport"):
                flight_score = (planes * 0.85) + (long_haul * 3.5) + (16.0 if is_peak_flight_hr else 0.0)
                lot_target = fa_bucket.get("lot_arrival_target")
                if lot_target:
                    flight_note = f"✈ ~{planes} KSEA arrivals ({long_haul} widebody) · FIFO Lot by {lot_target}"
                else:
                    flight_note = f"✈ ~{planes} KSEA arrivals ({long_haul} widebody)"

            # D. Historical Net $/hr in this zone & hour (R01/F01 & R6-01 calibration)
            hist_row = hist_by_zone_hour.get((z.id, lookup_hr)) or hist_by_zone_hour.get((z.id, slot_hour.hour))
            hist_net: float | None = None
            hist_sample = 0
            hist_grain = "none"
            if hist_row is not None and "historical_net_per_hour" in hist_row and hist_row["historical_net_per_hour"] is not None:
                hist_sample = int(hist_row.get("sample_trips") or 0)
                hist_grain = str(hist_row.get("grain") or "none")
                if step_idx == 0 and is_residential_origin and z.id == origin_zone.id and origin_trip_samples <= 0:
                    hist_sample = 0
                    hist_grain = "none"
                    hist_net = None
                elif hist_sample > 0:
                    hist_net = float(hist_row["historical_net_per_hour"])

            repo_penalty = dist_mi * 1.4
            cal_drive_mins = (
                float(hist_row.get("reposition_minutes") or drive_mins)
                if (step_idx == 0 and not has_exact_pin and hist_row is not None and z.id != prev_zone.id)
                else float(drive_mins)
            )
            if step_idx == 0 and z.id != prev_zone.id and eff_reposition_under is not None and cal_drive_mins > float(eff_reposition_under):
                continue

            if z.id == prev_zone.id:
                if step_idx == 0 and hist_row is not None and "score" in hist_row and hist_net is not None and not bool(hist_row.get("thin", False)):
                    hist_score = max(0.0, float(hist_row["score"]))
                elif step_idx == 0 and (hist_row is None or bool(hist_row.get("thin", True))) and not any(v[3] for v in zone_venues_active) and not event_catalysts:
                    bt_score = min(bt_score, 18.0)
                    hist_score = min(15.0, max(0.0, hist_net) * 0.30) if hist_net is not None else 0.0
                else:
                    hist_score = min(25.0, max(0.0, hist_net) * 0.45) if hist_net is not None else 0.0
            elif not (
                step_idx == 0
                and (
                    (is_residential_origin and origin_trip_samples < 2)
                    or (place.get("origin_kind") == "pickup_center" and origin_trip_samples == 0)
                )
            ) and _here_mod.is_calibrated_historical_move(
                prev_hist_row,
                hist_row,
                stay_samples=prev_hist_samples,
                max_reposition_minutes=float(eff_reposition_under or 20),
                drive_minutes=cal_drive_mins,
                min_score_advantage=12.0,
            ):
                if step_idx == 0 and hist_row is not None and "score" in hist_row:
                    hist_score = max(0.0, float(hist_row["score"])) + repo_penalty
                else:
                    hist_score = min(35.0, max(0.0, hist_net) * 0.55) if hist_net is not None else 0.0
            else:
                hist_score = 0.0

            outcome_info = outcome_by_zone.get(z.id) or {}
            outcome_adj = float(outcome_info.get("score_adjustment") or 0.0) if step_idx == 0 else 0.0
            positive_evidence = bt_score + event_score + flight_score + hist_score + max(0.0, outcome_adj)
            if outcome_adj < 0:
                penalty_score += abs(outcome_adj)
            if z.id != prev_zone.id and positive_evidence <= 0:
                continue

            # E. Repositioning Distance Penalty & Finish-Near Alignment
            repeat_count = sum(1 for uz in used_zones_recently[-2:] if uz == z.id)
            # Only apply repeat penalty when positive evidence exists; never force empty relocation (R01)
            repeat_penalty = 0.0
            if positive_evidence > 0 and repeat_count >= 2:
                repeat_penalty = 4.0

            finish_bonus = 0.0
            if finish_zone is not None and is_final_step and positive_evidence > 0:
                finish_dist_mi = (
                    0.0
                    if z.id == finish_zone.id
                    else _distance_miles(dest_lat, dest_lon, finish_zone.latitude, finish_zone.longitude)
                )
                finish_drive_mins = (
                    0
                    if z.id == finish_zone.id
                    else max(2, int(round(finish_dist_mi * 2.1 + (4 if finish_dist_mi > 3.5 else 0))))
                )
                if z.id == finish_zone.id:
                    finish_bonus = 20.0
                elif eff_reposition_under is not None and finish_drive_mins > eff_reposition_under:
                    finish_bonus = -35.0
                else:
                    finish_bonus = max(0.0, 12.0 - finish_dist_mi * 2.0)

            eff_penalty = (
                0.0
                if (step_idx == 0 and z.id != prev_zone.id and approved_anc is None and not any(v[3] for v in zone_venues_active))
                else penalty_score
            )
            total_score = positive_evidence + finish_bonus - eff_penalty - repo_penalty - repeat_penalty

            triggers = []
            if flight_note:
                triggers.append(flight_note)
            if zone_spillouts:
                any_live_spill = any(is_lv for is_lv, _ in zone_spillouts[:2])
                prefix = "🔥 Live venue drop-off: " if any_live_spill else "📊 Typical weekly activity: "
                triggers.append(prefix + ", ".join(lbl for _, lbl in zone_spillouts[:2]))
            elif zone_venues_active:
                any_live_act = any(v[3] for v in zone_venues_active[:3])
                prefix = "🔥 Live venue activity: " if any_live_act else "📊 Typical weekly activity: "
                triggers.append(prefix + ", ".join(v[1] for v in zone_venues_active[:3]))
            if event_catalysts:
                triggers.extend(event_catalysts[:2])
            if not triggers and hist_net is not None and hist_sample > 0:
                triggers.append(f"📊 Paid-trip archive (${hist_net:.0f}/hr across {hist_sample} trips)")
            if outcome_info.get("note") and step_idx == 0:
                triggers.append(str(outcome_info["note"]))
            if finish_zone is not None and is_final_step and z.id == finish_zone.id and positive_evidence > 0:
                triggers.append(f"🏁 Finishes near {finish_zone.label}")
            if not triggers:
                triggers.append("⏸ Insufficient live or historical evidence — hold position")

            # R02: Only approved anchors expose staging curb navigation
            pc_for_zone = next((c for c in registry.pickup_centers if c.zone == z.id), None)
            if approved_anc is not None:
                staging_name = str(getattr(approved_anc, "label", z.label))
                maps_url = f"https://www.google.com/maps/dir/?api=1&destination={dest_lat},{dest_lon}"
                navigation_available = True
                anchor_id = str(getattr(approved_anc, "id", ""))
            else:
                staging_name = f"{z.label} (unapproved curb — area reference only)"
                maps_url = ""
                navigation_available = False
                anchor_id = None

            has_live_act = any(v[3] for v in zone_venues_active) or bool(event_catalysts)
            has_cat = bool(zone_venues_active or event_catalysts or (z.id == "sea_airport" and planes > 0))
            if z.id != prev_zone.id:
                step_action = "MOVE"
            elif has_cat:
                step_action = "WAIT"
            elif hist_net is not None and hist_sample > 0:
                step_action = "WAIT"
            else:
                step_action = "WATCH"
            step_basis = (
                "live_opportunity"
                if has_live_act
                else "scheduled_catalyst"
                if has_cat
                else ("historical_and_positioning" if z.id != prev_zone.id else "paid_trip_archive")
                if (hist_net is not None and hist_sample > 0)
                else "uncalibrated"
            )
            step_state = (
                "AIRPORT_LOT"
                if z.id == "sea_airport"
                else ("MOVE" if step_action == "MOVE" else ("STAY" if step_action == "WAIT" else "WATCH"))
            )
            step_recheck = 15 if step_action == "WAIT" else 10

            cand = {
                "hour_index": step_idx + 1,
                "window_label": _format_hour_window(hr_start, hr_end),
                "starts_at": hr_start.isoformat(),
                "ends_at": hr_end.isoformat(),
                "hour_24": slot_hour.hour,
                "zone": z.id,
                "zone_label": z.label,
                "action": step_action,
                "decision_state": step_state,
                "recommendation_basis": step_basis,
                "origin_kind": place.get("origin_kind", "zone_centroid") if step_idx == 0 else "previous_stop",
                "origin_place_id": place.get("place_id", origin_zone.id) if step_idx == 0 else prev_zone.id,
                "destination_id": (
                    place.get("place_id", origin_zone.id)
                    if (step_idx == 0 and step_action != "MOVE")
                    else (
                        anchor_id
                        or (pc_for_zone.id if (step_idx == 0 and step_basis == "historical_and_positioning" and pc_for_zone is not None) else z.id)
                    )
                ),
                "destination_label": (
                    place.get("label", origin_zone.label)
                    if (step_idx == 0 and step_action != "MOVE")
                    else (
                        staging_name
                        if navigation_available
                        else (pc_for_zone.label if (step_idx == 0 and step_basis == "historical_and_positioning" and pc_for_zone is not None) else z.label)
                    )
                ),
                "staging_approved": navigation_available,
                "recheck_minutes": step_recheck,
                "recheck_at": (hr_start + timedelta(minutes=step_recheck)).isoformat(),
                "score": round(total_score, 1),
                "staging_spot": staging_name,
                "anchor_id": anchor_id,
                "navigation_available": navigation_available,
                "maps_url": maps_url,
                "primary_trigger": " · ".join(triggers[:2]),
                "hot_venues": [v[1] for v in zone_venues_active[:4]],
                "spillout_venues": zone_spillouts[:3],
                "events": event_catalysts[:3],
                "flight_arrivals": planes if z.id == "sea_airport" else 0,
                "drive_minutes_from_prev": drive_mins,
                "distance_miles_from_prev": round(dist_mi, 1),
                "reposition_label": (
                    f"Stay in {z.label} (0 min reposition)"
                    if drive_mins == 0 and z.id == prev_zone.id
                    else f"~{drive_mins} min drive ({dist_mi:.1f} mi) from {prev_zone.label if step_idx > 0 else 'current pin'}"
                ),
                "expected_net_per_hour": round(hist_net, 2) if hist_net is not None else None,
                "sample_trips": hist_sample,
                "historical_grain": hist_grain if hist_sample > 0 else "none",
                "rate_basis": "paid_trip_time_only" if hist_net is not None else "unknown",
                "predicted_online_net_per_hour": None,
                "_has_live_or_event": has_cat,
                "_zone_obj": z,
                "_dest_lat": dest_lat,
                "_dest_lon": dest_lon,
            }
            if best_candidate is None or cand["score"] > best_candidate["score"]:
                best_candidate = cand

        assert best_candidate is not None

        # Unify Step 0 with `here._pick_action` positioning & pickup-center rules (R6-01)
        if step_idx == 0 and driver_mode == "active_working":
            if (
                is_residential_origin
                and best_candidate["zone"] == origin_zone.id
                and not best_candidate.get("_has_live_or_event")
                and origin_trip_samples < 2
            ):
                now_rows_hr = [
                    r for (zid_k, hr_k), r in hist_by_zone_hour.items() if hr_k == slot_hour.hour
                ]
                pos_cand, _ = _here_mod._evaluate_positioning_candidates(
                    place,
                    now_rows_hr,
                    local_now,
                    max_reposition_minutes=min(float(eff_reposition_under or 20), 15.0),
                    vehicle_cost_per_mile=vehicle_cost,
                    origin_trip_samples=origin_trip_samples,
                )
                if pos_cand is not None:
                    pos_z = registry.by_id.get(pos_cand["zone"]) or origin_zone
                    pos_mins = max(1, int(round(float(pos_cand["reposition_minutes"]))))
                    pos_miles = round(float(pos_cand["reposition_miles"]), 1)
                    pos_nav = bool(pos_cand["navigation_available"])
                    best_candidate.update({
                        "zone": pos_z.id,
                        "zone_label": pos_cand["name"],
                        "action": "MOVE",
                        "decision_state": "MOVE",
                        "recommendation_basis": pos_cand["recommendation_basis"],
                        "destination_id": pos_cand["id"],
                        "destination_label": pos_cand["name"],
                        "staging_approved": bool(pos_cand["staging_approved"]),
                        "navigation_available": pos_nav,
                        "staging_spot": (
                            pos_cand["staging_notes"]
                            if pos_nav
                            else f"{pos_cand['name']} (unapproved curb — area reference only)"
                        ),
                        "anchor_id": pos_cand["anchor_id"] if pos_nav else None,
                        "maps_url": (
                            f"https://www.google.com/maps/dir/?api=1&destination={pos_cand['latitude']},{pos_cand['longitude']}"
                            if pos_nav
                            else ""
                        ),
                        "drive_minutes_from_prev": pos_mins,
                        "distance_miles_from_prev": pos_miles,
                        "reposition_label": f"~{pos_mins} min drive ({pos_miles:.1f} mi) from Home",
                        "primary_trigger": f"Positioning suggestion · live demand unknown — {pos_cand['suitability_reason']}",
                        "recheck_minutes": 10,
                        "recheck_at": (hr_start + timedelta(minutes=10)).isoformat(),
                        "_zone_obj": pos_z,
                        "_dest_lat": float(pos_cand["latitude"]),
                        "_dest_lon": float(pos_cand["longitude"]),
                    })
            elif (
                place.get("origin_kind") == "pickup_center"
                and best_candidate["zone"] == origin_zone.id
                and not best_candidate.get("_has_live_or_event")
                and int(best_candidate.get("sample_trips") or 0) == 0
            ):
                pc = next(
                    (c for c in registry.pickup_centers if c.id == place.get("place_id") or c.zone == origin_zone.id),
                    None,
                )
                if pc is not None and pc.active_start_hour <= slot_hour.hour <= pc.active_end_hour:
                    pc_approved = _here_mod._is_center_approved(pc, anchors)
                    best_candidate.update({
                        "action": "WAIT",
                        "decision_state": "STAY",
                        "recommendation_basis": "positioned_pickup_center",
                        "destination_id": pc.id,
                        "destination_label": pc.label,
                        "staging_approved": pc_approved,
                        "navigation_available": pc_approved,
                        "recheck_minutes": 15,
                        "recheck_at": (hr_start + timedelta(minutes=15)).isoformat(),
                        "primary_trigger": (
                            f"Positioned at {pc.label} pickup center (open {pc.active_start_hour}:00–{pc.active_end_hour}:00) "
                            "· current demand unverified (hold 15m wait)"
                        ),
                    })

        best_candidate.pop("_has_live_or_event", None)
        prev_zone = best_candidate.pop("_zone_obj")
        prev_lat = best_candidate.pop("_dest_lat")
        prev_lon = best_candidate.pop("_dest_lon")
        used_zones_recently.append(best_candidate["zone"])
        stops.append(best_candidate)

    # 5. Collect Top Metro-Wide BestTime Hotspots Right Now (only fresh live or explicitly typical)
    top_hotspots_now = []
    for v_item in bt_venues:
        req = v_item.get("requested") or {}
        fc = v_item.get("forecast") or {}
        lv = v_item.get("live") or {}
        fc_fresh = not fc.get("retrieved_at") or _is_fresh_iso(
            fc.get("retrieved_at"), current_utc, max_minutes=14 * 24 * 60.0
        )
        live_ok = (
            bool(lv.get("available"))
            and isinstance(lv.get("busyness"), (int, float))
            and _is_fresh_iso(lv.get("retrieved_at"), current_utc, max_minutes=90.0)
        )
        cur_p = lv.get("busyness") if live_ok else (_typical_for_hour(fc, local_now) if fc_fresh else None)
        nxt_p = _typical_for_hour(fc, local_now + timedelta(hours=1)) if fc_fresh else None
        if isinstance(cur_p, (int, float)) and cur_p >= 45:
            z_id = str(req.get("zone") or "")
            anc = approved_anchors_by_zone.get(z_id)
            top_hotspots_now.append({
                "name": req.get("name"),
                "area": req.get("area") or req.get("city"),
                "zone": z_id,
                "busyness_pct": int(cur_p),
                "is_live": live_ok,
                "next_hour_pct": int(nxt_p) if isinstance(nxt_p, (int, float)) else None,
                "spillout_drop": (int(cur_p) - int(nxt_p)) if isinstance(nxt_p, (int, float)) else 0,
                "maps_url": (
                    f"https://www.google.com/maps/dir/?api=1&destination={getattr(anc, 'latitude')},{getattr(anc, 'longitude')}"
                    if anc is not None
                    else ""
                ),
            })
    top_hotspots_now.sort(key=lambda x: x["busyness_pct"], reverse=True)

    fa_total_planes = sum(int(h.get("estimated_planes") or 0) for h in (fa_forecast.get("hours") or []))

    course_has_evidence = (
        fa_total_planes > 0
        or bool(top_hotspots_now)
        or any(
            (s.get("expected_net_per_hour") is not None and int(s.get("sample_trips") or 0) > 0)
            or bool(s.get("hot_venues"))
            or bool(s.get("events"))
            or int(s.get("flight_arrivals") or 0) > 0
            for s in stops
        )
    )

    from farol import shift as _shift_mod

    llm_warm = False
    if pull_all and course_has_evidence:
        try:
            ep, al = local_runtime.settings()
            llm_warm = bool(_shift_mod.active() or local_runtime.model_ready(ep, al))
        except Exception:
            llm_warm = False

    action_plan, ai_briefing, model_used, llm_elapsed_ms = _generate_formatted_action_plan(
        origin_label=origin_zone.label,
        stops=stops,
        top_hotspots=top_hotspots_now[:10],
        fa_forecast=fa_forecast,
        fa_total_planes=fa_total_planes,
        train_stations=train_stations[:3],
        run_live_llm=pull_all and course_has_evidence and llm_warm,
    )

    polled_clock = _format_clock_with_sec(local_now)
    api_ms = int(blast.get("blast_elapsed_ms", 0))
    live_reqs = int(blast.get("live_http_requests", 0))
    if pull_all:
        poll_receipt = (
            f"LIVE BLAST @ {polled_clock} · {live_reqs} fresh HTTP calls ({api_ms / 1000:.1f}s) "
            f"+ formatter ({llm_elapsed_ms / 1000:.1f}s)"
        )
    else:
        poll_receipt = (
            f"SNAPSHOT ({polled_clock}) · 0 outbound HTTP calls · Tap '🚀 Blast All APIs' for a live pull"
        )

    finish_constraint_status = "none"
    finish_constraint_note = ""
    if finish_zone is not None and stops:
        if stops[-1]["zone"] == finish_zone.id:
            finish_constraint_status = "satisfied"
            finish_constraint_note = f"Final window ends in {finish_zone.label}."
        else:
            last_z = registry.by_id.get(stops[-1]["zone"]) or origin_zone
            f_dist = _distance_miles(last_z.latitude, last_z.longitude, finish_zone.latitude, finish_zone.longitude)
            f_mins = max(2, int(round(f_dist * 2.1 + (4 if f_dist > 3.5 else 0))))
            if eff_reposition_under is not None and f_mins > eff_reposition_under:
                finish_constraint_status = "exceeds_drive_limit"
                finish_constraint_note = (
                    f"Finish-near target {finish_zone.label} is ~{f_mins} min away "
                    f"(exceeds {eff_reposition_under} min drive limit); holding in {stops[-1]['zone_label']}."
                )
            else:
                finish_constraint_status = "unverified_final_demand"
                finish_constraint_note = (
                    f"Finish-near target {finish_zone.label} (~{f_mins} min drive) has no verified final-hour "
                    f"demand catalyst; holding in {stops[-1]['zone_label']} to avoid an empty deadhead."
                )

    first_stop = stops[0] if stops else {}
    current_decision = {
        "action": str(first_stop.get("action") or "WATCH"),
        "decision_state": str(first_stop.get("decision_state") or "WATCH"),
        "recommendation_basis": str(first_stop.get("recommendation_basis") or "uncalibrated"),
        "origin_kind": str(first_stop.get("origin_kind") or place.get("origin_kind", "zone_centroid")),
        "origin_place_id": str(first_stop.get("origin_place_id") or place.get("place_id", origin_zone.id)),
        "origin_zone": origin_zone.id,
        "origin_label": origin_zone.label,
        "destination_id": str(first_stop.get("destination_id") or origin_zone.id),
        "destination_label": str(first_stop.get("destination_label") or origin_zone.label),
        "zone": str(first_stop.get("zone") or origin_zone.id),
        "zone_label": str(first_stop.get("zone_label") or origin_zone.label),
        "staging_approved": bool(first_stop.get("staging_approved", False)),
        "navigation_available": bool(first_stop.get("navigation_available", False)),
        "maps_url": str(first_stop.get("maps_url") or ""),
        "drive_minutes_from_prev": int(first_stop.get("drive_minutes_from_prev") or 0),
        "distance_miles_from_prev": float(first_stop.get("distance_miles_from_prev") or 0.0),
        "primary_trigger": str(first_stop.get("primary_trigger") or ""),
        "recheck_minutes": int(first_stop.get("recheck_minutes") or 10),
        "recheck_at": str(first_stop.get("recheck_at") or ""),
    }

    try:
        from farol.collect import build_source_coverage_inventory

        source_coverage = build_source_coverage_inventory(
            now=current_utc,
            chosen_zone=current_decision["zone"],
            chosen_action=current_decision["action"],
            chosen_basis=current_decision["recommendation_basis"],
            active_signal_sources=active_signal_sources,
            besttime_live_zones=bt_live_zones_seen,
            besttime_typical_zones=bt_typical_zones_seen,
            flightaware_planes=fa_total_planes,
            health=health_view,
        )
    except Exception:
        source_coverage = []

    return {
        "ok": True,
        "is_live_blast": pull_all,
        "generated_at": current_utc.isoformat(),
        "polled_clock": polled_clock,
        "poll_receipt": poll_receipt,
        "origin_zone": origin_zone.id,
        "origin_label": origin_zone.label,
        "origin_kind": place.get("origin_kind", "zone_centroid"),
        "origin_place_id": place.get("place_id", origin_zone.id),
        "current_decision": current_decision,
        "source_coverage": source_coverage,
        "constraints_applied": {
            "origin_zone": origin_zone.id,
            "origin_label": origin_zone.label,
            "origin_kind": place.get("origin_kind", "zone_centroid"),
            "origin_place_id": place.get("place_id", origin_zone.id),
            "minutes_available": eff_minutes_available,
            "reposition_under_minutes": eff_reposition_under,
            "finish_near": finish_near or "",
            "finish_near_zone": finish_zone.id if finish_zone is not None else "",
            "finish_near_label": finish_zone.label if finish_zone is not None else "",
            "finish_constraint_status": finish_constraint_status,
            "finish_constraint_note": finish_constraint_note,
        },
        "blast_elapsed_ms": api_ms,
        "llm_elapsed_ms": llm_elapsed_ms,
        "apis_fired": {
            "total_feeds_online": int(health_view.get("green_count", 0)),
            "total_feeds_catalog": int(health_view.get("total_count", 23)),
            "besttime_venues_scanned": len(bt_venues),
            "besttime_hotspots_active": len(top_hotspots_now),
            "flightaware_6h_planes": fa_total_planes,
            "flightaware_peak_window": str(fa_forecast.get("best_hour_label") or ""),
            "nearby_train_stations": len(train_stations),
            "live_http_requests": live_reqs,
        },
        "ai_model": model_used,
        "ai_briefing": ai_briefing,
        "action_plan": action_plan,
        "top_hotspots_now": top_hotspots_now[:10],
        "stops": stops,
    }


def _plan_signature(origin_label: str, stops: list[dict], fa_total_planes: int) -> str:
    summary = {
        "origin": origin_label,
        "stops": [
            (
                s.get("zone"),
                s.get("window_label"),
                s.get("expected_net_per_hour"),
                s.get("primary_trigger"),
            )
            for s in stops
        ],
        "planes": fa_total_planes,
    }
    digest = hashlib.sha256(json.dumps(summary, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"v3:{origin_label}:{digest}"


def _norm_clock_str(text: str) -> set[str]:
    return {
        re.sub(r"\s+", " ", m.strip().lower())
        for m in re.findall(r"\b\d{1,2}:\d{2}\s*(?:am|pm)\b", text.lower())
    }


_HOLD_CONNECTOR_TOKENS: frozenset[str] = frozenset({
    "0", "5", "a", "active", "am", "and", "archive", "area", "arrival", "arrivals",
    "at", "baselines", "before", "catalyst", "current", "deadhead", "demand",
    "do", "earnings", "evidence", "feeds", "fifo", "flightaware", "flights",
    "forecast", "fresh", "have", "hold", "hr", "in", "insufficient", "live",
    "loaded", "lot", "mi", "mid", "moving", "no", "not", "now", "on", "paid",
    "pm", "pulling", "recheck", "relocate", "sea", "shift", "snapshot", "sound",
    "stage", "stations", "stay", "tac", "the", "to", "transit", "trip", "trips",
    "unknown", "unverified", "verified", "wave", "within", "without",
})

_ACTIVE_CONNECTOR_TOKENS: frozenset[str] = frozenset(
    _HOLD_CONNECTOR_TOKENS
    | {
        "6h", "activity", "afternoon", "airport", "an", "approved", "are",
        "bank", "by", "consider", "curb", "curbs", "during", "evening",
        "for", "from", "gated", "has", "hour", "hours", "immediate", "is",
        "keep", "late", "link", "local", "monitor", "morning", "move",
        "navigation", "next", "night", "of", "only", "over", "peak", "pivot",
        "pulls", "queue", "skip", "spillout", "spillouts", "stays", "surge",
        "tactical", "telemetry", "train", "until", "venues", "watchouts",
        "window", "with",
    }
)

_APPROVED_MOVE_TOKENS: frozenset[str] = frozenset({
    "drive", "head", "leave", "proceed", "reposition", "staging",
})


def course_fact_catalog(
    stops: list[dict],
    fa_total_planes: int,
    top_hotspots: list[dict] | None = None,
    fa_forecast: dict | None = None,
    train_stations: list[dict] | None = None,
) -> dict:
    """Build a strict grounding catalog and token whitelist from structured course inputs."""
    allowed_dollars: set[str] = set()
    allowed_zones: set[str] = set()
    allowed_targets: set[str] = set()
    evidence_blobs: list[str] = []
    allowed_numbers: set[str] = {"0", "5", "6", str(len(train_stations or []))}
    any_approved_curb = False
    has_any_evidence = fa_total_planes > 0 or bool(top_hotspots)
    stop_records: list[dict] = []

    for idx, s in enumerate(stops):
        val = s.get("expected_net_per_hour")
        sample_trips = int(s.get("sample_trips") or (1 if isinstance(val, (int, float)) and val > 0 else 0))
        stop_dollars: set[str] = set()
        if isinstance(val, (int, float)) and sample_trips > 0:
            rounded_dollar = str(int(round(val)))
            formatted_dollar = f"{val:.2f}"
            allowed_dollars.add(rounded_dollar)
            allowed_dollars.add(formatted_dollar)
            stop_dollars.add(rounded_dollar)
            stop_dollars.add(formatted_dollar)
            allowed_numbers.add(rounded_dollar)
            allowed_numbers.add(str(sample_trips))
            evidence_blobs.append(rounded_dollar)
            evidence_blobs.append(str(sample_trips))
            has_any_evidence = True
        fl_arr = int(s.get("flight_arrivals") or 0)
        if (
            s.get("hot_venues")
            or s.get("events")
            or fl_arr > 0
            or s.get("recommendation_basis") in {"positioning_heuristic", "positioned_pickup_center"}
        ):
            has_any_evidence = True
        if fl_arr > 0:
            allowed_numbers.add(str(fl_arr))
            evidence_blobs.append(str(fl_arr))
        z_lbl = str(s.get("zone_label") or "").strip().lower()
        z_id = str(s.get("zone") or "").replace("_", " ").strip().lower()
        if z_lbl:
            allowed_zones.add(z_lbl)
            allowed_targets.add(z_lbl)
            evidence_blobs.append(z_lbl)
        if z_id:
            allowed_zones.add(z_id)
            allowed_targets.add(z_id)
            evidence_blobs.append(z_id)
        nav_ok = bool(s.get("navigation_available"))
        approved_spot = ""
        if nav_ok:
            any_approved_curb = True
            spot = str(s.get("staging_spot") or "").strip().lower()
            if spot:
                approved_spot = spot
                allowed_targets.add(spot)
                evidence_blobs.append(spot)
        for field_name in ("window_label", "primary_trigger"):
            if s.get(field_name):
                txt = str(s[field_name])
                evidence_blobs.append(txt)
                for num_tok in re.findall(r"\b\d+\b", txt):
                    allowed_numbers.add(num_tok)
        stop_venues: list[str] = []
        stop_events: list[str] = []
        for list_field in ("hot_venues", "spillout_venues", "events"):
            for item in s.get(list_field) or []:
                item_str = str(item).strip()
                evidence_blobs.append(item_str)
                for num_tok in re.findall(r"\b\d+\b", item_str):
                    allowed_numbers.add(num_tok)
                clean_name = re.sub(
                    r"^[^\w]+",
                    "",
                    item_str.split("(")[0].replace("Exit:", "").replace("Maritime:", "").replace("Surge:", ""),
                ).strip().lower()
                if clean_name:
                    allowed_targets.add(clean_name)
                    if list_field == "events":
                        stop_events.append(clean_name)
                    else:
                        stop_venues.append(clean_name)

        win_lbl = str(s.get("window_label") or "")
        identifiers = {x for x in (z_lbl, z_id, approved_spot) if x}
        stop_records.append(
            {
                "stop_id": f"stop_{idx}",
                "index": idx,
                "hour_index": int(s.get("hour_index") if s.get("hour_index") is not None else idx),
                "zone": str(s.get("zone") or "").strip().lower() or z_lbl,
                "zone_phrase": z_id,
                "zone_label": z_lbl,
                "window_label": win_lbl,
                "window_times": _norm_clock_str(win_lbl),
                "navigation_available": nav_ok,
                "approved_staging_spot": approved_spot,
                "rate_dollars": stop_dollars,
                "sample_trips": sample_trips if stop_dollars else 0,
                "rate_basis": str(s.get("rate_basis") or ("paid_trip_time_only" if stop_dollars else "unknown")),
                "venues": stop_venues,
                "events": stop_events,
                "flight_arrivals": fl_arr,
                "identifiers": identifiers,
                "raw": s,
            }
        )

    for h in top_hotspots or []:
        if isinstance(h, dict) and h.get("name"):
            h_name = str(h["name"]).strip().lower()
            allowed_targets.add(h_name)
            evidence_blobs.append(h_name)
            if h.get("area"):
                evidence_blobs.append(str(h["area"]))
            for pct_k in ("busyness_pct", "next_hour_pct"):
                if h.get(pct_k) is not None:
                    num_s = str(int(h[pct_k]))
                    allowed_numbers.add(num_s)
                    evidence_blobs.append(num_s)

    fa_blobs: list[str] = []
    if fa_total_planes > 0:
        allowed_numbers.add(str(int(fa_total_planes)))
        evidence_blobs.append(str(int(fa_total_planes)))
        if isinstance(fa_forecast, dict):
            for k in ("best_hour_label", "best_lot_arrival_time"):
                if fa_forecast.get(k):
                    txt = str(fa_forecast[k])
                    evidence_blobs.append(txt)
                    fa_blobs.append(txt)
                    for num_tok in re.findall(r"\b\d+\b", txt):
                        allowed_numbers.add(num_tok)
            for hr_b in fa_forecast.get("hours") or []:
                if isinstance(hr_b, dict):
                    for k in ("label", "lot_arrival_target", "hour_label"):
                        if hr_b.get(k):
                            txt = str(hr_b[k])
                            evidence_blobs.append(txt)
                            fa_blobs.append(txt)
                            for num_tok in re.findall(r"\b\d+\b", txt):
                                allowed_numbers.add(num_tok)

    for st in train_stations or []:
        if isinstance(st, dict) and st.get("name"):
            evidence_blobs.append(str(st["name"]))

    evidence_text = " ".join(evidence_blobs)
    allowed_times = _norm_clock_str(evidence_text)
    fa_times = _norm_clock_str(" ".join(fa_blobs))
    evidence_tokens = set(re.findall(r"[a-z0-9]+", evidence_text.lower())) | allowed_numbers
    if not has_any_evidence and fa_total_planes <= 0:
        allowed_tokens = evidence_tokens | _HOLD_CONNECTOR_TOKENS
    else:
        allowed_tokens = evidence_tokens | _ACTIVE_CONNECTOR_TOKENS
        if any_approved_curb:
            allowed_tokens = allowed_tokens | _APPROVED_MOVE_TOKENS

    allowed_flight_counts = {0} if fa_total_planes <= 0 else (
        {int(fa_total_planes)}
        | {int(s.get("flight_arrivals") or 0) for s in stops if int(s.get("flight_arrivals") or 0) > 0}
    )

    return {
        "has_any_evidence": has_any_evidence,
        "any_approved_curb": any_approved_curb,
        "allowed_dollars": allowed_dollars,
        "allowed_times": allowed_times,
        "fa_times": fa_times,
        "allowed_flight_counts": allowed_flight_counts,
        "allowed_numbers": allowed_numbers,
        "allowed_zones": allowed_zones,
        "allowed_targets": allowed_targets,
        "evidence_tokens": evidence_tokens,
        "allowed_tokens": allowed_tokens,
        "stop_records": stop_records,
    }


def _format_stop_rate(stop: dict) -> str:
    val = stop.get("expected_net_per_hour")
    trips_cnt = int(stop.get("sample_trips") or 0)
    if isinstance(val, (int, float)) and (trips_cnt > 0 or val > 0):
        if trips_cnt > 0:
            return f"~${val:.0f}/hr paid-trip archive ({trips_cnt} trips)"
        return f"~${val:.0f}/hr paid-trip archive"
    return "earnings unknown"


def _parse_clock_minutes(clock_str: str) -> int | None:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*(am|pm)\s*$", clock_str.strip(), re.IGNORECASE)
    if not m:
        return None
    hh = int(m.group(1)) % 12
    mm = int(m.group(2))
    if m.group(3).lower() == "pm":
        hh += 12
    return hh * 60 + mm


def _window_duration_minutes(stop: dict) -> float | None:
    s_dt = _parse_iso_aware(stop.get("starts_at"))
    e_dt = _parse_iso_aware(stop.get("ends_at"))
    if s_dt is not None and e_dt is not None and e_dt > s_dt:
        return (e_dt - s_dt).total_seconds() / 60.0
    win_lbl = str(stop.get("window_label") or "")
    parts = re.split(r"\s*[–-]\s*", win_lbl)
    if len(parts) == 2:
        t1 = _parse_clock_minutes(parts[0])
        t2 = _parse_clock_minutes(parts[1])
        if t1 is not None and t2 is not None:
            diff = t2 - t1
            if diff <= 0:
                diff += 24 * 60
            return float(diff)
    return None


def render_bound_action_plan(
    selection: dict,
    stops: list[dict],
    fa_total_planes: int,
    top_hotspots: list[dict] | None = None,
    fa_forecast: dict | None = None,
    train_stations: list[dict] | None = None,
    origin_label: str = "Selected area",
) -> dict | None:
    """Render a 5-field action plan deterministically from bound stop IDs and properties (H01)."""
    if not isinstance(selection, dict) or not stops:
        return None
    catalog = course_fact_catalog(
        stops,
        fa_total_planes,
        top_hotspots=top_hotspots,
        fa_forecast=fa_forecast,
        train_stations=train_stations,
    )
    stop_records = catalog["stop_records"]
    by_id = {sr["stop_id"]: sr["raw"] for sr in stop_records}
    imm_id = str(selection.get("immediate_stop_id") or "stop_0").strip()
    if imm_id != "stop_0" or imm_id not in by_id:
        return None
    default_piv = "stop_1" if "stop_1" in by_id else "stop_0"
    piv_id = str(selection.get("pivot_stop_id") or default_piv).strip()
    if piv_id not in by_id or (len(stop_records) > 1 and piv_id == "stop_0"):
        return None
    default_late = f"stop_{len(stop_records) - 1}"
    late_id = str(selection.get("late_stop_id") or default_late).strip()
    if late_id not in by_id:
        return None

    s1 = by_id[imm_id]
    s2 = by_id[piv_id]
    s3 = stops[2] if len(stops) >= 3 else s2
    s6 = by_id[late_id]
    fa_peak = str((fa_forecast or {}).get("best_hour_label") or "").strip()
    fa_lot = str((fa_forecast or {}).get("best_lot_arrival_time") or "").strip()

    s1_zone_label = str(s1.get("zone_label") or origin_label)
    origin_rec = zone_record(origin_label) if origin_label not in {"Selected area", "New area"} else None
    s1_rec = zone_record(str(s1.get("zone") or s1_zone_label))
    s1_drive = int(s1.get("drive_minutes_from_prev") or 0)
    s1_is_remote = s1_drive > 0 or (
        origin_rec is not None and s1_rec is not None and origin_rec.id != s1_rec.id
    )
    if s1_is_remote and s1_drive <= 0 and origin_rec is not None and s1_rec is not None:
        dist_est = _distance_miles(origin_rec.latitude, origin_rec.longitude, s1_rec.latitude, s1_rec.longitude)
        s1_drive = max(2, int(round(dist_est * 2.1 + (4 if dist_est > 3.5 else 0))))
    s1_win_mins = _window_duration_minutes(s1)
    s1_unreachable = s1_is_remote and s1_win_mins is not None and s1_win_mins < (s1_drive + 10)

    if not catalog["has_any_evidence"] and fa_total_planes <= 0:
        hold_area = origin_label if s1_is_remote else s1_zone_label
        return {
            "headline": f"Hold in {hold_area} · Insufficient evidence to relocate",
            "immediate_move": (
                f"[{s1.get('window_label', 'Now')}] Hold in {hold_area} "
                f"({_format_stop_rate(s1)}). {s1.get('primary_trigger', 'No active live catalyst')}."
            ),
            "mid_shift_pivot": (
                "No verified mid-shift demand wave in current snapshot. Recheck live feeds before moving."
            ),
            "airport_and_late_bank": (
                "No Sea-Tac arrival wave verified in current snapshot (0 flights loaded). "
                "Do not stage at the FIFO lot without pulling a fresh FlightAware forecast."
            ),
            "tactical_watchouts": (
                f"{len(train_stations or [])} Sound Transit stations within 5 mi have live arrivals. "
                "Do not deadhead on unverified baselines."
            ),
        }

    airport_line = (
        f"Sea-Tac forecast ~{fa_total_planes} arriving flights over 6h"
        + (f" (Peak forecast arrivals: {fa_peak}; Uber FIFO queue wait unknown). " if fa_peak else " (Uber FIFO queue wait unknown). ")
        + f"Late window: {s6.get('zone_label', origin_label)} ({s6.get('primary_trigger', 'hold')})."
        if fa_total_planes > 0
        else f"Sea-Tac forecast not active (0 flights loaded). Late window: {s6.get('zone_label', origin_label)} ({s6.get('primary_trigger', 'hold')})."
    )
    headline_tail = f" · Peak arrivals {fa_peak}" if (fa_total_planes > 0 and fa_peak) else ""
    s1_has_live = bool(s1.get("hot_venues") or s1.get("events") or int(s1.get("flight_arrivals") or 0) > 0)
    s1_basis = str(s1.get("recommendation_basis") or "")
    s1_has_any_stop_evidence = (
        s1_has_live
        or (s1.get("expected_net_per_hour") is not None and int(s1.get("sample_trips") or 0) > 0)
        or s1_basis in {"positioning_heuristic", "positioned_pickup_center"}
    )
    s1_trigger_str = str(s1.get("primary_trigger") or "")
    s1_lacks_evidence = (not s1_has_any_stop_evidence) or ("Insufficient live or historical evidence" in s1_trigger_str)
    if s1_unreachable:
        s1_action = (
            f"Stay in {origin_label} ({s1_zone_label} is ~{s1_drive} min away and the "
            f"{s1.get('window_label', 'current')} window ends before arrival)"
        )
        headline_lead = origin_label
    elif s1_basis == "positioning_heuristic":
        dest_lbl = str(s1.get("destination_label") or s1_zone_label)
        s1_action = f"Position near {dest_lbl} (~{s1_drive} min drive; Positioning suggestion · live demand unknown)"
        headline_lead = f"Position near {dest_lbl}"
    elif s1_basis == "positioned_pickup_center":
        dest_lbl = str(s1.get("destination_label") or s1_zone_label)
        s1_action = f"Wait at {dest_lbl} (bounded 15m wait · current demand unverified)"
        headline_lead = f"Wait at {dest_lbl}"
    elif s1_is_remote and s1_lacks_evidence:
        s1_action = f"Hold in {origin_label}"
        headline_lead = origin_label
    elif s1_is_remote:
        if s1.get("navigation_available") and s1_has_live:
            s1_action = (
                f"Move from {origin_label} (~{s1_drive} min drive) to stage at "
                f"{s1.get('staging_spot', s1_zone_label)} in {s1_zone_label}"
            )
        else:
            s1_action = f"Move from {origin_label} to {s1_zone_label} (~{s1_drive} min drive)"
        headline_lead = f"{origin_label} → {s1_zone_label}"
    elif s1.get("navigation_available") and s1_has_live:
        s1_action = f"Stage at {s1.get('staging_spot', origin_label)} in {s1_zone_label}"
        headline_lead = s1_zone_label
    else:
        s1_action = f"Hold in {s1_zone_label}"
        headline_lead = s1_zone_label
    s2_spot_prefix = f"{s2.get('staging_spot', '')}, " if s2.get("navigation_available") else ""
    s2_win = str(s2.get("window_label") or "")
    s3_win = str(s3.get("window_label") or "")
    s2_start = re.split(r"\s*[–-]\s*", s2_win)[0].strip() if s2_win else ""
    s3_end = re.split(r"\s*[–-]\s*", s3_win)[-1].strip() if s3_win else ""
    win_sep = " – " if "–" in s2_win else " - "
    pivot_window = f"{s2_start}{win_sep}{s3_end}" if (s2_start and s3_end) else s2_win
    return {
        "headline": f"{headline_lead} → {s2.get('zone_label', origin_label)}{headline_tail}",
        "immediate_move": (
            f"[{s1.get('window_label', 'Now')}] {s1_action} "
            f"({_format_stop_rate(s1)}). {s1.get('primary_trigger', '')}."
        ),
        "mid_shift_pivot": (
            f"[{pivot_window}] "
            f"{'Stay in' if s2.get('zone') == s1.get('zone') else 'Consider'} {s2.get('zone_label', origin_label)} "
            f"({s2_spot_prefix}{_format_stop_rate(s2)}): {s2.get('primary_trigger', '')}."
        ),
        "airport_and_late_bank": airport_line,
        "tactical_watchouts": (
            f"{len(train_stations or [])} Sound Transit Link stations within 5 mi have live train telemetry. "
            f"Navigation stays gated to approved curbs."
        ),
    }


def _validate_llm_action_plan(
    parsed: dict,
    stops: list[dict],
    fa_total_planes: int,
    top_hotspots: list[dict] | None = None,
    fa_forecast: dict | None = None,
    train_stations: list[dict] | None = None,
) -> bool:
    """Validate structured stop-ID selection (H01). Reject all free-form prose overrides."""
    if not isinstance(parsed, dict) or not stops:
        return False

    allowed_selection_keys = {"mode", "immediate_stop_id", "pivot_stop_id", "late_stop_id"}
    if not parsed or not set(parsed.keys()).issubset(allowed_selection_keys):
        return False
    if parsed.get("mode") != "structured_selection":
        return False
    if "immediate_stop_id" not in parsed or "pivot_stop_id" not in parsed:
        return False

    catalog = course_fact_catalog(
        stops,
        fa_total_planes,
        top_hotspots=top_hotspots,
        fa_forecast=fa_forecast,
        train_stations=train_stations,
    )
    if not catalog["has_any_evidence"] and fa_total_planes <= 0:
        return False

    return (
        render_bound_action_plan(
            parsed,
            stops,
            fa_total_planes,
            top_hotspots=top_hotspots,
            fa_forecast=fa_forecast,
            train_stations=train_stations,
        )
        is not None
    )


def _generate_formatted_action_plan(
    *,
    origin_label: str,
    stops: list[dict],
    top_hotspots: list[dict],
    fa_forecast: dict,
    fa_total_planes: int,
    train_stations: list[dict],
    run_live_llm: bool,
) -> tuple[dict, str, str, int]:
    """Build a structured 4-step Tactical Action Plan rendered exclusively on the server from bound stop records."""
    now_utc = datetime.now(UTC)
    default_selection = {
        "mode": "structured_selection",
        "immediate_stop_id": "stop_0",
        "pivot_stop_id": "stop_1" if len(stops) > 1 else "stop_0",
        "late_stop_id": f"stop_{max(0, len(stops) - 1)}",
    }
    rendered_default = render_bound_action_plan(
        default_selection,
        stops,
        fa_total_planes,
        top_hotspots=top_hotspots,
        fa_forecast=fa_forecast,
        train_stations=train_stations,
        origin_label=origin_label,
    )
    if rendered_default is not None:
        structured_plan = dict(rendered_default)
    else:
        structured_plan = {
            "headline": f"Hold in {origin_label} · Insufficient evidence to relocate",
            "immediate_move": f"[Now] Hold in {origin_label} (earnings unknown). No active live catalyst.",
            "mid_shift_pivot": "No verified mid-shift demand wave in current snapshot. Recheck live feeds before moving.",
            "airport_and_late_bank": (
                "No Sea-Tac arrival wave verified in current snapshot (0 flights loaded). "
                "Do not stage at the FIFO lot without pulling a fresh FlightAware forecast."
            ),
            "tactical_watchouts": (
                f"{len(train_stations)} Sound Transit stations within 5 mi have live arrivals. "
                "Do not deadhead on unverified baselines."
            ),
        }

    fa_peak = str(fa_forecast.get("best_hour_label") or "").strip()
    fa_lot = str(fa_forecast.get("best_lot_arrival_time") or "").strip()

    signature = _plan_signature(origin_label, stops, fa_total_planes)
    cache_path = cache_dir() / "last_shift_course_plan.json"
    if not run_live_llm:
        cached = _read_json(cache_path)
        cached_sel = cached.get("selection") if isinstance(cached, dict) else None
        if (
            isinstance(cached, dict)
            and cached.get("signature") == signature
            and cached.get("origin_label") == origin_label
            and _is_fresh_iso(cached.get("saved_at"), now_utc, max_minutes=30.0)
            and isinstance(cached_sel, dict)
            and _validate_llm_action_plan(
                cached_sel,
                stops,
                fa_total_planes,
                top_hotspots=top_hotspots,
                fa_forecast=fa_forecast,
                train_stations=train_stations,
            )
        ):
            ap = render_bound_action_plan(
                cached_sel,
                stops,
                fa_total_planes,
                top_hotspots=top_hotspots,
                fa_forecast=fa_forecast,
                train_stations=train_stations,
                origin_label=origin_label,
            )
            if ap is not None:
                spoken = (
                    f"{ap.get('headline')}. Immediate move: {ap.get('immediate_move')} "
                    f"Mid-shift pivot: {ap.get('mid_shift_pivot')} "
                    f"Airport and late bank: {ap.get('airport_and_late_bank')}"
                )
                return ap, spoken, str(cached.get("model") or "RideEdge Tactical Formatter"), 0

    llm_start = time.perf_counter()
    model_used = "RideEdge Tactical Formatter"
    if run_live_llm:
        try:
            endpoint, alias = local_runtime.settings()
            with local_runtime.session(endpoint, alias):
                selection_schema = build_action_plan_selection_schema(stops)
                dossier = {
                    "origin": origin_label,
                    "available_stop_ids": [f"stop_{idx}" for idx in range(len(stops))],
                    "stops": [
                        {
                            "stop_id": f"stop_{idx}",
                            "hour_index": s.get("hour_index", idx),
                            "window_label": s.get("window_label", ""),
                            "zone": s.get("zone", ""),
                            "zone_label": s.get("zone_label", ""),
                            "navigation_available": bool(s.get("navigation_available")),
                            "staging_spot": s.get("staging_spot", "") if s.get("navigation_available") else "",
                            "rate_summary": _format_stop_rate(s),
                            "primary_trigger": s.get("primary_trigger", ""),
                        }
                        for idx, s in enumerate(stops)
                    ],
                    "top_besttime_hotspots_now": [
                        {
                            "hotspot_id": f"hotspot_{idx}",
                            "name": h.get("name", ""),
                            "area": h.get("area", ""),
                            "busyness_pct": h.get("busyness_pct"),
                            "next_hour_pct": h.get("next_hour_pct"),
                        }
                        for idx, h in enumerate(top_hotspots[:6])
                    ],
                    "seatac_6h_flightaware": {
                        "total_planes_6h": fa_total_planes,
                        "peak_hour": fa_peak,
                        "fifo_lot_target": fa_lot,
                    },
                }
                body = json.dumps({
                    "model": alias,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are RideEdge Shift Commander. Select the stop IDs from the supplied dossier "
                                "matching the strict selection schema. The server will render all operational facts."
                            ),
                        },
                        {"role": "user", "content": json.dumps(dossier)},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 160,
                    "response_format": {"type": "json_object", "schema": selection_schema},
                }).encode("utf-8")
                req = Request(
                    endpoint,
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
                with urlopen(req, timeout=8.0) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                returned_model = str(payload.get("model") or "").strip()
                if not returned_model or returned_model.casefold() != alias.strip().casefold():
                    raise FeedError(f"Unexpected or missing model {returned_model!r}")
                raw_content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                parsed = json.loads(raw_content)
                if _validate_llm_action_plan(
                    parsed,
                    stops,
                    fa_total_planes,
                    top_hotspots=top_hotspots,
                    fa_forecast=fa_forecast,
                    train_stations=train_stations,
                ):
                    rendered = render_bound_action_plan(
                        parsed,
                        stops,
                        fa_total_planes,
                        top_hotspots=top_hotspots,
                        fa_forecast=fa_forecast,
                        train_stations=train_stations,
                        origin_label=origin_label,
                    )
                    if rendered is not None:
                        for k in ("headline", "immediate_move", "mid_shift_pivot", "airport_and_late_bank", "tactical_watchouts"):
                            structured_plan[k] = str(rendered[k]).strip()
                        model_used = returned_model
                        save(
                            cache_path,
                            {
                                "signature": signature,
                                "origin_label": origin_label,
                                "selection": parsed,
                                "action_plan": structured_plan,
                                "model": model_used,
                                "saved_at": now_utc.isoformat(),
                            },
                        )
        except Exception:
            pass

    llm_ms = int((time.perf_counter() - llm_start) * 1000) if run_live_llm else 0
    spoken_briefing = (
        f"🎯 {structured_plan['headline']}\n\n"
        f"⚡ 1. IMMEDIATE MOVE (NOW):\n{structured_plan['immediate_move']}\n\n"
        f"🚶 2. MID-SHIFT PIVOT (SPILLOUTS):\n{structured_plan['mid_shift_pivot']}\n\n"
        f"✈ 3. AIRPORT & LATE SURGE:\n{structured_plan['airport_and_late_bank']}\n\n"
        f"⚠️ 4. TACTICAL WATCHOUTS:\n{structured_plan['tactical_watchouts']}"
    )
    return structured_plan, spoken_briefing, model_used, llm_ms
