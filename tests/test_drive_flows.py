"""Portable replay and regression checks; no local captures, providers, or models needed."""

import copy
import json
import socket
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from farol.adapters import onebusaway
from farol.api import app
from farol.drive_flows import offline, run_suite
from farol.here import _drive_plain, resolve
from farol.signals import Anchor, RouteEstimate, Signal
from farol.tonight import _route_for

NOW = datetime.fromisoformat("2026-09-17T21:00:00-07:00")
ANCHOR = Anchor("test-capitol", "capitol_hill", "Test reference", 47.62, -122.32,
                "WATCH", "demo_only", "Test only")
ROUTE = RouteEstimate("capitol_hill", ANCHOR.id, 4, 1, .45, "live", "test:route", NOW.isoformat())


@pytest.mark.parametrize("stamp,expected", [
    (NOW.isoformat(), "live"),
    ((NOW - timedelta(minutes=15)).isoformat(), "live"),
    ((NOW - timedelta(minutes=15, seconds=1)).isoformat(), "assumed"),
    ((NOW + timedelta(minutes=2)).isoformat(), "assumed"),
    ("not-a-time", "assumed"),
    ("2026-09-17T21:00:00", "assumed"),
])
def test_route_freshness_boundary_and_bad_clocks(stamp, expected):
    route = replace(ROUTE, fetched_at=stamp)
    selected = _route_for(ANCHOR, None, {ANCHOR.id: route}, "capitol_hill", 47.623, -122.32,
                          .45, NOW.isoformat())
    assert selected.basis == expected
    if expected == "live":
        assert selected == route
    else:
        assert "no traffic feed" in selected.source


@pytest.mark.parametrize("pin", ["0.0,0.0", "91.0,-122.0", "-47.6,-122.3", "37.77,-122.42"])
def test_here_rejects_invalid_and_out_of_coverage_gps_before_scoring(pin):
    with patch("farol.here.score_window", side_effect=AssertionError("Must reject before scoring")):
        with pytest.raises(ValueError, match="coverage"):
            resolve(pin)
        response = TestClient(app).get("/api/here", params={"at": pin})
    assert response.status_code == 400


@pytest.mark.parametrize("minutes", [0, 1, 12])
def test_here_labels_assumed_drive_time_even_at_nearby_pins(minutes):
    line = _drive_plain(minutes, already_there=True, basis="assumed")
    assert "Estimated" in line and "current traffic unknown" in line
    assert "already there" not in line


def test_link_alert_keeps_capitol_hill_for_both_lines_and_deduplicates():
    end = NOW + timedelta(hours=1)
    alert = {"id": "test-bridge", "summary": {"value": "Link shuttle buses at Capitol Hill"},
             "allAffects": [{"routeId": "40_1LINE"}, {"routeId": "40_2LINE"}],
             "activeWindows": [{"from": int(NOW.timestamp() * 1000),
                                "to": int(end.timestamp() * 1000)}]}
    signals = onebusaway.parse({"data": {"references": {"situations": [alert]}}}, NOW, end,
                              fetched_at=NOW.isoformat())
    assert [row.zone for row in signals].count("capitol_hill") == 1
    assert {"sodo_stadiums", "bellevue_core"} <= {row.zone for row in signals}


def test_offline_guard_blocks_provider_connections():
    with offline(), socket.socket() as connection, pytest.raises(RuntimeError, match="offline"):
        connection.connect(("127.0.0.1", 1))


def sample_replay():
    stamp = NOW.isoformat()
    end = (NOW + timedelta(hours=3)).isoformat()
    signal = Signal("test-show", "event_exit", "capitol_hill", stamp, end, 8000, "scheduled",
                    "test:provider", stamp, end, .7, {"title": "Controlled show"})
    evening = {"version": 1, "as_of": stamp, "capture_finished_at": stamp, "hours": 3,
               "signals": [asdict(signal)], "feeds": [], "locations": [
                   {"id": "hill", "label": "Capitol Hill", "pin": "47.6231,-122.32",
                    "routes": {ANCHOR.id: asdict(ROUTE)}}]}
    inputs = {"evening": evening, "anchors": [ANCHOR],
              "daytime": {"collected_at": stamp, "window_start": stamp, "window_end": end,
                          "signals": [asdict(signal)], "feeds": []},
              "besttime": {"finished_at": stamp, "venues": []}}
    spec = {"locations": [{"id": "hill", "capture_id": "hill", "expected_zone": "capitol_hill"}],
            "flows": [{"id": "aging", "title": "Aging", "purpose": "Route and signal aging",
                       "source": "evening", "clock": "evening", "steps": [
                           {"location": "hill", "minutes": 0, "label": "Fresh"},
                           {"location": "hill", "minutes": 16, "label": "Old traffic"},
                           {"location": "hill", "minutes": 20, "variant": "all_outage", "label": "Outage"},
                           {"location": "hill", "minutes": 30, "label": "Recovery"},
                           {"location": "hill", "minutes": 190, "label": "Ended"}]}]}
    return spec, inputs


def test_replay_is_deterministic_and_does_not_mutate_recorded_evidence():
    spec, inputs = sample_replay()
    original = copy.deepcopy(inputs)
    with patch("farol.tonight.gather_signals", side_effect=AssertionError("No new feeds")), \
         patch("farol.adapters.routes.matrix", side_effect=AssertionError("No new routes")), \
         patch("farol.here.load_observed_trips", side_effect=AssertionError("Explicit history only")):
        report = run_suite(spec, inputs)
        assert report == run_suite(spec, inputs)
    assert inputs == original
    assert report["summary"]["failures"] == []
    fresh, aged, outage, restored, ended = report["flows"][0]["steps"]
    assert fresh["opportunities"][0]["route"]["basis"] == "live"
    assert aged["opportunities"][0]["route"]["basis"] == "assumed"
    assert restored["opportunities"][0]["route"]["basis"] == "assumed"
    assert outage["decision"]["action"] == "NO CLEAR SIGNAL"
    assert ended["opportunities"][0]["action"] == "AVOID"
    assert not ended["awareness"]["observations"]
    assert report["history_trips_used"] == 0
    assert "requested_at" not in json.dumps(report)


def test_replay_never_borrows_recorded_routes_from_a_nearby_pin():
    spec, inputs = sample_replay()
    spec["locations"] = [{"id": "nearby", "zone_id": "capitol_hill", "expected_zone": "capitol_hill"}]
    spec["flows"][0]["steps"] = [{"location": "nearby", "minutes": 0, "label": "Uncaptured pin"}]
    step = run_suite(spec, inputs)["flows"][0]["steps"][0]
    assert "No captured legs" in step["route_input"]
    assert step["opportunities"][0]["route"]["basis"] == "assumed"


def test_overlapping_shows_keep_their_own_title_in_here_cards():
    spec, inputs = sample_replay()
    spec["flows"][0]["steps"] = spec["flows"][0]["steps"][:1]
    original = inputs["evening"]["signals"][0]
    inputs["evening"]["signals"].append({**original, "id": "second-show",
        "starts_at": (NOW + timedelta(minutes=30)).isoformat(),
        "details": {"title": "Second show at another venue"}})
    step = run_suite(spec, inputs)["flows"][0]["steps"][0]
    assert len(step["here"]["nearby"]) == 2
    assert any("Second show at another venue" in row["plain"] for row in step["here"]["nearby"])
