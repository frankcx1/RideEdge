"""Replay multi-stop driving flows offline using recorded public feeds.

Runs production HERE, scoring, adapters, and awareness without network/GPU calls.
Reports contain simulated public pins and optional local receipt aggregates.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import socket
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from farol.adapters import _doctrine_signals, onebusaway, venues
from farol.awareness import PACIFIC, build_view, timestamp
from farol.besttime import save
from farol.dashboard import FIXTURES, ROOT
from farol.here import advise, resolve
from farol.live_simulation import safe_text
from farol.signals import RouteEstimate, Signal, load_anchors
from farol.tonight import ScoringSnapshot, brief_from_scored, score_window
from farol.zones import load_zones

SCOPE = (
    "Offline test drives using real public locations and recorded API responses. "
    "Clock advances and movement are simulated; recorded source times are retained. "
    "Injected events, outages, and standing schedules are labeled at each step. "
    "No simulated Uber dispatch, rider counts, earnings forecasts, or approved pickup curbs. "
    "Local receipt aggregates may personalize HERE; raw receipt rows are not exported. "
    "AI narration is not part of this run."
)


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def offline():
    """Fail immediately if a replay accidentally attempts provider/model I/O."""
    with patch.object(socket.socket, "connect", side_effect=RuntimeError("Replay is offline")), \
            patch.object(socket.socket, "connect_ex", side_effect=RuntimeError("Replay is offline")):
        yield


def location_catalog(spec: dict, evening: dict) -> dict:
    captures = {item["id"]: item for item in evening["locations"]}
    catalog = {item["id"]: item for item in venues.load_venues()}
    registry = load_zones().by_id
    result = {}
    for item in spec["locations"]:
        location = dict(item)
        if "capture_id" in item:
            row = captures[item["capture_id"]]
            location.update(label=row["label"], pin=row["pin"], source="recorded location capture")
        elif "venue_id" in item:
            row = catalog[item["venue_id"]]
            location.update(label=row["name"], pin=f'{row["latitude"]},{row["longitude"]}',
                            source="existing venue catalog")
        elif "zone_id" in item:
            row = registry[item["zone_id"]]
            location.update(label=row.label, pin=f"{row.latitude},{row.longitude}",
                            source="area reference point; approximate")
        else:
            location["source"] = "controlled invalid input"
        result[item["id"]] = location
    return result


def scene_inputs(flow: dict, step: dict, inputs: dict, now: datetime) -> tuple[dict, str]:
    source = flow["source"]
    raw = inputs["evening"] if source == "evening" else inputs["daytime"]
    saved = {
        "collected_at": raw.get("capture_finished_at") or raw.get("collected_at"),
        "window_start": raw.get("as_of") or raw.get("window_start"),
        "window_end": raw.get("window_end") or (
            datetime.fromisoformat(raw["as_of"]) + timedelta(hours=raw["hours"])).isoformat(),
        "signals": copy.deepcopy(raw["signals"]), "feeds": copy.deepcopy(raw["feeds"]),
    }
    description = "Recorded feeds; only the public location and viewing clock are simulated."
    if source == "pilot_only":
        saved = {"collected_at": None, "signals": [], "feeds": []}
        description = "Actual saved BestTime pilot only; no general-feed capture exists for this clock."
    elif source == "evening" and inputs.get("transit_raw"):
        # Exercise today's parser on the original raw provider response, never refetch.
        cached = inputs["transit_raw"]
        parsed = onebusaway.parse(cached["payload"], timestamp(saved["window_start"]),
                                 timestamp(saved["window_end"]), fetched_at=cached["fetched_at"])
        saved["signals"] = [row for row in saved["signals"] if row["source"] != onebusaway.SOURCE]
        saved["signals"] += [asdict(row) for row in parsed]
        description += " Original OneBusAway response reparsed with the current adapter."
    variant = step.get("variant", flow.get("variant", "captured"))
    if variant == "standing_hours":
        catalog = [{**row, "source": "fixtures/venues.json standing schedule", "basis": "assumed"}
                   for row in venues.load_venues()]
        closing = venues.parse(now, now + timedelta(hours=6),
                               fetched_at=saved["collected_at"], venues=catalog)
        saved["signals"] = [row for row in saved["signals"] if row["kind"] != "closing_wave"]
        saved["signals"] += [asdict(row) for row in closing]
        description = ("Standing closing hours projected from the existing venue catalog. "
                       "BestTime uses its saved historical week. Daytime traffic remains recorded/old; "
                       "no evening API observations are manufactured.")
    if variant in {"theater", "concurrent_stadium"}:
        saved["signals"] = [row for row in saved["signals"] if not (
            row["zone"] == "sodo_stadiums" and row["kind"] in {"event_exit", "doctrine_penalty"})]
        theater = Signal("test-wamu", "event_exit", "sodo_stadiums", now.isoformat(),
                         (now + timedelta(minutes=45)).isoformat(), 8000, "assumed",
                         "simulation:controlled venue comparison", now.isoformat(),
                         (now + timedelta(minutes=45)).isoformat(), .5,
                         {"title": "TEST: theater exit at WAMU", "venue": "WAMU Theater",
                          "exit_timing_basis": "injected test window, not an observed event"})
        injected = [theater]
        if variant == "concurrent_stadium":
            injected.append(replace(theater, id="test-stadium", magnitude=50000,
                                    details={"title": "TEST: simultaneous stadium exit",
                                             "venue": "Lumen Field"}))
        doctrine = [replace(row, fetched_at=now.isoformat()) for row in _doctrine_signals(injected)]
        saved["signals"] += [asdict(row) for row in injected + doctrine]
        description = ("Controlled event injection at real venues: "
                       + ("WAMU alone." if variant == "theater" else "WAMU plus a large stadium exit.")
                       + " Identical clock/evidence at core and edge; no dispatch advantage is assumed.")
    if variant == "all_outage":
        saved["signals"] = []
        saved["feeds"] = [{**row, "mode": "error", "signal_count": 0} for row in saved["feeds"]]
        description = "Controlled complete feed outage; historical receipt aggregates remain available."
    elif variant == "traffic_outage":
        saved["signals"] = [row for row in saved["signals"]
                            if row["kind"] not in {"highway_alert", "travel_delay"}]
        saved["feeds"] = [{**row, "mode": "error", "signal_count": 0}
                          if row.get("adapter") == "wsdot_traffic" else row for row in saved["feeds"]]
        description = "Controlled traffic outage: remove traffic observations and captured route legs."
    return saved, description


def run_step(flow: dict, step: dict, location: dict, inputs: dict, now: datetime,
             trips: list[dict]) -> dict:
    checks = []
    def check(name, passed, detail=""):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    record = {"label": step["label"], "location": location, "at": now.isoformat(), "checks": checks}
    if location.get("expected_rejection"):
        lat, lon = map(float, location["pin"].split(","))
        for name, operation in (
            ("HERE rejects invalid GPS", lambda: resolve(location["pin"])),
            ("Around you rejects invalid GPS", lambda: build_view(None, now=now, latitude=lat, longitude=lon)),
        ):
            try:
                operation()
            except ValueError as error:
                check(name, True, str(error))
            else:
                check(name, False, "Invalid location was accepted")
        record.update(changes="Controlled invalid location input", rejected=True)
        return record
    place = resolve(location["pin"])
    check("Location maps to expected area", place["zone"] == location["expected_zone"], place["zone"])
    saved, description = scene_inputs(flow, step, inputs, now)
    variant = step.get("variant", flow.get("variant", "captured"))
    signals = [Signal(**row) for row in saved["signals"]]
    captured_location = next((row for row in inputs["evening"]["locations"]
                              if row["pin"] == location["pin"]), None)
    routes = {}
    if flow["source"] == "evening" and captured_location and variant not in {"traffic_outage", "all_outage"}:
        routes = {key: RouteEstimate(**row) for key, row in captured_location["routes"].items()}
    feeds = list(saved["feeds"])
    feeds.append({"adapter": "google_routes_traffic", "mode": "cache" if routes else "error",
                  "source": "recorded routes" if routes else "no recorded route for this point",
                  "fetched_at": None, "signal_count": len(routes)})
    scored = score_window(current=now, hours=6, vehicle_cost_per_mile=.45,
                          origin_zone=place["zone"], origin_lat=place["latitude"],
                          origin_lon=place["longitude"],
                          snapshot=ScoringSnapshot(signals, feeds, inputs["anchors"], routes))
    brief = brief_from_scored(scored, include_personal=False)
    here = advise(location["pin"], now=now, trips=trips, scored_window=scored)
    # Never mix a pilot report captured in the future into an earlier replay.
    besttime = inputs.get("besttime")
    if besttime and timestamp(besttime["finished_at"]) > now:
        besttime = None
    if variant == "all_outage":
        besttime = None
    area_view = build_view(saved, now=now, scope="nearby", area=place["zone"], radius=0,
                           besttime=besttime)
    pin_view = build_view(saved, now=now, scope="nearby", radius=3,
                          latitude=place["latitude"], longitude=place["longitude"], besttime=besttime)
    metro = build_view(saved, now=now, besttime=besttime)
    opportunities = brief["opportunities"]
    check("Local observations remain in the metro view",
          {row["id"] for row in area_view["observations"]} <= {row["id"] for row in metro["observations"]})
    check("Named-area filter keeps only local or metro-wide context", all(
        place["zone"] in row["zones"] or "all" in row["zones"] for row in area_view["observations"]))
    check("No unapproved navigation", all(not row["navigation_available"] for row in opportunities))
    check("No unsupported hourly earnings forecasts", all(row["expected_net_per_hour"] is None
                                                          for row in opportunities))
    check("Overlapping windows retain their own event headline", all(
        row["facts"] and row["facts"][0]["signal_id"] == row["primary_signal_id"]
        for row in opportunities))
    check("Ended windows cannot be recommended", all(row["action"] == "AVOID" for row in opportunities
                                                     if timestamp(row["ends_at"]) < now))
    stale_live = [row["id"] for row in opportunities if row["route"]["basis"] == "live" and not (
        timestamp(row["route"]["fetched_at"]) and
        -1 <= (now - timestamp(row["route"]["fetched_at"])).total_seconds() / 60 <= 15)]
    check("Old traffic legs are not represented as live", not stale_live,
          f"{len(stale_live)} opportunities used a live label outside its 15-minute freshness bound")
    unclear = [row["id"] for row in here["nearby"] if row["route_basis"] == "assumed"
               and not any(word in row["detail"].lower() for word in ("estimat", "unknown", "assumed"))]
    check("HERE says when driving time is estimated", not unclear,
          f"{len(unclear)} assumed-route cards omit an estimate/unknown label")
    airport = place["zone"] == "sea_airport"
    check("Airport and street cards remain separate", all(
        (row["zone"] == "sea_airport") == airport for row in here["nearby"]))
    if airport:
        check("Airport queue size remains unknown", "cannot see" in here["spoken"].lower())
    if step.get("expect_named_transit"):
        check("Alert naming Capitol Hill appears in Capitol Hill", any(
            row["layer"] == "transit" and "capitol hill" in row["title"].lower()
            for row in area_view["observations"]), "Reparsed real OneBusAway replacement-bus alert")
    if "expect_recent_live" in step:
        count = area_view["busyness_coverage"]["recent_live"]
        check("BestTime reading ages out of recent coverage", bool(count) == step["expect_recent_live"],
              f"{count} recent live readings")
    if variant == "all_outage":
        check("Outage yields no clear engine signal", brief["shift_decision"]["action"] == "NO CLEAR SIGNAL")
        check("Outage is not described as a quiet area", not area_view["observations"]
              and "Coverage may be incomplete" in area_view["empty_note"])
    if variant in {"theater", "concurrent_stadium"}:
        penalties = [row for row in signals if row.kind == "doctrine_penalty" and row.zone == "sodo_stadiums"]
        check("WAMU alone does not trigger stadium doctrine", all(
            row.details.get("shadowed_signal") != "test-wamu" for row in penalties))
        check("Concurrent stadium exit changes district caution",
              bool(penalties) == (variant == "concurrent_stadium"))
    record.update(changes=description, zone=place["zone"], variant=variant,
                  route_input="Captured legs at this exact reference pin" if routes else "No captured legs; estimates required",
                  here={key: here[key] for key in ("action", "action_plain", "spoken", "nearby", "stay", "best")},
                  decision=brief["shift_decision"], opportunities=opportunities,
                  awareness=area_view, metro_awareness=metro, metro_count=len(metro["observations"]),
                  pin_radius_count=len(pin_view["observations"]))
    return record


def run_suite(spec: dict, inputs: dict, trips: list[dict] | None = None) -> dict:
    locations = location_catalog(spec, inputs["evening"])
    clocks = {
        "evening": timestamp(inputs["evening"]["capture_finished_at"]).astimezone(PACIFIC),
        "daytime": timestamp(inputs["daytime"]["collected_at"]).astimezone(PACIFIC),
        "pilot": timestamp(inputs["besttime"]["finished_at"]).astimezone(PACIFIC),
    }
    clocks["friday_night"] = clocks["daytime"].replace(hour=20, minute=30, second=0, microsecond=0)
    # Select the Friday at/after the daytime snapshot rather than silently label another day Friday.
    clocks["friday_night"] += timedelta(days=(4 - clocks["friday_night"].weekday()) % 7)
    result = {"scope": SCOPE, "history_trips_used": len(trips or []), "flows": []}
    with offline():
        for flow in spec["flows"]:
            output = {key: flow[key] for key in ("id", "title", "purpose", "source")}
            output["steps"] = []
            previous = None
            for step in flow["steps"]:
                now = (clocks[flow["clock"]].astimezone(UTC)
                       + timedelta(minutes=step["minutes"])).astimezone(PACIFIC)
                row = run_step(flow, step, locations[step["location"]], inputs, now, trips or [])
                if previous and "awareness" in row and "awareness" in previous:
                    old = {x["id"] for x in previous["awareness"]["observations"]}
                    new = {x["id"] for x in row["awareness"]["observations"]}
                    row["since_previous_stop"] = {"new_observations": len(new - old),
                                                  "no_longer_shown": len(old - new),
                                                  "note": "Location, filter, and clock changes can all change this count."}
                row["passed"] = all(check["passed"] for check in row["checks"])
                output["steps"].append(row)
                previous = row
            output["passed"] = all(row["passed"] for row in output["steps"])
            result["flows"].append(output)
    steps = [step for flow in result["flows"] for step in flow["steps"]]
    checks = [check for step in steps for check in step["checks"]]
    result["summary"] = {"flows": len(result["flows"]), "steps": len(steps),
                         "steps_passed": sum(row["passed"] for row in steps),
                         "checks": len(checks), "checks_passed": sum(row["passed"] for row in checks),
                         "failures": [{"flow": flow["id"], "step": step["label"], **check}
                                      for flow in result["flows"] for step in flow["steps"]
                                      for check in step["checks"] if not check["passed"]]}
    return result


def load_inputs(evening: Path, daytime: Path, besttime: Path) -> tuple[dict, list[dict]]:
    raw = {"evening": read(evening), "daytime": read(daytime), "besttime": read(besttime)}
    if raw["evening"].get("version") != 1 or not raw["evening"].get("capture_finished_at"):
        raise ValueError("A completed evening capture is required")
    paths = [evening, daytime, besttime]
    transit_path = evening.parent / "feed-cache" / "onebusaway_st40_vehicles.json"
    if transit_path.exists():
        raw["transit_raw"] = read(transit_path)
        paths.append(transit_path)
    raw["anchors"] = load_anchors(FIXTURES / "anchors.json")
    if any(anchor.approval_status == "approved" for anchor in raw["anchors"]):
        # Replay never emits live navigation. Keep the actual registry untouched.
        raw["anchors"] = [replace(anchor, approval_status="demo_only") for anchor in raw["anchors"]]
    metadata = [{"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in paths]
    return raw, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evening", type=Path, required=True)
    parser.add_argument("--daytime", type=Path, required=True)
    parser.add_argument("--besttime", type=Path, required=True)
    parser.add_argument("--flows", type=Path, default=FIXTURES / "drive_flows.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--without-history", action="store_true")
    args = parser.parse_args()
    from farol.env import load_env
    from farol.trips import load_observed_trips

    load_env()
    try:
        inputs, metadata = load_inputs(args.evening, args.daytime, args.besttime)
        spec = read(args.flows)
        trips = [] if args.without_history else load_observed_trips()
        report = run_suite(spec, inputs, trips)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, safe_text(f"Could not run flows: {error}\n"))
    metadata.append({"path": str(args.flows.resolve()),
                     "sha256": hashlib.sha256(args.flows.read_bytes()).hexdigest()})
    for name in ("anchors.json", "venues.json", "zones.json"):
        path = FIXTURES / name
        metadata.append({"path": str(path.resolve()),
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    report.update(inputs=metadata, generated_at=datetime.now(UTC).isoformat())
    report["code_sha256"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                             for name in ("farol/drive_flows.py", "farol/here.py", "farol/tonight.py",
                                          "farol/awareness.py", "farol/adapters/onebusaway.py",
                                          "farol/static/drive_flows_report.html")}
    directory = args.output or ROOT / ".cache" / "drive-flows" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    cleaned = json.loads(safe_text(json.dumps(report, ensure_ascii=False)))
    save(directory / "report.json", cleaned)
    template = (ROOT / "farol" / "static" / "drive_flows_report.html").read_text(encoding="utf-8")
    encoded = json.dumps(cleaned, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    (directory / "report.html").write_text(template.replace("__FLOW_REPORT_JSON__", encoded), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Interactive report: {directory / 'report.html'}")
    if report["summary"]["failures"]:
        parser.exit(1)


if __name__ == "__main__":
    main()
