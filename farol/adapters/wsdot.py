"""WSDOT Traveler Information: Eastside highway alerts and travel times.

Free AccessCode in WSDOT_API_KEY. Highway Alerts (I-5 / I-90 / I-405 / SR 520
in the Northwest region) plus a small set of named travel-time routes. Does not
replace Google Routes pin-to-anchor matrix; this is incidents and corridor delay.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime

from farol.adapters.base import FeedError, FeedStatus, fetch_json
from farol.signals import Signal

NAME = "wsdot_traffic"
SOURCE = "wsdot:Traveler Information REST"
ALERTS_URL = "https://wsdot.wa.gov/Traffic/api/HighwayAlerts/HighwayAlertsREST.svc/GetAlertsAsJson"
TIMES_URL = "https://wsdot.wa.gov/Traffic/api/TravelTimes/TravelTimesREST.svc/GetTravelTimesAsJson"
TTL_SECONDS = 5 * 60

# WSDOT RoadName is the route number without "I-".
WATCH_ROADS = {
    "405": ("I-405", ("kirkland_rose_hill", "kirkland_waterfront", "totem_lake", "bellevue_core", "redmond_downtown")),
    "520": ("SR 520", ("kirkland_waterfront", "bellevue_core", "redmond_downtown", "woodinville_wine")),
    "090": ("I-90", ("bellevue_core", "issaquah", "sodo_stadiums")),
    "005": ("I-5", ("sodo_stadiums", "seattle_core", "seattle_center", "uw_district")),
}
# King County I-90 is roughly MP 0–25; I-5 through Seattle ~150–185.
MILEPOST_MAX = {"090": 25.0, "005": 185.0}
MILEPOST_MIN = {"005": 150.0}
SKIP_PRIORITY = {"Lowest"}
# Named corridors Farol actually deadheads. Skip HOV twins.
WATCH_TIME_NAMES = {
    "Bellevue-Seattle via 520": ("bellevue_core", "seattle_center"),
    "Seattle-Bellevue via 520": ("seattle_center", "bellevue_core"),
    "Bellevue-Redmond": ("bellevue_core", "redmond_downtown"),
    "Redmond-Bellevue": ("redmond_downtown", "bellevue_core"),
    "Woodinville-Seattle via 520": ("woodinville_wine", "seattle_center"),
    "Seattle-Woodinville via 520": ("seattle_center", "woodinville_wine"),
    "Alderwood-Southcenter via 405": ("totem_lake", "sodo_stadiums"),
    "Southcenter-Alderwood via 405": ("sodo_stadiums", "totem_lake"),
}
DELAY_MINUTES = 5
PRIORITY_MAGNITUDE = {"Highest": 8.0, "High": 6.0, "Medium": 4.0, "Low": 2.0}


def _access_code() -> str:
    return os.getenv("WSDOT_API_KEY", "").strip()


def _alert_time(value: object, tzinfo) -> datetime | None:
    """WSDOT uses .NET epoch milliseconds as well as ISO timestamps.

    The optional -0700 suffix is display metadata; milliseconds already denote
    a UTC instant. Do not apply the offset a second time.
    """
    match = re.fullmatch(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/", str(value))
    try:
        stamp = (datetime.fromtimestamp(int(match[1]) / 1000, UTC) if match
                 else datetime.fromisoformat(str(value)))
        return stamp.astimezone(tzinfo) if stamp.tzinfo else None
    except (ValueError, OverflowError, OSError):
        return None


def _in_box(alert: dict) -> bool:
    if (alert.get("Region") or "") != "Northwest":
        return False
    if (alert.get("Priority") or "") in SKIP_PRIORITY:
        return False
    loc = alert.get("StartRoadwayLocation") or {}
    road = str(loc.get("RoadName") or "")
    if road not in WATCH_ROADS:
        return False
    try:
        mile = float(loc.get("MilePost"))
    except (TypeError, ValueError):
        mile = None
    if road in MILEPOST_MIN and mile is not None and mile < MILEPOST_MIN[road]:
        return False
    return not (road in MILEPOST_MAX and mile is not None and mile > MILEPOST_MAX[road])


def parse_alerts(payload: list, window_start: datetime, window_end: datetime, *, fetched_at: str) -> list[Signal]:
    signals: list[Signal] = []
    if not isinstance(payload, list):
        return signals
    for alert in payload:
        if not isinstance(alert, dict) or not _in_box(alert):
            continue
        loc = alert.get("StartRoadwayLocation") or {}
        road = str(loc.get("RoadName") or "")
        label, zones = WATCH_ROADS[road]
        headline = str(alert.get("HeadlineDescription") or "Highway alert").strip()
        headline_lower = headline.lower()
        is_bridge_closure = road in {"520", "090"} and any(
            phrase in headline_lower
            for phrase in (
                "bridge closed",
                "all lanes closed",
                "both directions closed",
                "full closure",
                "floating bridge closed",
            )
        )
        priority = "Highest" if is_bridge_closure else str(alert.get("Priority") or "Low")
        magnitude = PRIORITY_MAGNITUDE.get(priority, 2.0)
        category = str(alert.get("EventCategory") or "Alert")
        ends = _alert_time(alert.get("EndTime"), window_start.tzinfo) or window_end
        if ends < window_start:
            continue
        starts = window_start
        parsed = _alert_time(alert.get("StartTime"), window_start.tzinfo)
        if parsed and parsed > window_start:
            starts = parsed
        if starts > window_end:
            continue
        mile = loc.get("MilePost")
        direction = loc.get("Direction") or ""
        prefix = "CROSS-LAKE BRIDGE CLOSURE: " if is_bridge_closure else ""
        for zone in zones:
            signals.append(
                Signal(
                    id=f"wsdot-alert-{alert.get('AlertID')}-{zone}",
                    kind="highway_alert",
                    zone=zone,
                    starts_at=starts.isoformat(),
                    ends_at=min(window_end, ends).isoformat(),
                    magnitude=magnitude,
                    basis="live",
                    source=SOURCE,
                    fetched_at=fetched_at,
                    expires_at=min(window_end, ends).isoformat(),
                    evidence_quality=0.75,
                    details={
                        "title": f"{prefix}{priority} {category} on {label}"
                        + (f" MP {mile}" if mile is not None else "")
                        + (f" {direction}B" if direction else ""),
                        "headline": headline[:240],
                        "description": headline[:4000],
                        "road": label,
                        "priority": priority,
                        "category": category,
                        "bridge_closure": is_bridge_closure,
                    },
                )
            )
    return signals


def parse_times(payload: list, window_start: datetime, window_end: datetime, *, fetched_at: str) -> list[Signal]:
    signals: list[Signal] = []
    if not isinstance(payload, list):
        return signals
    for row in payload:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Name") or "")
        if name not in WATCH_TIME_NAMES:
            continue
        try:
            current = float(row.get("CurrentTime"))
            average = float(row.get("AverageTime"))
        except (TypeError, ValueError):
            continue
        delay = current - average
        if delay < DELAY_MINUTES:
            continue
        origin, dest = WATCH_TIME_NAMES[name]
        title = f"{name} {current:.0f} min (avg {average:.0f}, +{delay:.0f})"
        for zone in (origin, dest):
            signals.append(
                Signal(
                    id=f"wsdot-time-{row.get('TravelTimeID')}-{zone}",
                    kind="travel_delay",
                    zone=zone,
                    starts_at=window_start.isoformat(),
                    ends_at=window_end.isoformat(),
                    magnitude=min(delay, 20.0),
                    basis="live",
                    source=SOURCE,
                    fetched_at=fetched_at,
                    expires_at=fetched_at,
                    evidence_quality=0.7,
                    details={
                        "title": title,
                        "route": name,
                        "current_minutes": current,
                        "average_minutes": average,
                        "delay_minutes": round(delay, 1),
                    },
                )
            )
    return signals


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    code = _access_code()
    if not code:
        return [], FeedStatus(
            NAME,
            "needs_key",
            "env:WSDOT_API_KEY",
            None,
            0,
            "set WSDOT_API_KEY — Traveler Information Access Code",
        )
    signals: list[Signal] = []
    modes: list[str] = []
    fetched_at = ""
    errors: list[str] = []
    for label, url in (("alerts", ALERTS_URL), ("times", TIMES_URL)):
        try:
            payload, mode, fetched_at = fetch_json(
                f"{url}?AccessCode={code}",
                cache_key=f"wsdot_{label}",
                ttl_seconds=TTL_SECONDS,
            )
        except FeedError as error:
            errors.append(f"{label}: {error}")
            continue
        modes.append(mode)
        rows = payload if isinstance(payload, list) else []
        if label == "alerts":
            signals.extend(parse_alerts(rows, window_start, window_end, fetched_at=fetched_at))
        else:
            signals.extend(parse_times(rows, window_start, window_end, fetched_at=fetched_at))
    if not modes and errors:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, "; ".join(errors)[:300])
    mode = "stale_cache" if "stale_cache" in modes else ("cache" if set(modes) == {"cache"} else "live")
    detail = f"{len(signals)} Eastside alerts/delays"
    if errors:
        detail += f"; {'; '.join(errors)}"
    return signals, FeedStatus(NAME, mode, SOURCE, fetched_at or None, len(signals), detail)
