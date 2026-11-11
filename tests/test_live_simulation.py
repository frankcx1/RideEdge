import json
from dataclasses import asdict, replace
from datetime import datetime
from unittest.mock import patch

import pytest

from farol.brain import constrain_narration, strip_supported_flight_rates
from farol.here import _drive_plain, advise, resolve
from farol.live_simulation import build_cases, render, safe_text
from farol.signals import Anchor, RouteEstimate, Signal
from farol.tonight import _bundle_value


@pytest.fixture
def captured():
    stamp = "2026-09-17T21:00:00-07:00"
    signal = Signal(
        "wamu-test", "event_exit", "sodo_stadiums", stamp, "2026-09-17T22:00:00-07:00",
        8000, "scheduled", "https://example.org/event", stamp,
        "2026-09-17T22:00:00-07:00", 0.7,
        {"title": "Test theater exit", "venue": "WAMU Theater"},
    )
    anchor = Anchor("sodo-demo", "sodo_stadiums", "demo", 47.59, -122.33,
                    "WATCH", "demo_only", "No approved curb")
    route = RouteEstimate("sodo_stadiums", "sodo-demo", 4, 1, 0.45, "live", "google", stamp)
    return {
        "version": 1, "as_of": stamp, "capture_started_at": stamp,
        "capture_finished_at": stamp, "hours": 3, "vehicle_cost_per_mile": 0.45,
        "signals": [asdict(signal)], "anchors": [asdict(anchor)],
        "feeds": [{"adapter": "test", "mode": "live", "signal_count": 1}],
        "locations": [{"id": "sodo", "label": "Test SODO", "pin": "47.5914,-122.3325",
                       "place": resolve("47.5914,-122.3325"), "routes": {"sodo-demo": asdict(route)},
                       "route_status": {"adapter": "google_routes_traffic", "mode": "live",
                                        "signal_count": 1}}],
    }


def test_offline_replay_never_fetches_or_reads_private_receipts(captured):
    with patch("farol.tonight.gather_signals", side_effect=AssertionError("network")), \
         patch("farol.adapters.routes.matrix", side_effect=AssertionError("network")), \
         patch("farol.here.load_observed_trips", side_effect=AssertionError("private")), \
         patch("farol.tonight.personal_insights", side_effect=AssertionError("private")):
        cases = build_cases(captured)
        assert build_cases(captured) == cases
    assert len(cases) == 4
    assert cases[0]["brief"]["shift_decision"]["action"] == "CHECK WINDOW"
    assert all(all(case["engine_checks"].values()) for case in cases)
    assert all(not item["navigation_available"] for case in cases for item in case["all_opportunities"])
    assert "4 min drive" in cases[0]["here"]["spoken"]


def test_faults_change_evidence_without_mutating_capture(captured):
    before = json.dumps(captured, sort_keys=True)
    cases = {case["variant"]: case for case in build_cases(captured)}
    outage = cases["all_sources_outage"]
    assert outage["brief"]["shift_decision"]["action"] == "NO CLEAR SIGNAL"
    assert not outage["all_opportunities"]
    assert all(feed["mode"] == "error" for feed in outage["brief"]["feeds"])
    assert cases["traffic_outage"]["all_opportunities"][0]["route"]["basis"] == "assumed"
    assert cases["missed_windows"]["all_opportunities"][0]["action"] == "AVOID"
    assert cases["missed_windows"]["brief"]["shift_decision"]["action"] == "NO CLEAR SIGNAL"
    assert json.dumps(captured, sort_keys=True) == before


def test_incomplete_capture_is_rejected(captured):
    captured["capture_finished_at"] = None
    with pytest.raises(ValueError, match="complete"):
        build_cases(captured)


def test_two_events_at_same_zone_and_time_keep_distinct_ids(captured):
    captured["signals"].append({**captured["signals"][0], "id": "other-theater"})
    case = build_cases(captured)[0]
    assert len(case["all_opportunities"]) == 2
    assert case["engine_checks"]["unique_opportunity_ids"]


def test_corridor_penalty_does_not_scale_with_copied_alert_count(captured):
    event = Signal(**captured["signals"][0])
    alert = replace(event, kind="highway_alert", magnitude=4)
    assert _bundle_value([event, alert]) == 4
    assert _bundle_value([event, *[replace(alert, id=str(n)) for n in range(50)]]) == 4
    assert _bundle_value([event, alert, replace(alert, magnitude=8)]) == 0


def test_espn_midnight_fetches_individual_days_and_deduplicates():
    from farol.adapters import espn_seattle

    start = datetime.fromisoformat("2026-09-17T22:00:00-07:00")
    end = datetime.fromisoformat("2026-09-18T01:00:00-07:00")
    with patch("farol.adapters.espn_seattle.fetch_json", return_value=({}, "live", start.isoformat())) as fetch:
        _, status = espn_seattle.fetch(start, end)
    assert status.mode == "live"
    assert fetch.call_count == 8
    assert all("20260917-20260918" not in call.args[0] for call in fetch.call_args_list)
    assert sum("dates=20260918" in call.args[0] for call in fetch.call_args_list) == 4


def test_watch_model_cannot_turn_road_closure_into_demand():
    from farol.adapters import grok_watch

    stamp = datetime.fromisoformat("2026-09-17T22:00:00-07:00")
    note = {"kind": "event_exit", "zone": "bellevue_core",
            "title": "I-405 road closure", "evidence_quality": 0.8}
    with patch.object(grok_watch, "extract_text", return_value="{}"), \
         patch.object(grok_watch, "extract_json_object", return_value={"notes": [note]}):
        signals = grok_watch.parse({}, stamp, stamp, fetched_at=stamp.isoformat())
    assert signals[0].kind == "driver_intel"
    assert signals[0].basis == "assumed"
    assert signals[0].details["reported_kind"] == "event_exit"
    assert signals[0].details["scoring_role"] == "advisory_only"


def test_frozen_plane_rate_is_not_treated_as_income(captured):
    brief = build_cases(captured)[0]["brief"]
    brief["opportunities"][0]["facts"].append({"kind": "airport_arrivals", "per_hour": 40})
    blob = {"headline": "CHECK WINDOW", "spoken": "20 planes observed, about 40 per hour.",
            "shift_rationale": "Review evidence", "now_move": "WATCH", "risks": [],
            "opportunity_notes": {}}
    assert constrain_narration(brief, blob)["spoken"] == blob["spoken"]
    blob["spoken"] = "Live data shows 40 planes landing per hour. The queue is unknown."
    assert constrain_narration(brief, blob)["spoken"] == blob["spoken"]
    blob["spoken"] = "20 planes between 9:15 p.m. and 9:45 p.m., averaging about 40 per hour."
    assert "per hour" not in strip_supported_flight_rates(blob["spoken"], brief["opportunities"])
    # Aviation rate is supported; these invented clock bounds are not.
    assert constrain_narration(brief, blob)["spoken"] != blob["spoken"]
    blob["spoken"] = "20 planes observed, about 60 per hour."
    assert constrain_narration(brief, blob)["spoken"] != blob["spoken"]
    text = "Planes nearby mean earnings of 40 per hour."
    assert strip_supported_flight_rates(text, brief["opportunities"]) == text


def test_event_queries_use_utc_and_include_shows_already_underway(monkeypatch):
    from urllib.parse import parse_qs, urlsplit

    from farol.adapters import seatgeek, ticketmaster

    start = datetime.fromisoformat("2026-09-17T21:39:00-07:00")
    end = datetime.fromisoformat("2026-09-18T00:39:00-07:00")
    monkeypatch.setenv("TICKETMASTER_API_KEY", "test-key")
    monkeypatch.setenv("SEATGEEK_CLIENT_ID", "test-key")
    for adapter, low, high in ((ticketmaster, "startDateTime", "endDateTime"),
                                (seatgeek, "datetime_utc.gte", "datetime_utc.lte")):
        with patch.object(adapter, "fetch_json", return_value=({}, "live", start.isoformat())) as fetch:
            adapter.fetch(start, end)
        query = parse_qs(urlsplit(fetch.call_args.args[0]).query)
        assert query[low] == ["2026-09-18T00:00:00Z"]
        assert query[high] == ["2026-09-18T08:00:00Z"]
    kickoff = seatgeek._kickoff({"datetime_utc": "2026-09-18T02:00:00"}, start.tzinfo)
    assert kickoff.isoformat() == "2026-09-17T19:00:00-07:00"


def test_same_zone_and_short_routes_are_not_zero_drive():
    assert "9 min drive" in _drive_plain(9, already_there=True)
    assert "1 min drive" in _drive_plain(1, already_there=True)
    assert "unknown" in _drive_plain(None, already_there=True)
    assert "already" in _drive_plain(0, already_there=True)


def test_missing_airport_feed_does_not_assert_plane_count():
    result = advise("SEA", now=datetime.fromisoformat("2026-09-17T21:00:00-07:00"), trips=[],
                    scored_window={"opportunities": [], "feeds": [
                        {"adapter": "flightaware_sea", "mode": "error", "signal_count": 0}]})
    assert "fewer than 3" not in result["spoken"]
    assert "max 15" not in result["spoken"]
    assert "Missing feed data" in result["spoken"]
    assert result["feeds"][0]["mode"] == "error"


def test_report_escapes_api_titles_and_redacts_secrets(captured, tmp_path, monkeypatch):
    monkeypatch.setenv("EXAMPLE_API_KEY", "simulated-secret-key")
    assert "simulated-secret-key" not in safe_text("error: simulated-secret-key")
    assert "hidden" not in safe_text("https://example.org?key=hidden&other=visible")
    captured["locations"][0]["label"] = '<script>alert("bad")</script>'
    report = {"scope": "test", "capture_started_at": captured["as_of"],
              "capture_finished_at": captured["as_of"], "route_elements_requested": 1,
              "feeds": captured["feeds"], "cases": build_cases(captured), "results": []}
    target = tmp_path / "report.html"
    render(report, target)
    document = target.read_text(encoding="utf-8")
    assert '<script>alert("bad")</script>' not in document
    assert "&lt;script&gt;" in document
    assert "data-filter='baseline'" in document
