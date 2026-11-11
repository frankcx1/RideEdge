"""Beast-side feed warmer. Collectors do not see GPS.

Runs inside the API process so a parked browser is not required for NWS, sports,
Places hours, or the home traffic matrix to stay fresh. AI narration runs only
when a brief is requested; cloud research/watch are disabled in Qwen mode.
AeroAPI stays off this loop entirely: HERE at
SEA is the only spend.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime, timedelta

from farol.adapters import ADAPTERS, LLM_ADAPTERS, ON_DEMAND_ADAPTERS, mock_feeds_active
from farol.adapters.base import FeedStatus
from farol.awareness import PACIFIC, write_snapshot

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()
_state: dict = {
    "running": False,
    "last_run_at": None,
    "last_detail": "not started",
    "feed_count": 0,
}


def enabled() -> bool:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    if os.getenv("FAROL_COLLECT", "1") != "1":
        return False
    return not mock_feeds_active()


def status() -> dict:
    with _lock:
        return dict(_state)


def interval_seconds(now: datetime | None = None) -> float:
    """workstation is Pacific. Tests pass an aware datetime; hour is taken as-is."""
    local = now or datetime.now().astimezone()
    hour = local.hour
    if 16 <= hour or hour < 3:
        return 15 * 60
    if local.weekday() in {1, 3} and 4 <= hour < 10:
        return 15 * 60
    return 60 * 60


def _refresh_once(now: datetime | None = None, *, include_flightaware: bool = False) -> list[dict]:
    current = (now or datetime.now(PACIFIC)).astimezone(PACIFIC)
    window_end = (current.astimezone(UTC) + timedelta(hours=12)).astimezone(PACIFIC)
    results: list[dict] = []
    collected_signals = []
    for adapter in ADAPTERS:
        name = getattr(adapter, "NAME", "")
        if name in LLM_ADAPTERS:
            continue
        if name in ON_DEMAND_ADAPTERS and not include_flightaware:
            continue
        try:
            if name in ON_DEMAND_ADAPTERS:
                signals, feed_status = adapter.fetch(current, window_end, demand=True)
            else:
                signals, feed_status = adapter.fetch(current, window_end)
            collected_signals.extend(signals)
        except Exception as error:  # noqa: BLE001
            feed_status = FeedStatus(
                name or "adapter",
                "error",
                getattr(adapter, "SOURCE", "?"),
                None,
                0,
                repr(error)[:300],
            )
        results.append(feed_status.public())
    try:
        from farol.adapters import routes

        _, feed_status = routes.fetch(current, window_end)
        results.append(feed_status.public())
    except Exception as error:  # noqa: BLE001
        results.append(
            FeedStatus("google_routes_traffic", "error", "google:routes", None, 0, repr(error)[:300]).public()
        )
    try:
        write_snapshot(collected_signals, results, current, window_end)
        try:
            from farol.awareness import saved_besttime
            from farol.besttime_live import _inject_besttime_signals_into_snapshot

            bt_saved = saved_besttime(current)
            bt_venues = (bt_saved or {}).get("venues") or []
            if bt_venues:
                _inject_besttime_signals_into_snapshot(bt_venues, current)
        except Exception:
            pass
    except (OSError, ValueError):
        results.append(FeedStatus("area_snapshot", "error", "local", None, 0,
                                  "Could not save area context; previous snapshot retained").public())
    with _lock:
        _state["last_run_at"] = current.isoformat()
        _state["feed_count"] = len(results)
        errors = [item["adapter"] for item in results if item.get("mode") == "error"]
        _state["last_detail"] = (
            f"{len(results)} feeds warmed" + (f"; errors: {', '.join(errors)}" if errors else "")
        )
    return results


def refresh_once(now: datetime | None = None, *, include_flightaware: bool = False) -> list[dict]:
    from farol.usage import current_run
    counts = {}
    token = current_run.set(counts)
    began = time.monotonic()
    with _lock:
        _state["collecting"] = True
        _state["started_at"] = datetime.now(UTC).isoformat()
    try:
        try:
            return _refresh_once(now, include_flightaware=include_flightaware)
        except TypeError:
            return _refresh_once(now)
    finally:
        current_run.reset(token)
        with _lock:
            _state["collecting"] = False
            _state["completed_at"] = datetime.now(UTC).isoformat()
            _state["duration_seconds"] = round(time.monotonic() - began, 2)
            _state["runs"] = _state.get("runs", 0) + 1
            _state["last_run_usage"] = {"providers":counts, "scope":"Shared adapter HTTP client, one collector run; excludes separate manual trials and model calls.",
                                      "completed_at":datetime.now(UTC).isoformat(), "dollar_cost":"unknown; request counts are not billed credits"}


FEED_CATALOG: dict[str, tuple[str, str]] = {
    "wsf_colman_ferries": ("WSDOT Ferries (Colman Dock)", "Live Transit & Aviation"),
    "amtrak_king_street": ("Amtrak Trains (King St Station)", "Live Transit & Aviation"),
    "flightaware_sea": ("FlightAware AeroAPI (KSEA)", "Live Transit & Aviation"),
    "onebusaway_transit": ("Sound Transit Link (OneBusAway)", "Live Transit & Aviation"),
    "sea_fifo": ("Sea-Tac Arrival Banks (FIFO)", "Live Transit & Aviation"),
    "cruise_schedule": ("Port of Seattle Cruise Schedule", "Live Transit & Aviation"),
    "ticketmaster_events": ("Ticketmaster Discovery v2", "Events & Sports"),
    "seatgeek_events": ("SeatGeek Live Events", "Events & Sports"),
    "espn_seattle": ("ESPN Seattle (Seahawks/Sounders/UW)", "Events & Sports"),
    "mlb_schedule": ("MLB Schedule (Mariners)", "Events & Sports"),
    "nhl_schedule": ("NHL Schedule (Kraken)", "Events & Sports"),
    "seattle_special_events": ("Seattle Special Event Permits", "Events & Sports"),
    "seattle_community_events": ("Seattle & Eastside Community Calendars", "Events & Sports"),
    "google_places_closing": ("Google Places Nightlife Hours", "Venues & Foot Traffic"),
    "besttime_busyness": ("BestTime Venue Foot Traffic", "Venues & Foot Traffic"),
    "venue_hours": ("Eastside & Seattle Bar Harvests", "Venues & Foot Traffic"),
    "nws_live_observation": ("NWS Live Station (KBFI Rain/Wind)", "Weather & Roads"),
    "nws_hourly": ("NWS Hourly Weather Forecast", "Weather & Roads"),
    "wsdot_traffic": ("WSDOT Highway & Bridge Alerts", "Weather & Roads"),
    "google_routes_traffic": ("Google Routes Traffic Matrix", "Weather & Roads"),
    "situational_demand_waves": ("Situational Waves (Link/Hospitals/RTO)", "Standing & AI"),
    "eastside_doctrine": ("Eastside Nightlife Doctrine", "Standing & AI"),
    "openclaw_drop": ("OpenClaw Drop Folder", "Standing & AI"),
}


def feed_health_view(now: datetime | None = None) -> dict:
    """Return a stoplight health summary across all 23 live, cached, and standing feeds."""
    import json
    from farol.adapters import flightaware
    from farol.adapters.base import cache_dir, read_cache
    from farol.awareness import age_minutes, saved_besttime

    current = (now or datetime.now(PACIFIC)).astimezone(PACIFIC)
    snap_path = cache_dir() / "awareness_snapshot.json"
    try:
        snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snapshot = {}

    raw_feeds = {str(f.get("adapter")): dict(f) for f in snapshot.get("feeds", []) if f.get("adapter")}

    # Synthesize FlightAware AeroAPI entry from cache + key check
    if "flightaware_sea" not in raw_feeds:
        fa_key = bool(os.getenv("FLIGHTAWARE_API_KEY", "").strip())
        fa_cached = read_cache("flightaware_ksea_arrivals_p2")
        fa_age = age_minutes(fa_cached.get("fetched_at"), current) if isinstance(fa_cached, dict) else None
        if not fa_key:
            raw_feeds["flightaware_sea"] = {
                "adapter": "flightaware_sea",
                "mode": "needs_key",
                "source": flightaware.SOURCE,
                "fetched_at": None,
                "signal_count": 0,
                "detail": "Set FLIGHTAWARE_API_KEY in .env",
            }
        elif (
            isinstance(fa_cached, dict)
            and isinstance(fa_cached.get("payload"), dict)
            and fa_age is not None and -5 <= fa_age <= 240
        ):
            arrivals = (fa_cached.get("payload") or {}).get("arrivals") or []
            fa_sigs = flightaware.parse(
                fa_cached["payload"],
                current - timedelta(hours=2),
                current + timedelta(hours=6),
                fetched_at=str(fa_cached.get("fetched_at") or current.isoformat()),
                page_limit=flightaware.DEMAND_PAGES,
            )
            raw_feeds["flightaware_sea"] = {
                "adapter": "flightaware_sea",
                "mode": "cache",
                "source": flightaware.SOURCE,
                "fetched_at": fa_cached.get("fetched_at"),
                "signal_count": len(fa_sigs),
                "detail": f"{len(fa_sigs)} wave(s) from {len(arrivals)} KSEA arrivals (AeroAPI cached)",
            }
        else:
            raw_feeds["flightaware_sea"] = {
                "adapter": "flightaware_sea",
                "mode": "on_demand",
                "source": flightaware.SOURCE,
                "fetched_at": None,
                "signal_count": 0,
                "detail": "Key configured · explicitly refresh the SeaTac report to request arrivals",
            }

    # The dedicated report is fetched separately from the collector. Surface its
    # retained records without spending on a health/detail read.
    airport_report = flightaware.seatac_6h_forecast(now=current, pull=False)
    if airport_report.get("hours"):
        usable_hours = [h for h in airport_report["hours"] if h.get("usable")]
        retained_count = sum(h.get("sampled_flights") or 0 for h in airport_report["hours"])
        raw_feeds["flightaware_sea"] = {
            "adapter": "flightaware_sea", "mode": "cache" if usable_hours else "stale_cache",
            "source": flightaware.SCHEDULED_ARRIVALS_URL,
            "fetched_at": min(h["fetched_at"] for h in usable_hours) if usable_hours else airport_report.get("fetched_at"),
            "signal_count": retained_count, "count_unit": "retained flight records",
            "detail": f"{len(usable_hours)} usable hourly windows; one page per window. Missing pages may change the apparent peak.",
        }

    # Synthesize BestTime foot-traffic status from key check + saved pilot report
    bt_priv = bool(os.getenv("BESTTIME_API_KEY_PRIVATE", "").strip())
    bt_report = saved_besttime(current)
    bt_venues = len((bt_report or {}).get("venues") or [])
    bt_finished = (bt_report or {}).get("finished_at")
    bt_age = age_minutes(bt_finished, current) if bt_finished else None
    from farol.besttime_control import status as besttime_network_status
    bt_network = besttime_network_status()
    raw_feeds["besttime_busyness"] = {
        "adapter": "besttime_busyness",
        "mode": (
            ("live" if (bt_age is not None and bt_age <= 90.0 and bt_network["enabled"]) else "cache")
            if (bt_priv and bt_venues > 0)
            else ("needs_key" if not bt_priv else "on_demand")
        ),
        "source": "besttime.app/api/v1",
        "fetched_at": bt_finished,
        "signal_count": bt_venues,
        "detail": (
            f"{bt_network['detail']} · {bt_venues} venues cached"
            if bt_priv
            else "Set BESTTIME_API_KEY_PRIVATE in .env"
        ),
    }

    items: list[dict] = []
    standby_static = {"cruise_schedule", "openclaw_drop"}
    import re

    # Maintain deterministic order from FEED_CATALOG, then any extra adapters
    ordered_keys = list(FEED_CATALOG.keys()) + [k for k in raw_feeds if k not in FEED_CATALOG]
    for key in ordered_keys:
        feed = raw_feeds.get(key)
        if not feed:
            continue
        label, category = FEED_CATALOG.get(key, (key.replace("_", " ").title(), "Other"))
        mode = str(feed.get("mode") or "unknown")
        sig_count = int(feed.get("signal_count") or 0)
        fetched_at = feed.get("fetched_at")
        age = age_minutes(fetched_at, current) if fetched_at else None
        detail = str(feed.get("detail") or "")

        if mode in {"error", "needs_key"}:
            stoplight = "red"
        elif mode in {"stale_cache", "warming", "on_demand", "unknown", "missing", "initializing"} or (
            key in standby_static and sig_count == 0
        ):
            stoplight = "amber"
        elif mode in {"live", "cache"}:
            # R18: Enforce read-time freshness limits by category so stalled feeds do not stay green
            max_fresh_min = (
                720.0
                if key == "google_places_closing"
                else (
                    240.0
                    if key == "besttime_busyness"
                    else (
                        60.0
                        if category in {"Weather & Roads", "Transit, Rail & Ferries", "Aviation & Surge", "Live Transit & Aviation"}
                        else 180.0
                    )
                )
            )
            if age is None or age < -5.0:
                stoplight = "amber"
            elif age > max_fresh_min * 4:
                stoplight = "red"
                mode = "stale_cache"
            elif age > max_fresh_min:
                stoplight = "amber"
                mode = "stale_cache"
            else:
                stoplight = "green"
        elif mode in {"standing", "static", "fixture"} and sig_count > 0:
            stoplight = "green"
        else:
            stoplight = "amber"

        enabled_src = mode not in {"needs_key", "disabled"}
        healthy_src = enabled_src and stoplight == "green"
        plain_summary = detail
        if key == "ticketmaster_events":
            m_tm = re.search(r"(\d+)\s+mapped\s+exits\s+from\s+(\d+)\s+unique\s+TM\s+events", detail)
            if m_tm:
                plain_summary = f"{m_tm.group(2)} events · {m_tm.group(1)} mapped departure signals"

        items.append({
            "adapter": key,
            "label": label,
            "category": category,
            "stoplight": stoplight,
            "mode": mode,
            "enabled": enabled_src,
            "healthy": healthy_src,
            "signal_count": sig_count,
            "count_unit": feed.get("count_unit", "signals"),
            "fetched_at": fetched_at,
            "age_minutes": age,
            "detail": detail,
            "plain_summary": plain_summary,
        })

    green_count = sum(1 for item in items if item["stoplight"] == "green")
    amber_count = sum(1 for item in items if item["stoplight"] == "amber")
    red_count = sum(1 for item in items if item["stoplight"] == "red")
    enabled_count = sum(1 for item in items if item["enabled"])
    disabled_count = sum(1 for item in items if not item["enabled"])
    healthy_count = sum(1 for item in items if item["healthy"])
    degraded_count = sum(1 for item in items if item["enabled"] and not item["healthy"])
    overall = "red" if red_count > 0 else ("green" if green_count > 0 else "amber")
    snap_age = age_minutes(snapshot.get("collected_at"), current) if snapshot.get("collected_at") else None
    snapshot_state = (
        "missing"
        if not snapshot.get("feeds")
        else ("stale" if (snap_age is None or snap_age > 180.0) else "ready")
    )
    snapshot_id = str(snapshot.get("snapshot_id") or f"snap-{snapshot.get('collected_at') or 'none'}")

    return {
        "as_of": current.isoformat(),
        "collected_at": snapshot.get("collected_at"),
        "snapshot_id": snapshot_id,
        "snapshot_age_minutes": snap_age,
        "snapshot_state": snapshot_state,
        "service_health_note": "Shows API source availability and freshness — not whether sources agree with a recommendation.",
        "overall_stoplight": overall,
        "total_count": len(items),
        "enabled_count": enabled_count,
        "disabled_count": disabled_count,
        "healthy_count": healthy_count,
        "degraded_count": degraded_count,
        "green_count": green_count,
        "amber_count": amber_count,
        "red_count": red_count,
        "feeds": items,
    }


ADAPTER_SOURCE_PREFIXES: dict[str, tuple[str, ...]] = {
    "wsf_colman_ferries": ("wsdot:Ferries",),
    "amtrak_king_street": ("amtraker:", "amtrak:"),
    "flightaware_sea": ("flightaware:",),
    "onebusaway_transit": ("onebusaway:",),
    "sea_fifo": ("portseattle:sea", "farol:sea_fifo"),
    "cruise_schedule": ("portseattle:cruise", "fixtures/cruise"),
    "ticketmaster_events": ("ticketmaster:",),
    "seatgeek_events": ("seatgeek:",),
    "espn_seattle": ("espn:",),
    "mlb_schedule": ("mlb:",),
    "nhl_schedule": ("nhl:",),
    "seattle_special_events": ("seattle:data.seattle.gov", "seattle:special_events"),
    "seattle_community_events": ("community:",),
    "google_places_closing": ("google:places",),
    "besttime_busyness": ("besttime",),
    "venue_hours": ("fixtures/venues", "farol:venues"),
    "nws_live_observation": ("nws:stations", "weather.gov/stations"),
    "nws_hourly": ("nws:gridpoints", "api.weather.gov"),
    "wsdot_traffic": ("wsdot:HighwayAlerts", "wsdot:traffic"),
    "google_routes_traffic": ("google:routes",),
    "situational_demand_waves": ("farol:situational",),
    "eastside_doctrine": ("farol:eastside", "farol:doctrine"),
    "openclaw_drop": ("openclaw:",),
}

ADAPTER_DECISION_ROLES: dict[str, tuple[str, str]] = {
    "wsf_colman_ferries": ("arrival_wave_opportunity", "60m live / 240m cache"),
    "amtrak_king_street": ("arrival_wave_opportunity", "60m live / 240m cache"),
    "flightaware_sea": ("airport_arrival_forecast_and_lot_context", "60m live / 240m cache"),
    "onebusaway_transit": ("transit_disruption_and_station_telemetry", "10m live telemetry / 60m health"),
    "sea_fifo": ("airport_fifo_bank_schedule_context", "180m standing schedule"),
    "cruise_schedule": ("maritime_turnaround_opportunity", "180m seasonal schedule"),
    "ticketmaster_events": ("reachable_event_exit_window", "180m snapshot / event exit window"),
    "seatgeek_events": ("reachable_event_exit_window", "180m snapshot / event exit window"),
    "espn_seattle": ("reachable_sports_exit_window", "180m snapshot / game exit window"),
    "mlb_schedule": ("reachable_sports_exit_window", "180m snapshot / game exit window"),
    "nhl_schedule": ("reachable_sports_exit_window", "180m snapshot / game exit window"),
    "seattle_special_events": ("reachable_special_event_window", "180m snapshot / permit window"),
    "seattle_community_events": ("reachable_community_event_window", "180m snapshot / event window"),
    "google_places_closing": ("venue_closing_spillout_window", "180m snapshot / closing window"),
    "besttime_busyness": ("live_vs_typical_venue_activity", "90m live / 14d weekly pattern"),
    "venue_hours": ("bar_harvest_closing_window", "180m standing schedule"),
    "nws_live_observation": ("weather_demand_and_road_context", "60m live observation"),
    "nws_hourly": ("weather_forecast_context", "60m hourly forecast"),
    "wsdot_traffic": ("travel_burden_and_bridge_closure_penalty", "60m live highway alerts"),
    "google_routes_traffic": ("live_travel_time_and_deadhead_burden", "60m live route matrix"),
    "situational_demand_waves": ("standing_shift_and_commute_wave", "180m standing schedule"),
    "eastside_doctrine": ("convergence_and_deadhead_penalty_guardrail", "180m standing doctrine"),
    "openclaw_drop": ("operator_manual_drop_override", "180m drop file"),
}


def build_source_coverage_inventory(
    *,
    now: datetime | None = None,
    chosen_zone: str | None = None,
    chosen_action: str | None = None,
    chosen_basis: str | None = None,
    active_signal_sources: set[str] | None = None,
    affected_zones_by_adapter: dict[str, list[str]] | None = None,
    live_route_zones: set[str] | None = None,
    besttime_live_zones: set[str] | None = None,
    besttime_typical_zones: set[str] | None = None,
    flightaware_planes: int = 0,
    health: dict | None = None,
) -> list[dict]:
    """Build a source-by-source coverage inventory across all 23 configured adapters."""
    import json
    from farol.adapters.base import cache_dir

    current = (now or datetime.now(PACIFIC)).astimezone(PACIFIC)
    health_data = health if isinstance(health, dict) and health.get("feeds") else feed_health_view(current)
    feeds_by_key = {str(f.get("adapter")): f for f in (health_data.get("feeds") or []) if isinstance(f, dict)}
    snap_path = cache_dir() / "awareness_snapshot.json"
    try:
        snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snapshot = {}
    snap_signals = snapshot.get("signals") or []

    rows: list[dict] = []
    for key, (label, category) in FEED_CATALOG.items():
        f = feeds_by_key.get(key) or {}
        mode = str(f.get("mode") or "unknown")
        enabled = bool(f.get("enabled", mode not in {"needs_key", "disabled"}))
        configured = mode != "needs_key"
        healthy = bool(f.get("healthy", False))
        sig_count = int(f.get("signal_count") or 0)
        fetched_at = f.get("fetched_at")
        age = f.get("age_minutes")
        role, freshness_rule = ADAPTER_DECISION_ROLES.get(key, ("decision_context", "180m snapshot"))

        prefixes = ADAPTER_SOURCE_PREFIXES.get(key, ())
        matched_zones: set[str] = set((affected_zones_by_adapter or {}).get(key) or [])
        context_only_all = False
        routine_transit_only = False
        if prefixes and snap_signals:
            adapter_sigs = [
                s for s in snap_signals
                if isinstance(s, dict)
                and any(str(s.get("source") or "").startswith(pfx) for pfx in prefixes)
            ]
            for s in adapter_sigs:
                z = str(s.get("zone") or "")
                if z:
                    matched_zones.add(z)
            if adapter_sigs and all(bool((s.get("details") or {}).get("context_only")) for s in adapter_sigs):
                context_only_all = True
            if key in {"onebusaway_transit", "wsf_colman_ferries", "amtrak_king_street"} and adapter_sigs:
                if all(str(s.get("kind") or "") in {"transit_arrival_wave", "ferry_arrival", "transit_arrival"} for s in adapter_sigs):
                    routine_transit_only = True

        if key == "google_routes_traffic" and live_route_zones:
            matched_zones.update(live_route_zones)
        if key == "besttime_busyness":
            if besttime_live_zones:
                matched_zones.update(besttime_live_zones)
            if besttime_typical_zones:
                matched_zones.update(besttime_typical_zones)
        if key == "flightaware_sea" and flightaware_planes > 0:
            matched_zones.add("sea_airport")

        candidates_affected = sorted(z for z in matched_zones if z)
        influenced = False
        exclusion_reason: str | None = None

        if not configured:
            exclusion_reason = "not_configured_needs_key"
        elif not enabled:
            exclusion_reason = "adapter_disabled"
        elif mode == "stale_cache":
            exclusion_reason = "stale_cache_exceeded_freshness"
        elif key == "google_routes_traffic":
            if live_route_zones:
                influenced = True
            elif sig_count > 0:
                influenced = True
            else:
                exclusion_reason = "no_live_route_matrix_for_origin"
        elif key == "besttime_busyness":
            if besttime_live_zones and (not chosen_zone or chosen_zone in besttime_live_zones):
                influenced = True
            elif besttime_typical_zones:
                exclusion_reason = "weekly_typical_pattern_context_only_not_live_demand"
            else:
                exclusion_reason = "no_venues_above_busyness_threshold_in_window"
        elif key in {"flightaware_sea", "sea_fifo"}:
            if chosen_zone == "sea_airport" and (flightaware_planes > 0 or sig_count > 0):
                influenced = True
            elif flightaware_planes > 0 or sig_count > 0:
                exclusion_reason = "airport_fifo_isolated_from_street_board_queue_wait_unknown"
            else:
                exclusion_reason = "zero_arrivals_in_active_window"
        elif sig_count <= 0 and not candidates_affected:
            exclusion_reason = "zero_signals_in_active_window"
        elif context_only_all or key in {"nws_live_observation", "nws_hourly", "eastside_doctrine"}:
            if key == "eastside_doctrine":
                exclusion_reason = "doctrine_guardrail_context_only_not_positive_demand"
            else:
                exclusion_reason = "weather_context_only_no_rain_surge_multiplier_active"
        elif routine_transit_only and chosen_action != "MOVE":
            exclusion_reason = "routine_schedule_inventory_excluded_from_street_move"
        else:
            if active_signal_sources and any(
                any(src.startswith(pfx) for pfx in prefixes) for src in active_signal_sources
            ):
                influenced = True
            elif chosen_zone and chosen_zone in candidates_affected and chosen_basis in {"live_opportunity", "scheduled_catalyst"}:
                influenced = True
            elif candidates_affected:
                exclusion_reason = "evaluated_below_move_threshold_or_outside_drive_limit"
            else:
                exclusion_reason = "no_reachable_candidate_in_current_window"

        rows.append({
            "adapter": key,
            "label": label,
            "category": category,
            "enabled": enabled,
            "configured": configured,
            "healthy": healthy,
            "mode": mode,
            "last_fetched_at": fetched_at,
            "age_minutes": age,
            "freshness_rule": freshness_rule,
            "normalized_signal_count": sig_count,
            "role_in_decision": role,
            "influenced_decision": influenced,
            "candidates_affected": candidates_affected,
            "exclusion_reason": None if influenced else (exclusion_reason or "not_used_in_selected_action"),
        })
    return rows


def feed_detail_view(adapter_key: str, now: datetime | None = None) -> dict:
    """Return the retained snapshot records behind a single API source row without making fresh provider calls."""
    import json
    import re
    from farol.adapters import amtrak_sea, flightaware, onebusaway, ticketmaster, wsf_ferries
    from farol.adapters.base import cache_dir, read_cache
    from farol.awareness import _safe, age_minutes, saved_besttime
    from farol.zones import load_zones

    current = (now or datetime.now(PACIFIC)).astimezone(PACIFIC)
    health = feed_health_view(current)
    feed_row = next((f for f in health.get("feeds", []) if f.get("adapter") == adapter_key), None)
    if feed_row is None:
        if adapter_key not in FEED_CATALOG:
            raise ValueError(f"Unknown feed adapter: {adapter_key}")
        lbl, cat = FEED_CATALOG[adapter_key]
        feed_row = {
            "adapter": adapter_key,
            "label": lbl,
            "category": cat,
            "stoplight": "amber",
            "mode": "unknown",
            "enabled": True,
            "healthy": False,
            "signal_count": 0,
            "fetched_at": None,
            "age_minutes": None,
            "detail": "Snapshot not yet collected",
            "plain_summary": "Snapshot not yet collected",
        }

    snap_path = cache_dir() / "awareness_snapshot.json"
    try:
        snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snapshot = {}

    snapshot_id = str(snapshot.get("snapshot_id") or health.get("snapshot_id") or "snap-none")
    zones_by_id = load_zones().by_id

    def _zlabel(zid: str | None) -> str:
        if not zid:
            return "Metro wide"
        z = zones_by_id.get(zid)
        return z.label if z else zid.replace("_", " ").title()

    if adapter_key == "ticketmaster_events":
        m_counts = re.search(
            r"(\d+)\s+mapped\s+exits\s+from\s+(\d+)\s+unique\s+TM\s+events",
            str(feed_row.get("detail") or ""),
        )
        expected_signals = int(m_counts.group(1)) if m_counts else int(feed_row.get("signal_count") or 0)
        expected_events = int(m_counts.group(2)) if m_counts else 0
        tm_detail = ticketmaster.load_retained_detail(
            now=current,
            expected_events=expected_events if m_counts else None,
            expected_signals=expected_signals if (m_counts or feed_row.get("signal_count") is not None) else None,
            expected_fetched_at=str(feed_row.get("fetched_at")) if feed_row.get("fetched_at") else None,
            expected_snapshot_id=str(snapshot.get("snapshot_id")) if snapshot.get("snapshot_id") else None,
        )
        if tm_detail is not None and isinstance(tm_detail.get("events"), list):
            events_list = list(tm_detail.get("events") or [])
            signals_list = list(tm_detail.get("signals") or [])
            detail_fetched = tm_detail.get("fetched_at") or feed_row.get("fetched_at")
            detail_age = age_minutes(detail_fetched, current) if detail_fetched else feed_row.get("age_minutes")
            return _safe({
                "adapter": adapter_key,
                "label": feed_row["label"],
                "category": feed_row["category"],
                "kind": "events",
                "snapshot_id": snapshot_id,
                "collected_at": snapshot.get("collected_at"),
                "fetched_at": detail_fetched,
                "query_fetched_at_min": tm_detail.get("query_fetched_at_min"),
                "query_fetched_at_max": tm_detail.get("query_fetched_at_max"),
                "age_minutes": detail_age,
                "mode": feed_row.get("mode"),
                "stoplight": feed_row.get("stoplight"),
                "detail_state": "ready" if events_list else "empty",
                "status_message": (
                    tm_detail.get("summary_plain")
                    if events_list
                    else "0 Ticketmaster events returned in this snapshot window."
                ),
                "summary": feed_row.get("detail"),
                "plain_summary": tm_detail.get("summary_plain") or feed_row.get("plain_summary"),
                "mapping_note": tm_detail.get("mapping_note"),
                "window_start": tm_detail.get("window_start") or snapshot.get("window_start"),
                "window_end": tm_detail.get("window_end") or snapshot.get("window_end"),
                "unique_events_count": len(events_list),
                "mapped_signals_count": len(signals_list),
                "excluded_events_count": int(tm_detail.get("excluded_events_count") or 0),
                "duplicate_collapsed_count": int(tm_detail.get("duplicate_collapsed_count") or 0),
                "multi_query_duplicates": int(tm_detail.get("multi_query_duplicates") or 0),
                "truncated": bool(tm_detail.get("truncated")),
                "queries": tm_detail.get("queries") or [],
                "events": events_list,
                "signals": signals_list,
                "records": events_list,
            })
        # No retained detail file or raw cache found matching current snapshot
        if feed_row.get("mode") == "needs_key":
            d_state = "disabled"
            msg = "Ticketmaster API key is not configured."
        elif expected_events > 0 or expected_signals > 0:
            d_state = "details_not_saved"
            msg = "Retained detail record does not match current snapshot or wasn't saved. Tap Refresh Feeds to capture current event and signal mapping details."
        else:
            d_state = "empty"
            msg = "0 events returned in this snapshot window."
        return _safe({
            "adapter": adapter_key,
            "label": feed_row["label"],
            "category": feed_row["category"],
            "kind": "events",
            "snapshot_id": snapshot_id,
            "collected_at": snapshot.get("collected_at"),
            "fetched_at": feed_row.get("fetched_at"),
            "age_minutes": feed_row.get("age_minutes"),
            "mode": feed_row.get("mode"),
            "stoplight": feed_row.get("stoplight"),
            "detail_state": d_state,
            "status_message": msg,
            "summary": feed_row.get("detail"),
            "plain_summary": feed_row.get("plain_summary"),
            "mapping_note": (
                "A mapped departure signal is an event associated with a RideEdge area and an estimated "
                "departure window; it is not proof that passengers are currently leaving."
            ),
            "unique_events_count": expected_events,
            "mapped_signals_count": expected_signals,
            "excluded_events_count": max(0, expected_events - expected_signals),
            "events": [],
            "signals": [],
            "records": [],
        })

    if adapter_key == "onebusaway_transit":
        from farol.awareness import timestamp

        oba_cached = read_cache("onebusaway_st40_vehicles")
        records: list[dict] = []
        if isinstance(oba_cached, dict) and isinstance(oba_cached.get("payload"), dict):
            fetched_str = str(oba_cached.get("fetched_at") or feed_row.get("fetched_at") or current.isoformat())
            fetched_dt = (timestamp(fetched_str) or current).astimezone(PACIFIC)
            src_age = age_minutes(fetched_str, current)
            elapsed_sec = max(0.0, (current - fetched_dt).total_seconds())
            is_fresh_telemetry = src_age is not None and -2.0 <= src_age <= 10.0
            arr_sigs = onebusaway.parse_station_arrivals(
                oba_cached["payload"],
                fetched_dt,
                fetched_dt + timedelta(hours=2),
                fetched_at=fetched_str,
            )
            dis_sigs = onebusaway.parse(
                oba_cached["payload"],
                fetched_dt,
                fetched_dt + timedelta(hours=2),
                fetched_at=fetched_str,
            )
            for sig in arr_sigs:
                for tr in sig.details.get("trains") or []:
                    offset_sec = int(tr.get("offset_seconds") or (int(tr.get("eta_minutes") or 0) * 60))
                    anchored_arr_dt = (fetched_dt + timedelta(seconds=offset_sec)).astimezone(PACIFIC)
                    remaining_sec = offset_sec - elapsed_sec
                    if is_fresh_telemetry and remaining_sec >= -60.0:
                        eta_m: int | None = max(1, round(max(0.0, remaining_sec) / 60.0))
                        row_basis = "live"
                    else:
                        eta_m = None
                        row_basis = "expired_telemetry"
                    records.append({
                        "record_type": "train_arrival",
                        "station": str(tr.get("station") or sig.details.get("venue") or ""),
                        "zone": sig.zone,
                        "zone_label": _zlabel(sig.zone),
                        "route_line": str(tr.get("line") or "Link"),
                        "direction_headsign": f"to {tr.get('headsign', 'Link')}",
                        "arrival_time": anchored_arr_dt.strftime("%I:%M %p").lstrip("0"),
                        "eta_minutes": eta_m,
                        "basis": row_basis,
                        "source_age_minutes": src_age,
                        "service_alert": None,
                    })
            for sig in dis_sigs:
                records.append({
                    "record_type": "service_alert",
                    "station": _zlabel(sig.zone),
                    "zone": sig.zone,
                    "zone_label": _zlabel(sig.zone),
                    "route_line": "Link Light Rail",
                    "direction_headsign": "Service alert",
                    "arrival_time": None,
                    "eta_minutes": None,
                    "basis": sig.basis if is_fresh_telemetry else "expired_telemetry",
                    "source_age_minutes": src_age,
                    "service_alert": str(sig.details.get("title") or "Link disruption"),
                })
        sig_cnt = int(feed_row.get("signal_count") or 0)
        d_state = (
            "ready"
            if records
            else ("details_not_saved" if sig_cnt > 0 and oba_cached is None else "empty")
        )
        return _safe({
            "adapter": adapter_key,
            "label": feed_row["label"],
            "category": feed_row["category"],
            "kind": "transit",
            "snapshot_id": snapshot_id,
            "collected_at": snapshot.get("collected_at"),
            "fetched_at": feed_row.get("fetched_at"),
            "age_minutes": feed_row.get("age_minutes"),
            "mode": feed_row.get("mode"),
            "stoplight": feed_row.get("stoplight"),
            "detail_state": d_state,
            "status_message": (
                f"{len(records)} live Link arrival/alert record(s) in retained snapshot."
                if records
                else (
                    "Details weren't saved for this check."
                    if d_state == "details_not_saved"
                    else "0 active Link train arrivals or service alerts in retained snapshot."
                )
            ),
            "summary": feed_row.get("detail"),
            "plain_summary": feed_row.get("plain_summary"),
            "records": records,
        })

    if adapter_key == "wsf_colman_ferries":
        wsf_cached = read_cache("wsf_vessel_locations")
        records = []
        if isinstance(wsf_cached, dict) and isinstance(wsf_cached.get("payload"), list):
            fetched_str = str(wsf_cached.get("fetched_at") or feed_row.get("fetched_at") or current.isoformat())
            src_age = age_minutes(fetched_str, current)
            wsf_sigs = wsf_ferries.parse(
                wsf_cached["payload"],
                current - timedelta(minutes=15),
                current + timedelta(hours=6),
                fetched_at=fetched_str,
            )
            for sig in wsf_sigs:
                det = sig.details or {}
                records.append({
                    "record_type": "ferry_arrival",
                    "terminal": str(det.get("destination_terminal") or "Seattle Colman Dock (Pier 52)"),
                    "route": f"{det.get('origin_terminal', 'Puget Sound')} → Seattle Colman Dock",
                    "vessel": str(det.get("vessel") or "WSF Ferry"),
                    "arrival_time": sig.starts_at,
                    "disembark_window_end": sig.ends_at,
                    "time_meaning": "Estimated dock arrival and 25-minute passenger disembark window",
                    "basis": sig.basis,
                    "delay_minutes": int(det.get("delay_minutes") or 0),
                    "source_age_minutes": src_age,
                    "title": str(det.get("title") or ""),
                })
        sig_cnt = int(feed_row.get("signal_count") or 0)
        d_state = (
            "ready"
            if records
            else ("details_not_saved" if sig_cnt > 0 and wsf_cached is None else "empty")
        )
        return _safe({
            "adapter": adapter_key,
            "label": feed_row["label"],
            "category": feed_row["category"],
            "kind": "ferries",
            "snapshot_id": snapshot_id,
            "collected_at": snapshot.get("collected_at"),
            "fetched_at": feed_row.get("fetched_at"),
            "age_minutes": feed_row.get("age_minutes"),
            "mode": feed_row.get("mode"),
            "stoplight": feed_row.get("stoplight"),
            "detail_state": d_state,
            "status_message": (
                f"{len(records)} Colman Dock ferry arrival record(s) in retained snapshot."
                if records
                else (
                    "Details weren't saved for this check."
                    if d_state == "details_not_saved"
                    else "0 Colman Dock ferry arrivals in the current window."
                )
            ),
            "summary": feed_row.get("detail"),
            "plain_summary": feed_row.get("plain_summary"),
            "records": records,
        })

    if adapter_key == "amtrak_king_street":
        am_cached = read_cache("amtraker_v3_trains") or read_cache("amtrak_v3_trains")
        records = []
        if isinstance(am_cached, dict) and isinstance(am_cached.get("payload"), dict):
            fetched_str = str(am_cached.get("fetched_at") or feed_row.get("fetched_at") or current.isoformat())
            src_age = age_minutes(fetched_str, current)
            am_sigs = amtrak_sea.parse(
                am_cached["payload"],
                current - timedelta(minutes=15),
                current + timedelta(hours=6),
                fetched_at=fetched_str,
            )
            for sig in am_sigs:
                det = sig.details or {}
                records.append({
                    "record_type": "train_arrival",
                    "station": "King Street Station (Seattle)",
                    "zone": sig.zone,
                    "zone_label": _zlabel(sig.zone),
                    "route_line": f"Amtrak #{det.get('train_number') or det.get('train_num') or ''}".strip(),
                    "direction_headsign": f"from {det.get('origin', 'Corridor')}",
                    "arrival_time": str(det.get("arrival_time") or sig.starts_at),
                    "eta_minutes": None,
                    "basis": sig.basis,
                    "source_age_minutes": src_age,
                    "title": str(det.get("title") or ""),
                })
        sig_cnt = int(feed_row.get("signal_count") or 0)
        d_state = (
            "ready"
            if records
            else ("details_not_saved" if sig_cnt > 0 and am_cached is None else "empty")
        )
        return _safe({
            "adapter": adapter_key,
            "label": feed_row["label"],
            "category": feed_row["category"],
            "kind": "transit",
            "snapshot_id": snapshot_id,
            "collected_at": snapshot.get("collected_at"),
            "fetched_at": feed_row.get("fetched_at"),
            "age_minutes": feed_row.get("age_minutes"),
            "mode": feed_row.get("mode"),
            "stoplight": feed_row.get("stoplight"),
            "detail_state": d_state,
            "status_message": (
                f"{len(records)} Amtrak King Street arrival record(s) in retained snapshot."
                if records
                else (
                    "Details weren't saved for this check."
                    if d_state == "details_not_saved"
                    else "0 Amtrak King Street arrivals in the current window."
                )
            ),
            "summary": feed_row.get("detail"),
            "plain_summary": feed_row.get("plain_summary"),
            "records": records,
        })

    if adapter_key == "besttime_busyness":
        from farol import radar
        from farol.besttime import review_entry
        from farol.besttime_cache import coverage, hour_record, usable_hour

        bt_report = saved_besttime(current)
        records = []
        for item in (bt_report or {}).get("venues") or []:
            item = review_entry(item)
            req = item.get("requested") or {}
            live = item.get("live") or {}
            fc = item.get("forecast") or {}
            applicable = hour_record(fc, current)
            usable_pattern = usable_hour(fc, current, current)
            value = live.get("busyness")
            retained_live = live.get("available") is True and radar.number(value)
            live_fresh = retained_live and radar.fresh(live.get("retrieved_at"), current, 60)
            matched = item.get("identity_matched") is True
            zone = radar.canonical_zone(str(req.get("zone") or ""))
            detail = (f"Retained provider reading: {value:g}% of this venue's own weekly peak. "
                      "Underlying measurement time unknown." if retained_live else
                      "No usable live reading retained; a weekly pattern is not current crowd activity.")
            if not matched:
                detail += " Venue identity is unverified; excluded from recommendations."
            elif not item["identity_review"]["live_matched"]:
                detail += " Live venue identity is unverified; a matched weekly pattern may still be used."
            records.append({
                "id": req.get("id"),
                "title": req.get("name"),
                "venue": req.get("name"),
                "zone": req.get("zone"),
                "zone_label": req.get("area") or _zlabel(req.get("zone")),
                "basis": "current provider reading" if live_fresh else "stale retained provider reading" if retained_live
                    else "typical weekly pattern" if fc.get("available") else "unverified",
                "live_busyness_pct": value if retained_live else None,
                "typical_this_hour_pct": live.get("typical_this_hour"),
                "applicable_pattern_pct": usable_pattern.get("typical_busyness") if usable_pattern else None,
                "applicable_pattern_retrieved_at": applicable.get("retrieved_at") if applicable else None,
                "applicable_pattern_provenance": applicable.get("provenance") if applicable else None,
                "applicable_pattern_state": ("missing_hour" if applicable is None else "expired" if usable_pattern is None
                                              else "closed" if usable_pattern.get("closed") is True else "available"),
                "identity_matched": matched,
                "identity_review": item["identity_review"],
                "live_usable_for_radar": bool(live_fresh and matched and item["identity_review"]["live_matched"]
                                              and zone in zones_by_id and zone != "sea_airport"
                                              and live.get("open_status") not in (False, "Closed") and value >= 20),
                "measurement_time": None,
                "live_retrieved_at": live.get("retrieved_at"), "forecast_retrieved_at": fc.get("retrieved_at"),
                "open_status": live.get("open_status"),
                "retrieved_at": live.get("retrieved_at") or fc.get("retrieved_at"),
                "detail": detail,
            })
        return _safe({
            "adapter": adapter_key,
            "label": feed_row["label"],
            "category": feed_row["category"],
            "kind": "venue_activity",
            "snapshot_id": snapshot_id,
            "collected_at": snapshot.get("collected_at"),
            "fetched_at": feed_row.get("fetched_at"),
            "age_minutes": feed_row.get("age_minutes"),
            "mode": feed_row.get("mode"),
            "stoplight": feed_row.get("stoplight"),
            "detail_state": "ready" if records else ("disabled" if feed_row.get("mode") == "needs_key" else "empty"),
            "status_message": f"{len(records)} retained venue(s) in saved BestTime snapshot; usable current-hour coverage is reported separately.",
            "venue_coverage": coverage((bt_report or {}).get("venues") or [], current, current),
            "summary": feed_row.get("detail"),
            "plain_summary": feed_row.get("plain_summary"),
            "records": records,
        })

    if adapter_key == "flightaware_sea":
        airport_report = flightaware.seatac_6h_forecast(now=current, pull=False)
        if airport_report.get("hours"):
            records = []
            for hour in airport_report["hours"]:
                records.append({
                    "title": hour.get("hour_label", "Arrival window"), "starts_at": hour.get("starts_at"),
                    "ends_at": hour.get("ends_at"), "fetched_at": hour.get("fetched_at"),
                    "basis": "current returned schedule" if hour.get("usable") else "stale or unavailable",
                    "source": flightaware.SCHEDULED_ARRIVALS_URL, "coverage": hour.get("coverage"),
                    "sampled_flights": hour.get("sampled_flights"), "estimated_planes": hour.get("estimated_planes"),
                    "estimate_method": hour.get("estimate_method"), "timing_basis_counts": hour.get("timing_basis_counts"),
                    "excluded_records": hour.get("excluded_records"), "flights": hour.get("flights", []),
                })
            return _safe({
                "adapter": adapter_key, "label": feed_row["label"], "category": feed_row["category"],
                "kind": "flights", "snapshot_id": f"seatac-{airport_report.get('requested_at') or airport_report.get('fetched_at')}",
                "fetched_at": airport_report.get("fetched_at"), "mode": feed_row.get("mode"),
                "detail_state": airport_report["state"], "status_message": "Retained hourly SeaTac report; this view makes no provider requests.",
                "plain_summary": airport_report["coverage_note"], "records": records,
                "provider_usage": airport_report.get("provider_usage"),
            })
        fa_cached = read_cache("flightaware_ksea_arrivals_p2")
        records = []
        if isinstance(fa_cached, dict) and isinstance(fa_cached.get("payload"), dict):
            fetched_str = str(fa_cached.get("fetched_at") or feed_row.get("fetched_at") or current.isoformat())
            fa_sigs = flightaware.parse(
                fa_cached["payload"],
                current - timedelta(hours=2),
                current + timedelta(hours=6),
                fetched_at=fetched_str,
                page_limit=flightaware.DEMAND_PAGES,
            )
            for sig in fa_sigs:
                det = sig.details or {}
                records.append({
                    "id": sig.id,
                    "title": det.get("title") or "KSEA arrival wave",
                    "zone": sig.zone,
                    "zone_label": _zlabel(sig.zone),
                    "starts_at": sig.starts_at,
                    "ends_at": sig.ends_at,
                    "basis": sig.basis,
                    "flight_count": det.get("count"),
                    "per_hour": det.get("per_hour"),
                    "detail": f"{det.get('count', 0)} flights ({det.get('per_hour', 0)}/hr)",
                })
        return _safe({
            "adapter": adapter_key,
            "label": feed_row["label"],
            "category": feed_row["category"],
            "kind": "flights",
            "snapshot_id": snapshot_id,
            "collected_at": snapshot.get("collected_at"),
            "fetched_at": feed_row.get("fetched_at"),
            "age_minutes": feed_row.get("age_minutes"),
            "mode": feed_row.get("mode"),
            "stoplight": feed_row.get("stoplight"),
            "detail_state": "ready" if records else ("disabled" if feed_row.get("mode") == "needs_key" else "empty"),
            "status_message": (
                f"{len(records)} KSEA arrival wave(s) in cached AeroAPI snapshot."
                if records
                else str(feed_row.get("detail") or "No cached KSEA flight waves.")
            ),
            "summary": feed_row.get("detail"),
            "plain_summary": feed_row.get("plain_summary"),
            "records": records,
        })

    # Generic fallback for all remaining adapters using retained awareness_snapshot signals
    from farol.adapters.situational_waves import review_record

    prefixes = ADAPTER_SOURCE_PREFIXES.get(adapter_key, (adapter_key,))
    records = []
    for sig in snapshot.get("signals") or []:
        if not isinstance(sig, dict):
            continue
        sig = review_record(sig)
        src = str(sig.get("source") or "")
        if any(src.startswith(p) or p in src for p in prefixes):
            det = sig.get("details") or {}
            records.append({
                "id": sig.get("id"),
                "kind": sig.get("kind"),
                "title": str(det.get("title") or det.get("headline") or sig.get("kind") or adapter_key),
                "venue": det.get("venue"),
                "zone": sig.get("zone"),
                "zone_label": _zlabel(sig.get("zone")),
                "starts_at": sig.get("starts_at"),
                "ends_at": sig.get("ends_at"),
                "basis": sig.get("basis"),
                "source": src,
                "assumption_review": det.get("assumption_review"),
                "fetched_at": sig.get("fetched_at"),
                "detail": str(det.get("description") or det.get("notes") or det.get("exit_timing_basis") or ""),
            })
    sig_cnt = int(feed_row.get("signal_count") or 0)
    if feed_row.get("mode") == "needs_key":
        d_state = "disabled"
        msg = "Source is not configured (missing API key)."
    elif records:
        d_state = "ready"
        msg = f"{len(records)} retained record(s) from this source snapshot."
    elif sig_cnt > 0:
        d_state = "details_not_saved"
        msg = "Details weren't saved for this check."
    else:
        d_state = "empty"
        msg = "0 active records in the current snapshot window."

    return _safe({
        "adapter": adapter_key,
        "label": feed_row["label"],
        "category": feed_row["category"],
        "kind": "general",
        "snapshot_id": snapshot_id,
        "collected_at": snapshot.get("collected_at"),
        "fetched_at": feed_row.get("fetched_at"),
        "age_minutes": feed_row.get("age_minutes"),
        "mode": feed_row.get("mode"),
        "stoplight": feed_row.get("stoplight"),
        "detail_state": d_state,
        "status_message": msg,
        "summary": feed_row.get("detail"),
        "plain_summary": feed_row.get("plain_summary"),
        "records": records,
    })


def _loop() -> None:
    with _lock:
        _state["running"] = True
        _state["last_detail"] = "collector started"
    while not _stop.is_set():
        try:
            refresh_once()
        except Exception as error:  # noqa: BLE001
            with _lock:
                _state["last_detail"] = f"collector error: {error!r}"[:300]
        interval = interval_seconds()
        with _lock:
            _state["next_run_at"] = (datetime.now(UTC) + timedelta(seconds=interval)).isoformat()
            _state["interval_seconds"] = interval
        _stop.wait(interval)
    with _lock:
        _state["running"] = False
        _state["next_run_at"] = None
        _state["last_detail"] = "collector stopped"


def start() -> None:
    global _thread
    if not enabled():
        with _lock:
            _state["last_detail"] = "collector idle (mock feeds, tests, or FAROL_COLLECT=0)"
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="farol-collect", daemon=True)
        _thread.start()


def stop(*, wait=True) -> None:
    _stop.set()
    thread = _thread
    if wait and thread is not None and thread.is_alive():
        thread.join(timeout=2)
