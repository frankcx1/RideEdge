"""Local privacy-reduced trip ledger from official WA receipt CSVs.

Never stores street addresses. field_data/ is gitignored. Under pytest the
ledger is skipped so tests do not depend on the driver's files.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from farol.dashboard import ROOT
from farol.history import read_local_trips, summarize_history
from farol.recommend import empty_miles_report, rank_next_hours
from farol.zones import canonical_zone, load_zones


def field_data_dir() -> Path:
    override = os.getenv("FAROL_FIELD_DATA_DIR")
    return Path(override) if override else ROOT / "field_data"


def load_observed_trips() -> list[dict]:
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("FAROL_USE_FIELD_TRIPS", "") != "1":
        return []
    directory = field_data_dir()
    if not directory.is_dir():
        return []
    return read_local_trips(directory)


def _cluster(zone: str) -> str:
    record = next((item for item in load_zones().zones if item.id == canonical_zone(zone)), None)
    if record is None:
        return "unknown"
    return record.cluster


def venue_observations() -> list[dict]:
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("FAROL_USE_FIELD_TRIPS", "") != "1":
        return []
    path = field_data_dir() / "venue_observations.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("observations", [])


def personal_insights(trips: list[dict] | None = None, vehicle_cost_per_mile: float = 0.45) -> dict:
    observed = trips if trips is not None else load_observed_trips()
    if not observed:
        return {
            "trips": 0,
            "status": "empty",
            "note": "Import Washington Trip Receipt CSVs to compare your past driving sessions.",
            "history": summarize_history([]),
        }
    earnings = sum(trip["earnings"] for trip in observed)
    tips = sum(trip.get("tip") or 0 for trip in observed)
    miles = sum(trip["paid_miles"] for trip in observed)
    minutes = sum(trip["duration_minutes"] for trip in observed)
    by_pickup: dict[str, list[dict]] = defaultdict(list)
    by_cluster: dict[str, list[dict]] = defaultdict(list)
    by_hour: dict[int, list[dict]] = defaultdict(list)
    wa_only = []
    seattle_miles = []
    for trip in observed:
        if float(trip.get("duration_minutes") or 0) <= 0:
            continue
        by_pickup[trip["pickup_zone"]].append(trip)
        by_cluster[_cluster(trip["pickup_zone"])].append(trip)
        hour = datetime.fromisoformat(trip["requested_at"]).hour
        by_hour[hour].append(trip)
        if trip.get("washington_miles", 0) > 0 and trip.get("seattle_miles", 0) == 0:
            wa_only.append(trip)
        if trip.get("seattle_miles", 0) > 0:
            seattle_miles.append(trip)

    def _bucket(items: list[dict]) -> dict:
        if not items:
            return {"trips": 0}
        total = sum(item["earnings"] for item in items)
        return {
            "trips": len(items),
            "earnings": round(total, 2),
            "mean_earnings": round(total / len(items), 2),
            "mean_miles": round(sum(item["paid_miles"] for item in items) / len(items), 2),
        }

    hour_means = sorted(
        (
            {"hour": hour, "mean_earnings": round(sum(t["earnings"] for t in items) / len(items), 2), "trips": len(items)}
            for hour, items in by_hour.items()
            if items
        ),
        key=lambda row: row["mean_earnings"],
        reverse=True,
    )
    pickup_means = sorted(
        (
            {"zone": zone, **_bucket(items)}
            for zone, items in by_pickup.items()
            if items
        ),
        key=lambda row: row.get("mean_earnings", 0),
        reverse=True,
    )
    first = observed[0]["requested_at"]
    last = observed[-1]["requested_at"]
    net = earnings - miles * vehicle_cost_per_mile
    return {
        "trips": len(observed),
        "completed_trip_count": sum(float(trip.get("duration_minutes") or 0) > 0 for trip in observed),
        "status": "thin" if len(observed) < 80 else "usable",
        "first_trip_at": first,
        "last_trip_at": last,
        "earnings": round(earnings, 2),
        "tips": round(tips, 2),
        "paid_miles": round(miles, 2),
        "on_trip_minutes": round(minutes, 2),
        "net_after_paid_mile_cost_lower_bound": round(net, 2),
        "mean_earnings": round(earnings / len(observed), 2),
        "tip_share_percent": round(100 * tips / earnings, 1) if earnings else 0,
        "by_pickup_cluster": {name: _bucket(items) for name, items in by_cluster.items()},
        "by_pickup_zone": pickup_means[:8],
        "best_hours": hour_means[:6],
        "wa_miles_only": _bucket(wa_only),
        "has_seattle_miles": _bucket(seattle_miles),
        "empty_miles": empty_miles_report(observed),
        "history": summarize_history(observed, vehicle_cost_per_mile),
        "venue_observations": venue_observations(),
        "note": (
            "Thin personal sample — treat as directional, not a demand forecast."
            if len(observed) < 80
            else "Personal priors from official WA receipts; streets reduced to zones."
        ),
    }


def sit_here(
    *,
    now: datetime,
    origin_zone: str = "kirkland_waterfront",
    hours: int = 3,
    value_of_time_per_hour: float = 22.0,
    vehicle_cost_per_mile: float = 0.45,
    trips: list[dict] | None = None,
    live_routes: dict[str, tuple[float, float]] | None = None,
) -> dict:
    observed = trips if trips is not None else load_observed_trips()
    return rank_next_hours(
        observed,
        now=now,
        origin_zone=origin_zone,
        hours=hours,
        value_of_time_per_hour=value_of_time_per_hour,
        vehicle_cost_per_mile=vehicle_cost_per_mile,
        live_routes=live_routes,
    )
