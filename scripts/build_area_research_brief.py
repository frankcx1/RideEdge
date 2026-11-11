"""Build the isolated October 26 research projection once; never publish it to radar.

Requires the saved eight-query study receipts. Retains per-field source pointers.
The saved home point is used in memory for estimates only, never serialized.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from farol import radar
from farol.adapters.base import read_cache
from farol.adapters.venues import load_venues
from farol.zones import load_zones
from scripts.research_area_opportunities import AREA_IDS

directory = Path(".cache/research/eastside-2026-10-26")
if (directory / "comparison-evidence.json").exists():
    raise SystemExit("The frozen study projection already exists; it was not overwritten.")
centers = {p.id: p for p in load_zones().pickup_centers}
home = radar.origin("Home")  # used only in memory; no private coordinates in artifacts
payload = {
    "review_time": datetime.now(UTC).isoformat(),
    "question": "Where should this driver move from a residential development to find the next rider?",
    "radius_rule": "All four centers must be evaluated; Now within 5 straight-line miles.",
    "limits": [
        "No Uber request counts or driver competition data.",
        "Percentages are relative to each venue own peak, not people counts or comparable capacities.",
        "Samples capped at 50 by provider default review-count order; counts are not neighborhood density.",
        "Live endpoint values describe the 8PM hour; underlying measurement timestamps absent.",
        "Typical patterns are not current observations. Zero means returned zero, not automatically closed.",
        "Google opening schedules were retained earlier today. openNow from that retrieval is not current.",
        "No measured residential occupancy, apartment density or late-shift workers in these feeds.",
        "Travel is estimated from the saved starting point, not current traffic. No private origin is included.",
    ],
    "venue_columns": [
        "id",
        "name",
        "type",
        "live_percent",
        "typical_8pm_9pm_10pm",
        "miles_from_center",
        "google_monday_hours",
    ],
    "areas": [],
}
provenance = {}
for aid in AREA_IDS:
    p = centers[aid]
    typical = json.loads((directory / f"{aid}-typical.json").read_text())
    live = json.loads((directory / f"{aid}-live.json").read_text())
    tv = typical["payload"]["venues"]
    lv = live["payload"]["venues"]
    tm = {v["venue_id"]: v for v in tv}
    lm = {v["venue_id"]: v for v in lv}
    google = []
    for venue in load_venues():
        cached = (
            read_cache("places_details_" + venue.get("place_id", ""))
            if venue.get("place_id")
            else None
        )
        if (
            cached
            and isinstance(venue.get("latitude"), (int, float))
            and radar.distance(p.latitude, p.longitude, venue["latitude"], venue["longitude"])
            <= 0.65
        ):
            hours = (
                cached.get("payload", {}).get("currentOpeningHours")
                or cached.get("payload", {}).get("regularOpeningHours")
                or {}
            )
            monday = next(
                (h for h in hours.get("weekdayDescriptions", []) if h.startswith("Monday")), None
            )
            google.append(
                (venue["name"].casefold(), monday, venue.get("place_id"), cached.get("fetched_at"))
            )
    area = {
        "id": aid,
        "name": p.label,
        "estimated_drive_minutes": radar.estimate_route(
            home, {"latitude": p.latitude, "longitude": p.longitude}
        )["minutes"],
        "straight_line_miles": round(
            radar.distance(home["latitude"], home["longitude"], p.latitude, p.longitude), 1
        ),
        "typical_returned": len(tv),
        "live_returned": len(lv),
        "query_radius_m": 1000,
        "retrieved_at": {"typical": typical["retrieved_at"], "live": live["retrieved_at"]},
        "venues": [],
        "omitted_zero_pattern_without_live": 0,
    }
    for vid in dict.fromkeys([*tm, *lm]):
        t = tm.get(vid)
        l = lm.get(vid)
        v = t or l
        whole = (t or l).get("day_raw_whole", [])
        ix = typical["payload"]["window"]["time_local_index"]
        pattern = whole[ix : ix + 3] if len(whole) == 24 else None
        raw_live = l.get("day_raw") if l else None
        value = (
            raw_live[0]
            if isinstance(raw_live, list)
            and len(raw_live) == 1
            and type(raw_live[0]) in (int, float)
            else None
        )
        if not l and pattern and all(n == 0 for n in pattern):
            area["omitted_zero_pattern_without_live"] += 1
            continue
        eid = f"v{len(provenance)}"
        hours = next((g[1] for g in google if g[0] == v["venue_name"].casefold()), None)
        area["venues"].append(
            [
                eid,
                v["venue_name"],
                v.get("venue_type"),
                value,
                pattern,
                round(radar.distance(p.latitude, p.longitude, v["venue_lat"], v["venue_lng"]), 2),
                hours,
            ]
        )
        provenance[eid] = {
            "venue_id": vid,
            "live": {"receipt": f"{aid}-live.json", "field": "venues[venue_id].day_raw[0]"}
            if l
            else None,
            "typical": {
                "receipt": f"{aid}-typical.json" if t else f"{aid}-live.json",
                "field": f"venues[venue_id].day_raw_whole[{ix}:{ix + 3}]",
            },
            "google": next(
                (
                    {
                        "cache_key": "places_details_" + g[2],
                        "field": "currentOpeningHours or regularOpeningHours.weekdayDescriptions.Monday",
                        "retrieved_at": g[3],
                    }
                    for g in google
                    if g[0] == v["venue_name"].casefold()
                ),
                None,
            ),
        }
    payload["areas"].append(area)
(directory / "comparison-evidence.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
)
(directory / "field-provenance.json").write_text(
    json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    json.dumps(
        [
            {k: v for k, v in a.items() if k != "venues"} | {"projected_rows": len(a["venues"])}
            for a in payload["areas"]
        ],
        indent=2,
    )
)
