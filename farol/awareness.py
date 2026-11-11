"""Read-only local/metro context from collector snapshots and saved BestTime trials.

No network, model, route, GPS persistence, or navigation commands in this view.
Source retrieval age is displayed separately from event/forecast time.
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from farol.adapters.base import cache_dir
from farol.besttime import sanitize, save
from farol.dashboard import FIXTURES, ROOT
from farol.evidence import parse_time
from farol.signals import FixtureSignalAdapter, Signal
from farol.zones import canonical_zone, load_zones

PACIFIC = ZoneInfo("America/Los_Angeles")
LAYERS = {
    "events": "Events and exits", "dining": "Dining and nightlife",
    "access": "Traffic and access", "transit": "Transit", "weather": "Weather",
    "airport": "Airport and cruise",
}
KINDS = {
    "event_exit": "events", "special_event": "events", "closing_wave": "dining",
    "highway_alert": "access", "travel_delay": "access", "doctrine_penalty": "access",
    "transit_disruption": "transit", "precipitation": "weather",
    "airport_arrivals": "airport", "cruise_disembark": "airport",
}


def timestamp(value: object) -> datetime | None:
    stamp = parse_time(value)
    return stamp if stamp and stamp.tzinfo else None


def age_minutes(value: object, now: datetime) -> float | None:
    stamp = timestamp(value)
    if stamp is None or stamp > now + timedelta(minutes=1):
        return None
    return round(max(0, (now - stamp).total_seconds() / 60), 1)


def _safe(value):
    secrets = tuple(value for key, value in os.environ.items() if len(value) >= 8
                    and any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")))
    return sanitize(value, secrets)


def write_snapshot(signals: list[Signal], feeds: list[dict], start: datetime, end: datetime):
    from farol.adapters import _doctrine_signals, _prefer_google_venue_hours
    from farol.evidence import dedupe_events, sanitize_signals

    cleaned = dedupe_events(_prefer_google_venue_hours(sanitize_signals(signals)))
    cleaned += _doctrine_signals(cleaned)
    collected_at = datetime.now(UTC).isoformat()
    snapshot_id = f"snap-{collected_at}"
    snapshot = _safe({
        "schema": 1, "snapshot_id": snapshot_id, "collected_at": collected_at,
        "window_start": start.isoformat(), "window_end": end.isoformat(),
        "signals": [asdict(signal) for signal in cleaned], "feeds": feeds,
    })
    save(cache_dir() / "awareness_snapshot.json", snapshot)
    tm_path = cache_dir() / "source_details" / "ticketmaster_events.json"
    if tm_path.is_file():
        try:
            tm_data = json.loads(tm_path.read_text(encoding="utf-8"))
            if isinstance(tm_data, dict):
                tm_data["snapshot_id"] = snapshot_id
                tm_path.write_text(json.dumps(tm_data, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            pass
    from farol.changes import retain
    retain(snapshot)


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def saved_besttime(now: datetime) -> dict | None:
    candidates = []
    for path in (ROOT / ".cache" / "besttime").glob("*/report.json"):
        report = _read(path)
        stamp = timestamp((report or {}).get("finished_at"))
        if stamp and stamp <= now:
            candidates.append((stamp, report))
    return max(candidates, key=lambda pair: pair[0])[1] if candidates else None


def _distance(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((phi2 - phi1) / 2) ** 2 + math.cos(phi1) * math.cos(phi2)
         * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 3958.8 * 2 * math.asin(math.sqrt(min(1, a)))


def _freshness(signal: dict, now: datetime, demo: bool) -> tuple[str, float | None]:
    if demo:
        return "demo", None
    static_venue = (signal["id"].startswith("venue-")
                    and not signal["source"].startswith("google:places.googleapis.com"))
    if signal["source"].startswith(("farol:", "fixtures/")) or static_venue:
        return "standing schedule", None
    age = age_minutes(signal.get("fetched_at"), now)
    if age is None:
        return "time unknown", None
    limit = (15 if signal["kind"] in {"highway_alert", "travel_delay", "transit_disruption"}
             else 90 if signal["kind"] == "precipitation" else 24 * 60)
    expires = timestamp(signal.get("expires_at"))
    fetched = timestamp(signal.get("fetched_at"))
    expired = bool(expires and fetched and expires > fetched and expires < now)
    return ("old source data" if age > limit or expired else "recently checked"), age


def _observation(signal: dict, now: datetime, demo: bool) -> dict | None:
    kind = signal.get("kind")
    if kind not in KINDS:
        return None
    start, end = timestamp(signal.get("starts_at")), timestamp(signal.get("ends_at"))
    if not start or not end or end <= start:
        return None
    details = signal.get("details") or {}
    event_start = timestamp(details.get("kickoff") or details.get("first_pitch"))
    begins = event_start if kind == "event_exit" and event_start and event_start < start else start
    freshness, age = _freshness(signal, now, demo)
    if details.get("community_event"):
        freshness = details.get("freshness", freshness)
    notes = []
    for field in ("description" if details.get("description") else "headline", "notes",
                  "exit_timing_basis"):
        if details.get(field):
            notes.append(str(details[field]))
    timing = {"event_exit": "Estimated exit window", "closing_wave": "Closing window",
              "precipitation": "Forecast window", "highway_alert": "Restriction times unverified",
              "travel_delay": "Travel time when checked"}.get(kind, "Applies during")
    if details.get("community_event"):
        timing = "Hours unconfirmed" if details.get("date_only") else "Published hours"
    if kind == "highway_alert":
        notes.append("Read the description for closure hours; an alert listed now may describe a later restriction.")
    if kind == "event_exit" and not details.get("exit_timing_basis"):
        notes.append("Exit time is an estimate; check the event schedule.")
    if kind in {"highway_alert", "travel_delay", "transit_disruption"}:
        notes.append("Applies to the listed corridor or service; local pickup access is unverified.")
    if kind == "closing_wave" and details.get("close_at"):
        notes.append("Closing time: " + str(details["close_at"]))
    zone = canonical_zone(str(signal.get("zone", "unknown")))
    layer_name = (
        "transit"
        if details.get("category") in {"transit", "ferry", "rail", "light_rail"}
        else "dining"
        if details.get("category") == "foot_traffic"
        else KINDS[kind]
    )
    return {
        "id": str(signal["id"]), "layer": layer_name, "kind": kind, "zones": [zone],
        "title": str(details.get("title") or kind.replace("_", " ")),
        "detail": " ".join(notes), "basis": signal.get("basis", "assumed"),
        "source": signal["source"], "fetched_at": signal.get("fetched_at"),
        "source_age_minutes": age, "freshness": freshness,
        "starts_at": begins.isoformat(), "ends_at": end.isoformat(),
        "window_starts_at": start.isoformat(), "timing_label": timing,
        "event_starts_at": event_start.isoformat() if event_start else None,
        "venue": details.get("venue"),
        "priority": details.get("priority"),
        "community_event": bool(details.get("community_event")),
        "category": details.get("category"), "date_only": bool(details.get("date_only")),
        "end_unknown": bool(details.get("end_unknown")), "local_date": details.get("local_date"),
        "source_url": details.get("url") if details.get("community_event") else None,
        "receipts": details.get("source_urls", []), "conflicts": details.get("conflicts", []),
        "location_label": details.get("location_label"),
        "location_precision": details.get("location_precision"),
        "_position": details.get("position") if details.get("community_event") else None,
    }


def observations(snapshot: dict, now: datetime, demo: bool = False) -> list[dict]:
    result, merged = [], {}
    failed_sources = {feed.get("source") for feed in snapshot.get("feeds", [])
                      if feed.get("mode") in {"stale_cache", "error"}}
    for signal in snapshot.get("signals", []):
        try:
            row = _observation(signal, now, demo)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if row is None:
            continue
        if not demo and row["source"] in failed_sources:
            row["freshness"] = "source refresh failed"
        if row["kind"] in {"highway_alert", "travel_delay", "transit_disruption"}:
            key = (row["kind"], row["source"], row["title"], row["detail"],
                   row["starts_at"], row["ends_at"])
            if key in merged:
                merged[key]["zones"] = sorted(set(merged[key]["zones"] + row["zones"]))
                continue
            merged[key] = row
        result.append(row)
    return result


def _typical_at(forecast: dict, at: datetime) -> dict | None:
    local = at.astimezone(PACIFIC)
    day = (local.weekday() - (local.hour < 6)) % 7
    profile = next((row for row in forecast.get("days", []) if row["weekday"] == day), None)
    if profile is None:
        return None
    return next((row for row in profile["hours"] if row["hour"] == local.hour), None)


def venue_activity(report: dict | None, now: datetime, start: datetime, end: datetime) -> list[dict]:
    try:
        return _venue_activity(report, now, start, end)
    except (KeyError, TypeError, ValueError, AttributeError):
        # An incompatible/corrupt pilot report must not hide the other feeds.
        return []


def _venue_activity(report: dict | None, now: datetime, start: datetime, end: datetime) -> list[dict]:
    if not report:
        return []
    panel = _read(FIXTURES / "venues.json") or {}
    zones = {item["id"]: item.get("zone") for item in panel.get("venues", [])}
    zones.update(caffe_vita_capitol_hill="capitol_hill", caffe_vita_kexp="seattle_center",
                 tavern_law="capitol_hill")
    result = []
    for item in report.get("venues", []):
        requested, forecast, live = item["requested"], item["forecast"], item["live"]
        matched = item.get("identity_matched") is True
        age = age_minutes(live.get("retrieved_at"), now)
        baseline_age = age_minutes(forecast.get("retrieved_at"), now)
        # This is a retrieval freshness bound, not a measurement-age claim.
        recent = bool(matched and live.get("available") and age is not None and age <= 75)
        current = _typical_at(forecast, now) if matched else None
        profile_usable = bool(matched and baseline_age is not None and baseline_age <= 30 * 24 * 60)
        points = []
        cursor = start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        while cursor < end.astimezone(UTC):
            point = _typical_at(forecast, cursor) if profile_usable else None
            if point and point.get("closed") is not True and point.get("typical_busyness") is not None:
                points.append({"at": cursor.isoformat(), "value": point["typical_busyness"]})
            cursor += timedelta(hours=1)
        peak = max(points, key=lambda row: row["value"]) if points else None
        next_hr_point = _typical_at(forecast, now + timedelta(hours=1)) if matched else None
        cur_typ = current.get("typical_busyness") if current and profile_usable else None
        if cur_typ is None and matched and isinstance(live.get("typical_this_hour"), (int, float)):
            cur_typ = int(live["typical_this_hour"])
        nxt_typ = next_hr_point.get("typical_busyness") if next_hr_point and profile_usable else None
        eff_now = live.get("busyness") if (matched and live.get("available") and recent) else cur_typ
        if not matched:
            note = "Weekly coverage unavailable; live coverage not checked"
        elif not live.get("available"):
            if age is not None and age <= 75 and isinstance(cur_typ, (int, float)) and cur_typ > 0:
                open_st = live.get("open_status") or "Open"
                nxt_str = f" → next hr {int(nxt_typ)}%" if isinstance(nxt_typ, (int, float)) else ""
                note = f"{open_st} · Polled {age}m ago ({int(cur_typ)}% this hr{nxt_str})"
            else:
                note = "Live reading unavailable in saved check"
        elif recent:
            note = "Saved live reading; see retrieval time"
        else:
            note = "Old live reading or unknown retrieval time; current busyness unknown"
        if isinstance(eff_now, (int, float)) and isinstance(nxt_typ, (int, float)) and eff_now >= 45 and (eff_now - nxt_typ) >= 15:
            note += f" · 🚶 Spillout wave next hr ({int(eff_now)}% → {int(nxt_typ)}%)"
        result.append({
            "id": requested["id"], "name": requested["name"], "area": requested["area"],
            "zone": requested.get("zone") or zones.get(requested["id"]), "source": "BestTime saved pilot",
            "weekly_available": bool(matched and forecast.get("available")),
            "profile_usable": profile_usable, "forecast_retrieved_at": forecast.get("retrieved_at"),
            "typical_now": cur_typ,
            "typically_closed_now": current.get("closed") if current and profile_usable else None,
            "window_peak": peak, "live_recent": recent,
            "live_value": live.get("busyness") if matched and live.get("available") else None,
            "live_baseline": live.get("typical_this_hour") if matched else None,
            "live_delta": live.get("delta_percentage_points") if matched else None,
            "live_retrieved_at": live.get("retrieved_at"), "live_age_minutes": age,
            "provider_time": live.get("provider_current_localtime"),
            "note": note,
        })
    return result


def build_view(snapshot: dict | None, *, now: datetime, scope="metro", area="totem_lake",
               radius=5.0, period="all", layer="all", latitude=None, longitude=None,
               besttime: dict | None = None, demo=False) -> dict:
    if (scope not in {"metro", "nearby"} or period not in {"now", "next", "later", "all", "today", "week"}
            or layer not in {"all", *LAYERS}):
        raise ValueError("Invalid scope, time window, or topic")
    registry = load_zones()
    area = canonical_zone(area)
    if area not in registry.by_id or not math.isfinite(radius) or not 0 <= radius <= 30:
        raise ValueError("Choose a supported area and a radius between 0 and 30 miles")
    if (latitude is None) != (longitude is None):
        raise ValueError("Provide both latitude and longitude")
    if latitude is not None and not (math.isfinite(latitude) and math.isfinite(longitude)
                                    and 47 <= latitude <= 48.2 and -123 <= longitude <= -121.5):
        raise ValueError("Location must be within the Seattle metro area")
    center = (min(registry.zones, key=lambda zone: _distance(latitude, longitude, zone.latitude, zone.longitude))
              if latitude is not None else registry.by_id[area])
    # The actual pin already drives the radius. Its nearest named area must also
    # drive the selector/label, rather than leaving the default Totem Lake label.
    area = center.id
    lat, lon = (latitude, longitude) if latitude is not None else (center.latitude, center.longitude)
    distances = {z.id: round(_distance(lat, lon, z.latitude, z.longitude), 1) for z in registry.zones}
    # Include the selected area only for a named-area center, not an unrelated GPS pin.
    selected = ({z for z, distance in distances.items() if distance <= radius}
                | ({area} if latitude is None else set()))
    offsets = {"now": (0, 0), "next": (0, 1), "later": (1, 6), "all": (0, 6), "today": (0, 14), "week": (0, 168)}
    first, last = offsets[period]
    start = (now.astimezone(UTC) + timedelta(hours=first)).astimezone(PACIFIC)
    end = (now.astimezone(UTC) + timedelta(hours=last)).astimezone(PACIFIC)
    snapshot = snapshot or {}
    all_rows = observations(snapshot, now, demo)
    def overlaps(row):
        begins, ends = timestamp(row["starts_at"]), timestamp(row["ends_at"])
        return ends > start and (begins <= end if period == "now" else begins < end)

    timed = [row for row in all_rows if overlaps(row)]
    def nearby(row):
        if row["community_event"]:
            position = row.get("_position")
            if position:
                distance = _distance(lat, lon, position["lat"], position["lon"])
                row["distance_miles"] = round(distance, 1)
                return distance <= radius
            # An unresolved venue is metro context, never "everywhere nearby".
            return False
        zone_dists = [distances[z] for z in row["zones"] if z in distances]
        if zone_dists and row.get("distance_miles") is None:
            row["distance_miles"] = min(zone_dists)
        return "all" in row["zones"] or bool(set(row["zones"]) & selected)

    local = [row for row in timed if scope == "metro" or nearby(row)]
    rows = [row for row in local if layer in {"all", row["layer"]}]
    priority = {"Highest": 4, "High": 3, "Medium": 2, "Low": 1}
    if scope == "nearby":
        rows.sort(key=lambda row: (
            timestamp(row["window_starts_at"] if row["kind"] == "event_exit" else row["starts_at"]) > now,
            row.get("distance_miles") if isinstance(row.get("distance_miles"), (int, float)) else 99.0,
            -priority.get(row["priority"], 0),
            row["starts_at"],
            row["title"],
        ))
    else:
        rows.sort(key=lambda row: (timestamp(row["starts_at"]) > now,
                                  -priority.get(row["priority"], 0), row["starts_at"], row["title"]))
    for row in rows:
        row["zone_labels"] = [registry.by_id[z].label if z in registry.by_id else "Metro wide"
                              for z in row["zones"]]
        row["state"] = "in window now" if timestamp(row["starts_at"]) <= now else "upcoming"
        if row["community_event"] and row["date_only"]:
            row["state"] = "date confirmed; hours unknown"
        if row["kind"] == "highway_alert":
            row["state"] = "road advisory"
        elif row["kind"] == "travel_delay":
            row["state"] = "last observed travel time"
        if row["kind"] == "event_exit" and timestamp(row["window_starts_at"]) > now:
            row["state"] = "scheduled underway" if timestamp(row["starts_at"]) <= now else "upcoming"
        row.pop("_position", None)
    # Now uses the current hour for historical busyness context.
    activity = venue_activity(besttime, now, start, end if end > start else start + timedelta(seconds=1))
    for row in activity:
        z = row.get("zone")
        if z in distances:
            row["distance_miles"] = distances[z]
    activity = [row for row in activity if scope == "metro" or row["zone"] in selected]
    if scope == "nearby":
        activity.sort(key=lambda row: (
            not bool(row.get("live_recent") and row.get("live_value") is not None),
            round((row.get("distance_miles") if isinstance(row.get("distance_miles"), (int, float)) else 99.0) / 3.5),
            -(row.get("live_value") if (row.get("live_recent") and row.get("live_value") is not None) else (row.get("typical_now") or 0)),
            row.get("distance_miles") if isinstance(row.get("distance_miles"), (int, float)) else 99.0,
        ))
    if layer not in {"all", "dining"}:
        activity = []
    sample = len(activity)
    recent = [row for row in activity if row["live_recent"]]
    age = age_minutes(snapshot.get("collected_at"), now)
    window_end = timestamp(snapshot.get("window_end"))
    feeds = [{"name": str(f.get("adapter", "source")).replace("_", " "),
              "mode": f.get("mode"), "fetched_at": f.get("fetched_at"),
              "age_minutes": age_minutes(f.get("fetched_at"), now),
              "source": f.get("source")} for f in snapshot.get("feeds", [])]
    counts = Counter(row["layer"] for row in local)
    return _safe({
        "as_of": now.isoformat(), "timezone": "America/Los_Angeles", "demo": demo,
        "scope": scope, "area": area, "period": period, "layer": layer,
        "location_label": center.label,
        "location_source": "device" if latitude is not None else "selected_area",
        "distance_note": "Approximate straight-line distance to published venue pins where available; otherwise area centers. Driving time is unknown.",
        "snapshot": {"collected_at": snapshot.get("collected_at"), "age_minutes": age,
                     "state": "demo" if demo else "missing" if not snapshot else
                     "old" if age is None or age > 75 or not window_end or window_end <= now else "ready",
                     "window_end": snapshot.get("window_end"),
                     "full_window_covered": bool(window_end and window_end >= end)},
        "areas": [{"id": z.id, "label": z.label, "cluster": z.cluster,
                   "distance_miles": distances[z.id],
                   "observations": sum(z.id in row["zones"] for row in timed)} for z in registry.zones],
        "layers": [{"id": key, "label": label, "count": counts[key]} for key, label in LAYERS.items()],
        "observations": rows, "venue_activity": activity, "feeds": feeds,
        "community_calendar": snapshot.get("community_calendar"),
        "busyness_coverage": {"sampled": sample, "weekly": sum(v["weekly_available"] for v in activity),
                              "recent_live": len(recent),
                              "above_typical": sum(v["live_delta"] is not None and v["live_delta"] > 0
                                                   for v in recent)},
        "empty_note": "No observations match these filters in the saved feeds. Coverage may be incomplete.",
    })


def awareness_view(**filters) -> dict:
    from farol.adapters import mock_feeds_active

    demo = mock_feeds_active()
    now = datetime(2026, 8, 14, 20, tzinfo=PACIFIC) if demo else datetime.now(PACIFIC)
    if demo:
        end = now + timedelta(hours=6)
        signals = FixtureSignalAdapter(FIXTURES / "tonight_signals.json").fetch(now, end)
        snapshot = {"collected_at": now.isoformat(), "window_end": end.isoformat(),
                    "signals": [asdict(row) for row in signals], "feeds": []}
    else:
        snapshot = _read(cache_dir() / "awareness_snapshot.json")
        from farol.community_events import catalog, event_signals

        calendar = catalog(now=now)
        # Read the catalog directly so a changed or canceled event does not wait for
        # the six-hour feed snapshot. This remains entirely local, including refresh.
        snapshot = dict(snapshot or {})
        signals = [row for row in snapshot.get("signals", [])
                   if not str(row.get("source", "")).startswith("community:")]
        signals.extend(asdict(row) for row in event_signals(now, now + timedelta(days=7), now=now))
        from farol.adapters import flightaware
        from farol.adapters.base import read_cache

        fa_cached = read_cache("flightaware_ksea_arrivals_p2")
        if isinstance(fa_cached, dict) and isinstance(fa_cached.get("payload"), dict):
            fa_signals = flightaware.parse(
                fa_cached["payload"],
                now - timedelta(hours=2),
                now + timedelta(hours=6),
                fetched_at=str(fa_cached.get("fetched_at") or now.isoformat()),
                page_limit=flightaware.DEMAND_PAGES,
            )
            existing_ids = {str(s.get("id")) for s in signals}
            for sig in fa_signals:
                sig_dict = asdict(sig)
                # Ensure recently cached live flight wave remains visible in the current hour
                end_dt = timestamp(sig_dict.get("ends_at"))
                if end_dt and end_dt < now + timedelta(minutes=30):
                    sig_dict["ends_at"] = (now + timedelta(minutes=45)).isoformat()
                if sig_dict["id"] not in existing_ids:
                    signals.append(sig_dict)
        snapshot["signals"] = signals
        feeds = [row for row in snapshot.get("feeds", [])
                 if not str(row.get("source", "")).startswith("community:")]
        for source in calendar["sources"]:
            feeds.append({"adapter": source["name"], "source": "community:" + source["source_id"],
                          "mode": "cache" if source["state"] == "ready" else "stale_cache",
                          "fetched_at": source.get("last_success")})
        snapshot["feeds"] = feeds
        snapshot["community_calendar"] = {
            "city": calendar["city"], "through_date": calendar["through_date"],
            "scheduled_count": calendar["scheduled_count"], "sources": calendar["sources"],
        }
    return build_view(snapshot, now=now, besttime=None if demo else saved_besttime(now),
                      demo=demo, **filters)
