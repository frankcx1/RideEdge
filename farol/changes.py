"""Bounded, local normalized snapshot history. Refresh failures are not resolutions."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from datetime import UTC, datetime

from farol.adapters.base import cache_dir
from farol.dashboard import ROOT
from farol.evidence import parse_time
from farol.signals import RouteEstimate

_lock = threading.Lock()
LIMIT = 4


def _allow_cache_write() -> bool:
    if not os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return cache_dir() != ROOT / ".cache" / "feeds" or bool(os.getenv("FAROL_CACHE_DIR"))


def _semantic_value(row: dict, field: str):
    value = row.get(field)
    if field == "details" and value and value.get("community_event"):
        # A source receipt refreshed at a new time is not a changed event.
        value = dict(value, source_urls=[
            {key: item for key, item in receipt.items() if key != "checked_at"}
            for receipt in value.get("source_urls", [])
        ])
    return value


def retain(snapshot: dict) -> None:
    path = cache_dir() / "awareness_history.json"
    with _lock:
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except (OSError, ValueError):
            history = []
        history = [*history[-(LIMIT - 1):], snapshot]
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(history), encoding="utf-8")
        temporary.replace(path)


def retain_routes(origin_zone: str, routes: dict[str, RouteEstimate], fetched_at: str | None) -> None:
    """Retain recent traffic-aware route matrices per origin zone for Ask and What Changed."""
    if not origin_zone or not routes or not fetched_at or not _allow_cache_write():
        return
    serialized = {
        key: asdict(route) if hasattr(route, "__dataclass_fields__") else dict(route)
        for key, route in routes.items()
    }
    if not any(row.get("basis") == "live" for row in serialized.values()):
        return
    path = cache_dir() / "routes_history.json"
    with _lock:
        try:
            store = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(store, dict):
                store = {}
        except (OSError, ValueError):
            store = {}
        bucket = store.get(origin_zone)
        if not isinstance(bucket, list):
            bucket = []
        entry = {"origin_zone": origin_zone, "fetched_at": fetched_at, "routes": serialized}
        if bucket and bucket[-1].get("fetched_at") == fetched_at:
            bucket[-1] = entry
        else:
            bucket = [*bucket[-(LIMIT - 1):], entry]
        store[origin_zone] = bucket
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(store), encoding="utf-8")
        temporary.replace(path)


def latest_routes(origin_zone: str, vehicle_cost_per_mile: float = 0.45) -> tuple[dict[str, RouteEstimate], str | None]:
    """Return the most recent cached route matrix for an origin zone."""
    if not _allow_cache_write():
        return {}, None
    path = cache_dir() / "routes_history.json"
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, None
    bucket = (store or {}).get(origin_zone)
    if not isinstance(bucket, list) or not bucket:
        return {}, None
    latest_entry = bucket[-1]
    raw_routes = latest_entry.get("routes") or {}
    parsed: dict[str, RouteEstimate] = {}
    for key, row in raw_routes.items():
        if not isinstance(row, dict):
            continue
        try:
            miles = float(row["distance_miles"])
            parsed[key] = RouteEstimate(
                origin_zone=origin_zone,
                destination_anchor_id=str(row["destination_anchor_id"]),
                traffic_minutes=float(row["traffic_minutes"]),
                distance_miles=miles,
                vehicle_cost=round(miles * vehicle_cost_per_mile, 2),
                basis=row.get("basis", "live"),
                source=str(row.get("source") or "google:routes"),
                fetched_at=str(row.get("fetched_at") or latest_entry.get("fetched_at") or ""),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return parsed, latest_entry.get("fetched_at")


def route_diff(origin_zone: str) -> list[dict]:
    """Compare the last two captured route matrices for an origin zone."""
    if not origin_zone or not _allow_cache_write():
        return []
    path = cache_dir() / "routes_history.json"
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    bucket = (store or {}).get(origin_zone)
    if not isinstance(bucket, list) or len(bucket) < 2:
        return []
    before, after = bucket[-2].get("routes") or {}, bucket[-1].get("routes") or {}
    changes = []
    for key in sorted(before.keys() & after.keys()):
        prev, curr = before[key], after[key]
        old_min = prev.get("traffic_minutes")
        new_min = curr.get("traffic_minutes")
        if not isinstance(old_min, (int, float)) or not isinstance(new_min, (int, float)):
            continue
        if abs(new_min - old_min) < 2:
            continue
        changes.append({
            "id": f"route-{key}",
            "kind": "route",
            "before": f"{old_min:g} min",
            "now": f"{new_min:g} min",
            "why": f"Traffic-aware route from {origin_zone.replace('_', ' ')} changed from {old_min:g} to {new_min:g} min.",
            "source": curr.get("source", "google:routes"),
            "observed_at": after[key].get("fetched_at") or bucket[-1].get("fetched_at"),
            "evidence_ids": [],
            "zone": origin_zone,
        })
    return changes


def diff(before: dict, after: dict, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    old = {row["id"]: row for row in before.get("signals", [])}
    new = {row["id"]: row for row in after.get("signals", [])}
    failed = {row.get("source") for row in after.get("feeds", []) if row.get("mode") in {"error", "stale_cache"}}
    changes = []
    for feed in after.get("feeds", []):
        if feed.get("source") in failed:
            changes.append({"id":f"coverage-{feed.get('adapter')}", "kind":"coverage", "before":"Earlier coverage", "now":"Refresh failed",
                            "why":"Missing observations do not mean conditions improved.", "source":feed.get("source"), "evidence_ids":[], "observed_at":feed.get("fetched_at")})
    for key in sorted(old.keys() | new.keys()):
        previous, current = old.get(key), new.get(key)
        row = current or previous
        label = row.get("details", {}).get("title") or row.get("kind", "Observation")
        if row.get("source") in failed and current is None:
            continue
        if current is None:
            kind, earlier, latest = "removed", label, "No longer listed (resolution unverified)"
        elif previous is None:
            kind, earlier, latest = "added", "Not in previous snapshot", label
        elif any(_semantic_value(previous, field) != _semantic_value(current, field) for field in
                 (("magnitude", "details") if row.get("kind") in {"highway_alert", "travel_delay", "transit_disruption"}
                  else ("magnitude", "starts_at", "ends_at", "details"))):
            kind = "changed"
            earlier = str(previous.get("details", {}).get("headline") or previous.get("details", {}).get("title") or label)[:240]
            latest = str(current.get("details", {}).get("headline") or label)[:240]
            if earlier == latest and previous.get("magnitude") != current.get("magnitude"):
                earlier += f" · signal {previous.get('magnitude')}"
                latest += f" · signal {current.get('magnitude')}"
        else:
            fetched = parse_time(current.get("fetched_at"))
            before_clock = parse_time(before.get("collected_at"))
            limit = 15 if row.get("kind") in {"highway_alert", "travel_delay", "transit_disruption"} else 1440
            if not (fetched and fetched.tzinfo and before_clock and before_clock.tzinfo
                    and (before_clock - fetched).total_seconds() <= limit * 60 < (now - fetched).total_seconds()):
                continue
            kind, earlier, latest = "aging", "Within freshness window", "Source data is now old"
        changes.append({"id":key, "kind":kind, "before":earlier, "now":latest,
                        "why":"Review the source and timing; this is not evidence of rider demand.",
                        "source":row.get("source"), "observed_at":row.get("fetched_at"), "evidence_ids":[key], "zone":row.get("zone")})
    return changes


def latest(area: str | None = None) -> dict:
    try:
        history = json.loads((cache_dir() / "awareness_history.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        history = []
    route_rows = route_diff(area) if area else []
    if len(history) < 2 and not route_rows:
        return {"changes":[], "detail":"Waiting for two collected snapshots.", "snapshots":len(history)}
    rows = diff(history[-2], history[-1]) if len(history) >= 2 else []
    if area:
        rows = [row for row in rows if row.get("zone") in {None, area}]
    rows = [*route_rows, *rows]
    return {"changes":rows[:20], "total":len(rows), "snapshots":len(history),
            "before_at":history[-2].get("collected_at") if len(history) >= 2 else None,
            "now_at":history[-1].get("collected_at") if len(history) >= 1 else None,
            "detail":"No meaningful observation changes." if not rows else "Changes in collected observations; coverage failures remain visible."}
