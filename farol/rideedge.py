"""Isolated, deterministic Eastside demo using production signals and scoring."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from farol.signals import Anchor, RouteEstimate, Signal
from farol.tonight import ScoringSnapshot, score_window

SCENARIO = "eastside-evening-v1"
START = datetime.fromisoformat("2026-09-19T20:00:00-07:00")
AREAS = {"bellevue_core": "Bellevue", "kirkland_waterfront": "Kirkland", "capitol_hill": "Seattle"}


class Constraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minutes_available: int = Field(default=90, ge=15, le=240)
    reposition_under_minutes: int = Field(default=15, ge=1, le=60)
    finish_near: Literal["kirkland_waterfront", "bellevue_core", "capitol_hill", "none"] = "kirkland_waterfront"

    @field_validator("finish_near", mode="before")
    @classmethod
    def _normalize_finish_near(cls, value: object) -> str:
        if not isinstance(value, str):
            return str(value)
        cleaned = value.strip().lower()
        aliases = {
            "eastside": "kirkland_waterfront",
            "kirkland": "kirkland_waterfront",
            "kirkland waterfront": "kirkland_waterfront",
            "totem_lake": "kirkland_waterfront",
            "totem lake": "kirkland_waterfront",
            "redmond": "bellevue_core",
            "bellevue": "bellevue_core",
            "bellevue core": "bellevue_core",
            "seattle": "capitol_hill",
            "downtown seattle": "capitol_hill",
            "seattle_core": "capitol_hill",
            "slu": "capitol_hill",
            "capitol hill": "capitol_hill",
            "anywhere": "none",
            "any": "none",
            "": "none",
        }
        return aliases.get(cleaned, cleaned)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:24]


def scenario(step: int = 0) -> dict:
    if step not in {0, 1, 2}:
        raise ValueError("Unknown scenario step")
    now = START + timedelta(minutes=[0, 5, 30][step])
    fetched = START + timedelta(minutes=5 if step else 0)
    anchors, signals, routes, evidence = [], [], {}, []
    rows = [
        ("bellevue_core", "Lantern Hall", 47.6101, -122.2015, 20, 55, 22 if step else 8, 3.2, 8000),
        ("kirkland_waterfront", "Cedar Room", 47.6769, -122.206, 30, 65, 14, 6.1, 8000),
        ("capitol_hill", "Rainlight Hall", 47.614, -122.319, 25, 70, 25, 12.4, 14000),
    ]
    for zone, venue, lat, lon, start, end, minutes, miles, magnitude in rows:
        anchor = Anchor(f"demo-{zone}", zone, f"Fictional {venue}", lat, lon, "WATCH", "demo_only", "Synthetic location; no navigation or approved pickup curb.")
        signal = Signal(f"demo-event-{zone}", "event_exit", zone,
                        (START + timedelta(minutes=start)).isoformat(), (START + timedelta(minutes=end)).isoformat(),
                        magnitude, "scheduled", "synthetic:event-schedule", START.isoformat(),
                        (START + timedelta(hours=2)).isoformat(), .8,
                        {"title": f"Fictional {venue} show exit", "venue": f"Fictional {venue}", "exit_timing_basis":"synthetic estimated window"})
        route = RouteEstimate("bellevue_core", anchor.id, minutes, miles, round(miles * .45, 2),
                              "assumed", "synthetic:route-estimate", fetched.isoformat())
        anchors.append(anchor)
        signals.append(signal)
        dining = replace(signal, id=f"demo-dining-{zone}", kind="closing_wave", magnitude=4,
                         source="synthetic:neighborhood-schedule", details={"title":"Fictional neighborhood closing window"})
        signals.append(dining)
        routes[anchor.id] = route
        evidence.extend([
            {"id":signal.id, "kind":"event", "source":signal.source, "observed_at":signal.fetched_at, "synthetic":True, "text":signal.details["title"], "starts_at":signal.starts_at, "ends_at":signal.ends_at},
            {"id":f"demo-route-{zone}-{'b' if step else 'a'}", "kind":"route", "source":route.source, "observed_at":route.fetched_at, "synthetic":True, "text":f"{minutes} minute simulated route to {venue}", "minutes":minutes},
            {"id":dining.id, "kind":"dining", "source":dining.source, "observed_at":dining.fetched_at, "synthetic":True, "text":"Synthetic neighborhood closing signal; heuristic magnitude 4"},
        ])
    snapshot = ScoringSnapshot(signals, [{"adapter":"synthetic_routes", "source":"synthetic:route-estimate",
        "mode":"error" if step == 2 else "synthetic", "fetched_at":fetched.isoformat(), "signal_count":3,
        "detail":"Simulated route collection unavailable; previous observations retained" if step == 2 else "Fictional event and route inputs"}], anchors, routes)
    # Coordinates are a public area center. No personal history or preferences are loaded.
    scored = score_window(current=now, hours=1.5, vehicle_cost_per_mile=.45,
                          origin_zone="bellevue_core", origin_lat=47.6101, origin_lon=-122.2015,
                          include_llm=False, snapshot=snapshot)
    options = []
    for item in scored["ranked"]:
        if not item["primary_signal_id"].startswith("demo-event-"):
            continue
        route = routes[item["anchor"]["id"]]
        options.append({"id":item["primary_signal_id"], "zone":item["zone"], "area":AREAS[item["zone"]],
            "venue":item["venue_name"], "score":item["score"], "action":item["action"],
            "starts_at":item["starts_at"], "ends_at":item["ends_at"],
            "route_minutes":route.traffic_minutes if step < 2 else None,
            "last_route_minutes":route.traffic_minutes, "route_observed_at":route.fetched_at,
            "route_status":"unavailable; old observation retained" if step == 2 else "simulated estimate",
            "distance_miles":route.distance_miles, "vehicle_cost":route.vehicle_cost,
            "evidence_ids":[item["primary_signal_id"], f"demo-route-{item['zone']}-{'b' if step else 'a'}", f"demo-dining-{item['zone']}"],
            "audit":item["audit"]})
    context = {"scenario_id":SCENARIO, "step":step, "mode":"demo", "label":"Simulated scenario",
        "as_of":now.isoformat(), "session_started_at":START.isoformat(), "origin":"Bellevue public area center",
        "options":options, "evidence":evidence, "feeds":snapshot.feeds,
        "external_data_calls":0, "private_history_read":False, "navigation_available":False,
        "stay_put":"Remaining where you are is a zero-reposition baseline. The Bellevue venue still requires its own route.",
        "changes":[]}
    if step:
        context["changes"] = [{"id":"bellevue-route-change", "before":"8 min", "now":"22 min" if step == 1 else "Route unavailable",
            "why":"Bellevue no longer qualifies under 15 minutes." if step == 1 else "Route collection failed. Old estimates are not current travel times.",
            "evidence_ids":["demo-route-bellevue_core-a", "demo-route-bellevue_core-b"]}]
        # Preserve both timestamps and evidence versions for the before/after explanation.
        context["evidence"].extend(e for e in scenario(0)["evidence"] if e["kind"] == "route")
    context["snapshot_id"] = digest(context)
    return context


def compare(context: dict, constraints: Constraints) -> dict:
    now = datetime.fromisoformat(context["as_of"])
    deadline = datetime.fromisoformat(context["session_started_at"]) + timedelta(minutes=constraints.minutes_available)
    options = []
    for original in context["options"]:
        item = dict(original)
        minutes = item["route_minutes"]
        reasons = []
        if minutes is None:
            reasons.append("Current route time is unknown.")
        elif minutes >= constraints.reposition_under_minutes:
            reasons.append(f"{minutes:g} min does not meet under {constraints.reposition_under_minutes} min.")
        if minutes is not None and (now + timedelta(minutes=minutes) >= deadline or datetime.fromisoformat(item["starts_at"]) >= deadline):
            reasons.append("No usable window before the session deadline.")
        if minutes is not None and now + timedelta(minutes=minutes) > datetime.fromisoformat(item["ends_at"]):
            reasons.append("Arrival would miss this window.")
        if item["action"] == "AVOID" or item["score"] < 5:
            reasons.append("The engine does not show a strong reachable signal.")
        item.update(eligible=not reasons, reasons=reasons or ["Within the route limit and session window."],
                    finish_preference_match=item["zone"] == constraints.finish_near)
        options.append(item)
    # Finish is a soft tie-break only; never implies the destination of a passenger ride.
    options.sort(key=lambda item: (item["eligible"], item["score"], item["finish_preference_match"]), reverse=True)
    best = next((item for item in options if item["eligible"]), None)
    basis = "simulated " if context["mode"] == "demo" else "estimated "
    answer = f"Watch {best['area']}. {best['route_minutes']:g} min {basis}reposition." if best else "No qualifying move in this comparison. Staying put remains an option."
    changes = [dict(change) for change in context["changes"]]
    for change in changes:
        if change["id"] == "bellevue-route-change":
            bellevue = next(row for row in options if row["zone"] == "bellevue_core")
            change["why"] = ("Route collection failed; old estimates are not current. " if bellevue["route_minutes"] is None else "") + f"Bellevue: {' '.join(bellevue['reasons'])}"
    return {"constraints":constraints.model_dump(), "deadline":deadline.isoformat(), "options":options[:3], "changes":changes,
            "best_id":best["id"] if best else None, "answer":answer,
            "limits":"Signals are not rider demand or earnings forecasts. A finish preference cannot control a passenger's destination. Pickup access needs your review."}
