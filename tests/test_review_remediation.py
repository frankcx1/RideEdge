"""Independent regression tests verifying review findings R01-R24 and follow-up findings F01-F08."""

from __future__ import annotations

import copy
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_FEEDS", "1")
    monkeypatch.setenv("FAROL_COLLECT", "0")
    monkeypatch.setenv("FAROL_GROK_IN_MOCK", "0")
    monkeypatch.setenv("FAROL_LOCAL_URL", "http://127.0.0.1:1/v1/chat/completions")
    monkeypatch.setenv("FAROL_USE_FIELD_TRIPS", "1")
    monkeypatch.setenv("FAROL_FIELD_DATA_DIR", str(tmp_path / "field"))
    monkeypatch.setenv("FAROL_CACHE_DIR", str(tmp_path / "cache"))


def test_f01_r01_real_ranker_empty_trips_preserves_unknown_rates_and_measured_zero() -> None:
    from farol import course

    now = datetime(2026, 10, 21, 20, 0, tzinfo=UTC)
    with ExitStack() as s:
        s.enter_context(patch.object(course, "_read_json", return_value={}))
        s.enter_context(patch.object(course, "seatac_6h_forecast", return_value={"hours": []}))
        s.enter_context(patch.object(course, "load_observed_trips", return_value=[]))
        s.enter_context(patch.object(course, "load_anchors", return_value=[]))
        s.enter_context(patch.object(course, "nearby_train_stations", return_value=[]))
        s.enter_context(patch.object(course, "feed_health_view", return_value={}))

        # Deliberately exercise the real sit_here -> rank_next_hours path with 0 trips
        empty = course.build_6h_shift_course(pull_all=False, now=now)
        assert [st["expected_net_per_hour"] for st in empty["stops"]] == [None] * 6
        assert all(st["rate_basis"] == "unknown" and st["sample_trips"] == 0 for st in empty["stops"])
        assert all(st["navigation_available"] is False and st["maps_url"] == "" for st in empty["stops"])
        assert "earnings unknown" in empty["action_plan"]["immediate_move"]
        assert "Stage at" not in empty["action_plan"]["immediate_move"]
        assert "9:20 PM" not in json.dumps(empty["action_plan"])

        # Genuine observed zero-dollar trip history (sample_trips > 0, net == 0.0)
        zero_trips = [
            {
                "requested_at": "2026-10-14T13:10:00-07:00",
                "ended_at": "2026-10-14T13:30:00-07:00",
                "pickup_zone": "bellevue_core",
                "dropoff_zone": "bellevue_core",
                "duration_minutes": 20.0,
                "paid_miles": 10.0,
                "earnings": 4.50,  # 4.50 - 10 * 0.45 = 0.0 net
            },
            {
                "requested_at": "2026-10-07T13:15:00-07:00",
                "ended_at": "2026-10-07T13:35:00-07:00",
                "pickup_zone": "bellevue_core",
                "dropoff_zone": "bellevue_core",
                "duration_minutes": 20.0,
                "paid_miles": 10.0,
                "earnings": 4.50,
            },
        ]
        with patch.object(course, "load_observed_trips", return_value=zero_trips):
            measured_zero = course.build_6h_shift_course(pull_all=False, now=now)
        assert measured_zero["stops"][0]["expected_net_per_hour"] == 0.0
        assert measured_zero["stops"][0]["sample_trips"] == 2
        assert measured_zero["stops"][0]["rate_basis"] == "paid_trip_time_only"

        # Positive receipt-only rate retains paid-trip qualifier and does not stage at unapproved curb
        pos_trips = [
            {**t, "earnings": 24.50}
            for t in zero_trips
        ]
        with patch.object(course, "load_observed_trips", return_value=pos_trips):
            pos_course = course.build_6h_shift_course(pull_all=False, now=now)
        assert pos_course["stops"][0]["expected_net_per_hour"] == 60.0
        assert pos_course["stops"][0]["rate_basis"] == "paid_trip_time_only"
        assert "paid-trip archive (2 trips)" in pos_course["action_plan"]["immediate_move"]
        assert "Stage at" not in pos_course["action_plan"]["immediate_move"]


def test_f02_r04_ai_validator_and_live_formatter_reject_ungrounded_claims_and_models() -> None:
    from farol import course

    now = datetime(2026, 10, 21, 20, 0, tzinfo=UTC)
    with ExitStack() as s:
        s.enter_context(patch.object(course, "_read_json", return_value={}))
        s.enter_context(patch.object(course, "seatac_6h_forecast", return_value={"hours": []}))
        s.enter_context(patch.object(course, "load_observed_trips", return_value=[]))
        s.enter_context(patch.object(course, "load_anchors", return_value=[]))
        s.enter_context(patch.object(course, "nearby_train_stations", return_value=[]))
        s.enter_context(patch.object(course, "feed_health_view", return_value={}))
        base_course = course.build_6h_shift_course(pull_all=False, now=now)

    evidence_stops = copy.deepcopy(base_course["stops"])
    evidence_stops[0]["expected_net_per_hour"] = 32.0
    evidence_stops[0]["sample_trips"] = 4
    evidence_stops[0]["hot_venues"] = ["Tavern Hall (75%)"]

    invented = {
        "headline": "Bellevue core: take the next demand wave",
        "immediate_move": "Leave Bellevue now and stage at Fictional Pier in Tacoma.",
        "mid_shift_pivot": "Drive to Everett at 9:45 PM for a stadium sellout.",
        "airport_and_late_bank": "Sea-Tac has 75 incoming flights; FIFO wait is only 5 minutes.",
        "tactical_watchouts": "The destination curb is approved and all roads are clear.",
    }
    assert course._validate_llm_action_plan(invented, evidence_stops, 0) is False

    # Exercise live formatting branch and assert mocked session & transport are called
    for model_id in ("expected-model", "qwen-unrelated-model", ""):
        payload = {"model": model_id, "choices": [{"message": {"content": json.dumps(invented)}}]}
        with patch.object(
            course.local_runtime,
            "settings",
            return_value=("http://127.0.0.1:1234/v1/chat/completions", "expected-model"),
        ), patch.object(
            course.local_runtime, "session", return_value=nullcontext()
        ) as sess_mock, patch.object(
            course, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())
        ) as req_mock, patch.object(course, "save"):
            plan, _, used_model, _ = course._generate_formatted_action_plan(
                origin_label="Bellevue",
                stops=evidence_stops,
                top_hotspots=[],
                fa_forecast={},
                fa_total_planes=0,
                train_stations=[],
                run_live_llm=True,
            )
        assert sess_mock.call_count == 1
        assert req_mock.call_count == 1
        assert used_model == "RideEdge Tactical Formatter"
        assert plan != invented
        assert "Tacoma" not in json.dumps(plan)

    # Verify free-form prose dicts are rejected even if text looks plausible,
    # and only a valid structured stop-ID selection from the expected model is accepted.
    prose_plan = {
        "headline": "Bellevue core · Hold on Tavern Hall activity",
        "immediate_move": "[1:00 PM – 2:00 PM] Hold in Bellevue core (~$32/hr paid-trip archive). Tavern Hall (75%).",
        "mid_shift_pivot": "Stay in Bellevue core during the afternoon window and monitor local venues.",
        "airport_and_late_bank": "Sea-Tac has 0 flights loaded in the current snapshot; skip airport queue.",
        "tactical_watchouts": "No approved curb is active; keep navigation gated until approved.",
    }
    assert course._validate_llm_action_plan(prose_plan, evidence_stops, 0) is False

    valid_selection = {
        "mode": "structured_selection",
        "immediate_stop_id": "stop_0",
        "pivot_stop_id": "stop_1",
        "late_stop_id": "stop_5",
    }
    assert course._validate_llm_action_plan(valid_selection, evidence_stops, 0) is True
    expected_rendered = course.render_bound_action_plan(
        valid_selection,
        evidence_stops,
        0,
        origin_label="Bellevue",
    )
    assert expected_rendered is not None
    valid_payload = {"model": "expected-model", "choices": [{"message": {"content": json.dumps(valid_selection)}}]}
    with patch.object(
        course.local_runtime,
        "settings",
        return_value=("http://127.0.0.1:1234/v1/chat/completions", "expected-model"),
    ), patch.object(
        course.local_runtime, "session", return_value=nullcontext()
    ) as sess_mock, patch.object(
        course, "urlopen", return_value=io.BytesIO(json.dumps(valid_payload).encode())
    ) as req_mock, patch.object(course, "save"):
        plan, _, used_model, _ = course._generate_formatted_action_plan(
            origin_label="Bellevue",
            stops=evidence_stops,
            top_hotspots=[],
            fa_forecast={},
            fa_total_planes=0,
            train_stations=[],
            run_live_llm=True,
        )
    assert sess_mock.call_count == 1
    assert req_mock.call_count == 1
    assert used_model == "expected-model"
    assert plan == expected_rendered


def test_f03_r09_concurrent_besttime_refreshes_preserve_fresh_values_over_baseline(tmp_path: Path) -> None:
    from farol import besttime_live
    from farol.zones import canonical_zone, load_zones

    registry = load_zones()

    def _first_venue(area: str) -> dict:
        center = registry.by_id[canonical_zone(area)]
        return sorted(
            besttime_live.BESTTIME_UBER_VENUES,
            key=lambda v: (
                0 if v["zone"] == center.id else 1,
                besttime_live._distance_miles(center.latitude, center.longitude, v["latitude"], v["longitude"]),
            ),
        )[0]

    east = _first_venue("Bellevue")
    west = _first_venue("Seattle")
    baseline = {
        "venues": [
            {"requested": east, "forecast": {}, "live": {"busyness": 10, "retrieved_at": "2026-10-21T19:00:00Z"}},
            {"requested": west, "forecast": {}, "live": {"busyness": 10, "retrieved_at": "2026-10-21T19:00:00Z"}},
        ]
    }
    gate = Barrier(2)
    east_saved = Event()
    writes: list[dict] = []

    def read_report(path: Path):
        if path.name == "report.json":
            gate.wait(timeout=10)
            return copy.deepcopy(baseline)
        return None

    def post(endpoint: str, params: dict, *args):
        if params["venue_name"] == west["name"]:
            assert east_saved.wait(10), "Bellevue publish timed out"
        return {"http_status": 200, "payload": {}}

    def save_report(path: Path, value: dict):
        if path.name == "report.json":
            writes.append(copy.deepcopy(value))
            east_saved.set()

    with ExitStack() as s:
        s.enter_context(patch.dict(os.environ, BESTTIME_API_KEY_PRIVATE="test", BESTTIME_API_KEY_PUBLIC="test"))
        s.enter_context(patch.object(besttime_live, "_active_dir", return_value=tmp_path / "besttime"))
        s.enter_context(patch.object(besttime_live, "_read_json", side_effect=read_report))
        s.enter_context(patch.object(besttime_live, "_bt_post", side_effect=post))
        s.enter_context(patch.object(besttime_live, "normalize_forecast", return_value={}))
        s.enter_context(
            patch.object(
                besttime_live,
                "normalize_live",
                return_value={"busyness": 80, "retrieved_at": "2026-10-21T20:00:00Z"},
            )
        )
        s.enter_context(patch.object(besttime_live, "_merge_radar_hotspots", return_value=0))
        s.enter_context(patch.object(besttime_live, "_inject_besttime_signals_into_snapshot"))
        s.enter_context(patch.object(besttime_live, "_PUBLISHED_BY_CONTEXT", {}))
        s.enter_context(patch.object(besttime_live, "save", side_effect=save_report))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(
                pool.map(
                    lambda area: besttime_live.poll_besttime_venues(area, max_venues=1),
                    ["Bellevue", "Seattle"],
                )
            )

    final_by_id = {v["requested"]["id"]: v["live"]["busyness"] for v in writes[-1]["venues"]}
    assert final_by_id == {east["id"]: 80, west["id"]: 80}


def test_f04_r13_navigation_requires_live_approved_anchor_and_valid_expiry() -> None:
    from farol import navigation, tonight
    from farol.signals import Anchor

    valid_end = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    opp = {
        "id": "followup-test",
        "action": "MOVE",
        "navigation_available": True,
        "ends_at": valid_end,
        "anchor": {
            "id": "curb-1",
            "label": "Test Curb",
            "approval_status": "approved",
            "latitude": 47.61,
            "longitude": -122.20,
        },
    }

    # 1. Deleted/absent anchor in authoritative store -> rejected
    navigation.remember_brief({"mode": "LIVE", "opportunities": [opp]})
    with patch.object(tonight, "load_anchors", return_value=[]):
        with pytest.raises(ValueError, match="driver-approved anchor"):
            navigation.command_from_opportunity("followup-test", 0.45)

    # 2. Unreadable anchor store -> rejected
    navigation.remember_brief({"mode": "LIVE", "opportunities": [opp]})
    with patch.object(tonight, "load_anchors", side_effect=OSError("Synthetic unreadable store")):
        with pytest.raises(ValueError, match="readable driver-approved anchor store"):
            navigation.command_from_opportunity("followup-test", 0.45)

    # 3. Revoked approval in authoritative store -> rejected
    revoked_anc = Anchor("curb-1", "bellevue_core", "Test Curb", 47.61, -122.20, "MOVE", "pending", "notes")
    navigation.remember_brief({"mode": "LIVE", "opportunities": [opp]})
    with patch.object(tonight, "load_anchors", return_value=[revoked_anc]):
        with pytest.raises(ValueError, match="driver-approved anchor"):
            navigation.command_from_opportunity("followup-test", 0.45)

    # 4. Missing, malformed, and elapsed expiry -> rejected
    approved_anc = replace(revoked_anc, approval_status="approved")
    for bad_end, err_match in (
        (None, "expiration window"),
        ("not-a-timestamp", "expiration window"),
        ("2020-01-01T00:00:00Z", "already ended"),
    ):
        bad_opp = {**opp, "ends_at": bad_end}
        navigation.remember_brief({"mode": "LIVE", "opportunities": [bad_opp]})
        with patch.object(tonight, "load_anchors", return_value=[approved_anc]):
            with pytest.raises(ValueError, match=err_match):
                navigation.command_from_opportunity("followup-test", 0.45)


def test_f05_r08_stale_typical_this_hour_and_radar_freshness() -> None:
    from farol import besttime_live, course
    from farol.zones import load_zones

    now = datetime(2026, 10, 21, 20, 0, tzinfo=UTC)
    for bad_stamp in (
        "2020-01-01T00:00:00Z",
        (now - timedelta(hours=3)).isoformat(),
        (now + timedelta(hours=2)).isoformat(),
        None,
    ):
        stale_venue = {
            "requested": {"zone": "bellevue_core", "name": "Old Hour Test Venue"},
            "forecast": {},
            "live": {
                "available": True,
                "busyness": 95,
                "typical_this_hour": 95,
                "retrieved_at": bad_stamp,
            },
        }
        with ExitStack() as s:
            s.enter_context(
                patch.object(
                    course,
                    "_read_json",
                    side_effect=lambda p, v=stale_venue: {"venues": [v]} if p.name == "report.json" else {},
                )
            )
            s.enter_context(patch.object(course, "seatac_6h_forecast", return_value={"hours": []}))
            s.enter_context(patch.object(course, "load_observed_trips", return_value=[]))
            s.enter_context(patch.object(course, "load_anchors", return_value=[]))
            s.enter_context(patch.object(course, "nearby_train_stations", return_value=[]))
            s.enter_context(patch.object(course, "feed_health_view", return_value={}))
            res = course.build_6h_shift_course(pull_all=False, now=now)
        assert res["stops"][0]["score"] == 0.0
        assert "Old Hour Test Venue" not in res["stops"][0]["primary_trigger"]

    # Radar refreshes existing venue busyness and does not restamp 10-day-old reading
    radar = {
        "status": "OK",
        "venues": [
            {
                "venue_id": "review",
                "venue_name": "Synthetic Review Venue",
                "venue_address": "Public test place",
                "venue_type": "BAR",
                "venue_lat": 47.6155,
                "venue_lng": -122.2015,
                "day_raw": [75] * 24,
                "venue_live_busyness": 80,
            }
        ]
    }
    by_id: dict[str, dict] = {}
    kwargs = dict(
        by_id=by_id,
        lat=47.6155,
        lon=-122.2015,
        radius_m=1000,
        private_key="test",
        public_key="test",
        registry=load_zones(),
    )
    with patch.object(besttime_live, "urlopen", return_value=io.BytesIO(json.dumps(radar).encode())):
        besttime_live._merge_radar_hotspots(now=now, **kwargs)
    radar["venues"][0]["venue_live_busyness"] = 10
    with patch.object(besttime_live, "urlopen", return_value=io.BytesIO(json.dumps(radar).encode())):
        besttime_live._merge_radar_hotspots(now=now + timedelta(days=1), **kwargs)
    entry = next(iter(by_id.values()))
    assert entry["live"]["busyness"] == 10

    saved_snapshots: list[dict] = []
    with patch.object(besttime_live, "_read_json", return_value={"signals": [], "schema": 1}), patch.object(
        besttime_live, "save", side_effect=lambda p, v: saved_snapshots.append(copy.deepcopy(v))
    ):
        besttime_live._inject_besttime_signals_into_snapshot([entry], now + timedelta(days=10))
    assert saved_snapshots[0]["signals"] == []


def test_f06_android_source_enforces_fresh_gps_and_request_generations() -> None:
    kt_path = Path(__file__).resolve().parents[1] / "android/app/src/main/java/com/rideedge/app/MainActivity.kt"
    source = kt_path.read_text(encoding="utf-8")
    # Every fetchShiftCourse call with coordinates uses freshGps, never raw lastGpsLat
    assert "latitude = lastGpsLat" not in source
    assert "longitude = lastGpsLon" not in source
    assert "var courseReqGen by remember" in source
    assert "if (reqId != hereReqGen)" in source
    assert "RECHECK NOW (OVERDUE)" in source


def test_f07_r23_http_request_accounting_for_collector_and_empty_radar(tmp_path: Path) -> None:
    from farol import besttime_live, course

    # 1. Collector returning list[dict] is counted accurately
    with patch.object(course, "_read_json", return_value={}), patch.object(
        course, "poll_besttime_venues", return_value={"http_requests_made": 0}
    ), patch.object(course, "seatac_6h_forecast", return_value={"cached": True, "hours": []}), patch.object(
        course, "refresh_once", return_value=[{"adapter": "nws_live_observation", "mode": "live"}]
    ):
        blast = course._fire_all_apis_parallel("Bellevue", True)
    assert blast["push_refreshed"] is True
    assert blast["live_http_requests"] == 1

    # 2. Radar HTTP request returning 0 qualifying venues still counts 1 radar HTTP request
    with ExitStack() as s:
        s.enter_context(patch.dict(os.environ, BESTTIME_API_KEY_PRIVATE="test", BESTTIME_API_KEY_PUBLIC="test"))
        s.enter_context(patch.object(besttime_live, "_active_dir", return_value=tmp_path / "bt_empty_radar"))
        s.enter_context(patch.object(besttime_live, "_is_fresh", return_value=True))
        s.enter_context(patch.object(besttime_live, "_read_json", return_value={"http_status": 200}))
        s.enter_context(patch.object(besttime_live, "normalize_forecast", return_value={}))
        s.enter_context(patch.object(besttime_live, "normalize_live", return_value={}))
        s.enter_context(
            patch.object(besttime_live, "urlopen", return_value=io.BytesIO(json.dumps({"venues": []}).encode()))
        )
        s.enter_context(patch.object(besttime_live, "_inject_besttime_signals_into_snapshot"))
        s.enter_context(patch.object(besttime_live, "save"))
        res = besttime_live.poll_besttime_venues("Bellevue", max_venues=1, force_live=False)
    assert res["radar_hotspots_found"] == 0
    assert res["radar_requests"] == 1
    assert res["http_requests_made"] == 1


def test_driver_outcome_feedback_loop_and_retention(tmp_path: Path) -> None:
    from farol import history, recommend

    now = datetime(2026, 10, 21, 20, 0, tzinfo=UTC)
    # Verify more than 500 outcomes are retained without truncation
    for idx in range(510):
        history.log_driver_outcome(
            status="waiting" if idx % 2 == 0 else "request_received",
            zone="bellevue_core",
            recommendation_id=f"rec-{idx}",
            recorded_at=(now - timedelta(minutes=600 - idx)).isoformat(),
            directory=tmp_path,
        )
    all_outcomes = history.read_driver_outcomes(directory=tmp_path, limit=None)
    assert len(all_outcomes) == 510
    assert all_outcomes[-1]["recommendation_id"] == "rec-509"

    # Verify waiting -> ping vs dry waiting adjusts zone ranking scores
    out_dir = tmp_path / "feedback"
    history.log_driver_outcome(
        "waiting", "kirkland_waterfront", recorded_at="2026-10-21T19:00:00Z", directory=out_dir
    )
    history.log_driver_outcome(
        "repositioned", "kirkland_waterfront", recorded_at="2026-10-21T19:25:00Z", directory=out_dir
    )
    history.log_driver_outcome(
        "waiting", "bellevue_core", recorded_at="2026-10-21T19:30:00Z", directory=out_dir
    )
    history.log_driver_outcome(
        "accepted_ride", "bellevue_core", recorded_at="2026-10-21T19:34:00Z", directory=out_dir
    )
    summaries = history.summarize_zone_outcomes(directory=out_dir, now=now)
    assert summaries["bellevue_core"]["score_adjustment"] > 0
    assert summaries["kirkland_waterfront"]["score_adjustment"] < 0

    ranked = recommend.rank_next_hours(
        [],
        now=now,
        origin_zone="bellevue_core",
        hours=1,
        outcome_summaries=summaries,
    )["ranked"]
    bel = next(r for r in ranked if r["zone"] == "bellevue_core")
    kirk = next(r for r in ranked if r["zone"] == "kirkland_waterfront")
    assert bel["outcome_adjustment"] > 0
    assert kirk["outcome_adjustment"] < 0


def test_remaining_review_findings_r03_r05_r07_r10_to_r22(tmp_path: Path) -> None:
    from farol import collect, course, evidence, history
    from farol.adapters import flightaware, onebusaway, routes, weather_live
    from farol.api import app
    from farol.ingest import _zone
    from farol.signals import Anchor, Signal

    now = datetime(2026, 10, 21, 20, tzinfo=UTC)

    # R03: Negative context-only doctrine penalty is never promoted as a positive trigger
    fake_signal = {
        "zone": "bellevue_core",
        "kind": "doctrine_penalty",
        "magnitude": 18,
        "starts_at": (now - timedelta(hours=1)).isoformat(),
        "ends_at": (now + timedelta(hours=8)).isoformat(),
        "details": {"context_only": True, "title": "Synthetic convergence penalty"},
    }
    with ExitStack() as s:
        s.enter_context(
            patch.object(
                course,
                "_read_json",
                side_effect=lambda p: {"signals": [fake_signal]} if p.name == "awareness_snapshot.json" else {},
            )
        )
        s.enter_context(patch.object(course, "seatac_6h_forecast", return_value={"hours": []}))
        s.enter_context(patch.object(course, "load_observed_trips", return_value=[]))
        s.enter_context(patch.object(course, "load_anchors", return_value=[]))
        s.enter_context(patch.object(course, "nearby_train_stations", return_value=[]))
        s.enter_context(patch.object(course, "feed_health_view", return_value={}))
        boosted = course.build_6h_shift_course(pull_all=False, now=now)
    assert boosted["stops"][0]["score"] <= 0.0
    assert "Synthetic convergence penalty" not in boosted["stops"][0]["primary_trigger"]

    # R05: Unbounded plan cache rejects stale/mismatched area plan
    with patch.object(
        course,
        "_read_json",
        return_value={
            "saved_at": "2020-01-01T00:00:00+00:00",
            "model": "old-model",
            "action_plan": {
                "headline": "OLD AREA",
                "immediate_move": "Drive to yesterday's event",
                "mid_shift_pivot": "Old pivot",
            },
        },
    ):
        plan, _, model, _ = course._generate_formatted_action_plan(
            origin_label="New area",
            stops=boosted["stops"],
            top_hotspots=[],
            fa_forecast={},
            fa_total_planes=0,
            train_stations=[],
            run_live_llm=False,
        )
        assert plan["headline"] != "OLD AREA"
        assert model == "RideEdge Tactical Formatter"

    # R10 & R17: Ancient airport cache is stale; airport hour buckets do not overlap
    with patch(
        "farol.adapters.base.read_cache",
        return_value={
            "fetched_at": "2020-01-01T00:00:00Z",
            "payload": {
                "state": "ready",
                "fetched_at": "2020-01-01T00:00:00Z",
                "hours": [{"estimated_planes": 48}],
            },
        },
    ):
        assert flightaware.seatac_6h_forecast(pull=False)["state"] == "stale"

    requested_windows = []

    def flight_fetch(url, **kwargs):
        requested_windows.append(parse_qs(urlsplit(url).query))
        return {"scheduled_arrivals": []}, "cache", "2026-10-21T23:00:00Z"

    with patch.object(flightaware, "_api_key", return_value="test"), patch.object(
        flightaware, "fetch_json", side_effect=flight_fetch
    ), patch("farol.adapters.base.read_cache", return_value=None), patch("farol.adapters.base.write_cache"):
        forecast = flightaware.seatac_6h_forecast(
            datetime.fromisoformat("2026-10-21T17:55:00-07:00"), pull=True
        )
    assert requested_windows[0]["end"][0] == requested_windows[1]["start"][0]
    assert len({h["hour_label"] for h in forecast["hours"]}) == 6

    # R11 & R21: Ancient train cache is rejected
    cached_vehicles = {
        "fetched_at": "2020-01-01T00:00:00Z",
        "payload": {
            "data": {
                "references": {
                    "routes": [{"id": "40_2LINE", "shortName": "2 Line"}],
                    "trips": [{"id": "t1", "routeId": "40_2LINE", "tripHeadsign": "Redmond"}],
                    "stops": [{"id": "s1", "name": "Bellevue Downtown"}],
                },
                "list": [{"tripId": "t1", "tripStatus": {"nextStop": "s1", "nextStopTimeOffset": 60}}],
            }
        },
    }
    with patch("farol.adapters.base.read_cache", return_value=cached_vehicles):
        rows = onebusaway.nearby_train_stations(47.6155, -122.2015, now=now)
        bel_trains = next(s for s in rows if "Bellevue Downtown" in s["name"])["trains"]
        assert bel_trains == []

    # R12: Ancient weather observation is rejected
    assert (
        weather_live.parse(
            {"properties": {"timestamp": "2020-01-01T00:00:00Z", "textDescription": "Heavy Rain"}},
            now,
            now + timedelta(hours=6),
            fetched_at="2020-01-01T00:00:00Z",
        )
        == []
    )

    # R14: Non-overlapping shift does not calibrate receipt
    synthetic_trip = dict(
        requested_at="2026-10-21T12:00:00-07:00",
        ended_at="2026-10-21T12:30:00-07:00",
        pickup_zone="bellevue_core",
        dropoff_zone="bellevue_core",
        duration_minutes=30,
        paid_miles=10,
        earnings=40,
    )
    unrelated_shift = dict(
        shift_id="unrelated",
        started_at="2026-10-21T09:00:00-07:00",
        ended_at="2026-10-21T10:30:00-07:00",
        start_odometer_miles=100,
        end_odometer_miles=120,
    )
    summary = history.summarize_history([synthetic_trip], shift_logs=[unrelated_shift])
    assert summary["earnings_status"] == "uncalibrated"
    assert summary["sessions"][0]["net_per_committed_hour"] is None

    # R15 & R07: Non-finite odometer, naive timestamps, and idempotency keys
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/api/history/shifts/start", json={"odometer_miles": "nan"}).status_code == 400
    assert (
        client.post(
            "/api/history/shifts/start",
            json={"odometer_miles": 100, "started_at": "2026-10-21T09:00:00"},
        ).status_code
        == 400
    )
    s1 = client.post(
        "/api/history/shifts/start",
        json={"odometer_miles": 1000.0, "idempotency_key": "idem-start-1"},
    )
    s2 = client.post(
        "/api/history/shifts/start",
        json={"odometer_miles": 1000.0, "idempotency_key": "idem-start-1"},
    )
    assert s1.json()["shift_id"] == s2.json()["shift_id"]

    # R18, R19, R20, R22
    assert _zone("1234 Airport Way S, Seattle, WA") != "sea_airport"
    anchor = Anchor("same-id", "bellevue_core", "Test", 47.61, -122.2, "WAIT", "approved", "test")
    assert routes._cache_key(47.6, -122.3, [anchor]) != routes._cache_key(
        47.6, -122.3, [replace(anchor, latitude=47.8)]
    )
    bad_time = Signal(
        "bad",
        "event_exit",
        "bellevue_core",
        "2026-10-21T12:00:00",
        "2026-10-21T13:00:00-07:00",
        1000,
        "scheduled",
        "synthetic",
        "",
        "",
        0.8,
        {},
    )
    assert evidence.sanitize_signal(bad_time) is None

    snap_path = tmp_path / "cache" / "awareness_snapshot.json"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text(
        json.dumps(
            {
                "collected_at": "2020-01-01T00:00:00Z",
                "feeds": [
                    {
                        "adapter": "wsdot_traffic",
                        "mode": "live",
                        "fetched_at": "2020-01-01T00:00:00Z",
                        "signal_count": 1,
                    }
                ],
            }
        )
    )
    with patch("farol.awareness.saved_besttime", return_value=None):
        health = collect.feed_health_view(now)
    row = next(r for r in health["feeds"] if r["adapter"] == "wsdot_traffic")
    assert row["stoplight"] == "red"
    assert row["mode"] == "stale_cache"


def test_g01_ai_validation_by_construction_rejects_paraphrased_hallucinations() -> None:
    from farol import course

    now = datetime(2026, 10, 21, 20, 0, tzinfo=UTC)
    with ExitStack() as s:
        s.enter_context(patch.object(course, "_read_json", return_value={}))
        s.enter_context(patch.object(course, "seatac_6h_forecast", return_value={"hours": []}))
        s.enter_context(patch.object(course, "load_observed_trips", return_value=[]))
        s.enter_context(patch.object(course, "load_anchors", return_value=[]))
        s.enter_context(patch.object(course, "nearby_train_stations", return_value=[]))
        s.enter_context(patch.object(course, "feed_health_view", return_value={}))
        empty = course.build_6h_shift_course(pull_all=False, now=now)

    paraphrased = {
        "headline": "Bellevue evening shift: reposition for stronger waterfront activity",
        "immediate_move": "Proceed to Renton Marina for immediate pickups.",
        "mid_shift_pivot": "Reposition near the waterfront concert at nine tonight.",
        "airport_and_late_bank": "Seventy-five flights land tonight; airport pickup takes five minutes.",
        "tactical_watchouts": "The pickup point has driver approval and unrestricted access.",
    }
    assert course._validate_llm_action_plan(paraphrased, empty["stops"], 0) is False

    # Also verify rejection when evidence IS present for Bellevue
    evidence_stops = copy.deepcopy(empty["stops"])
    evidence_stops[0]["expected_net_per_hour"] = 35.0
    evidence_stops[0]["sample_trips"] = 3
    evidence_stops[0]["hot_venues"] = ["Tavern Hall (72%)"]
    assert course._validate_llm_action_plan(paraphrased, evidence_stops, 0) is False

    payload = {"model": "expected-model", "choices": [{"message": {"content": json.dumps(paraphrased)}}]}
    with patch.object(
        course.local_runtime,
        "settings",
        return_value=("http://offline.invalid/v1/chat/completions", "expected-model"),
    ), patch.object(course.local_runtime, "session", return_value=nullcontext()), patch.object(
        course, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())
    ) as req_mock, patch.object(course, "save"):
        plan, _, model, _ = course._generate_formatted_action_plan(
            origin_label="Bellevue",
            stops=empty["stops"],
            top_hotspots=[],
            fa_forecast={},
            fa_total_planes=0,
            train_stations=[],
            run_live_llm=True,
        )
    assert req_mock.call_count == 1
    assert model == "RideEdge Tactical Formatter"
    assert plan != paraphrased
    assert "Renton Marina" not in json.dumps(plan)


def test_g02_outcome_episode_state_machine_and_recency_policy() -> None:
    from farol import history, recommend

    now = datetime(2026, 10, 21, 20, 0, tzinfo=UTC)

    def ev(status: str, minutes: int, base: datetime = now) -> dict:
        return {
            "zone": "bellevue_core",
            "status": status,
            "recorded_at": (base + timedelta(minutes=minutes)).isoformat(),
            "recommendation_id": "same-advice",
            "evidence_version": "test-v1",
        }

    s_accept_only = history.summarize_zone_outcomes(
        [ev("waiting", -20), ev("accepted_ride", -1)], now=now
    )["bellevue_core"]
    s_ping_then_accept = history.summarize_zone_outcomes(
        [ev("waiting", -20), ev("request_received", -2), ev("accepted_ride", -1)], now=now
    )["bellevue_core"]
    assert s_accept_only["matched_episodes"] == 1
    assert s_ping_then_accept["matched_episodes"] == 1
    assert s_accept_only["score_adjustment"] == s_ping_then_accept["score_adjustment"] == 1.25
    assert s_accept_only["available_wait_minutes"] == s_ping_then_accept["available_wait_minutes"] == 19.0

    s_one_wait = history.summarize_zone_outcomes(
        [ev("waiting", -20), ev("request_received", 0)], now=now
    )["bellevue_core"]
    s_repeated_wait = history.summarize_zone_outcomes(
        [ev("waiting", -20), ev("waiting", -10), ev("request_received", 0)], now=now
    )["bellevue_core"]
    assert s_one_wait["waiting_events"] == s_repeated_wait["waiting_events"] == 1
    assert s_one_wait["unsuccessful_waits"] == s_repeated_wait["unsuccessful_waits"] == 0
    assert s_one_wait["available_wait_minutes"] == s_repeated_wait["available_wait_minutes"] == 20.0
    assert s_one_wait["mean_minutes_to_ping"] == s_repeated_wait["mean_minutes_to_ping"] == 20.0
    assert s_one_wait["score_adjustment"] == s_repeated_wait["score_adjustment"] == 1.25

    old_base = datetime(2020, 1, 1, tzinfo=UTC)
    s_old = history.summarize_zone_outcomes(
        [ev("waiting", 0, old_base), ev("request_received", 5, old_base)], now=now
    )
    assert s_old["bellevue_core"]["stale_events_excluded"] == 2
    assert s_old["bellevue_core"]["score_adjustment"] == 0.0
    ranked_old = recommend.rank_next_hours(
        [], now=now, origin_zone="bellevue_core", hours=1, outcome_summaries=s_old
    )["ranked"]
    bel_old = next(r for r in ranked_old if r["zone"] == "bellevue_core")
    assert bel_old["score"] == 0.0


def test_g03_g04_android_outcome_attribution_and_manual_area_switch() -> None:
    root = Path(__file__).resolve().parents[1]
    client_kt = (
        root / "android" / "app" / "src" / "main" / "java" / "com" / "rideedge" / "app" / "RideEdgeClient.kt"
    ).read_text(encoding="utf-8")
    main_kt = (
        root / "android" / "app" / "src" / "main" / "java" / "com" / "rideedge" / "app" / "MainActivity.kt"
    ).read_text(encoding="utf-8")
    controller_kt = (
        root / "android" / "app" / "src" / "main" / "java" / "com" / "rideedge" / "app" / "WorkingLocationController.kt"
    ).read_text(encoding="utf-8")

    assert '.put("recommendation_id", recommendationId)' in client_kt
    assert '.put("evidence_version", evidenceVersion' in client_kt
    assert 'recommendationId = json.optString("recommendation_id", "")' in client_kt
    assert "recommendationId = attributedRecId" in main_kt
    assert "evidenceVersion = attributedEvVer" in main_kt

    load_place_block = main_kt.split("fun loadHereByPlace(place: String)")[1].split("fun loadHereFromPixelGps()")[0]
    assert "hereState = null" in load_place_block.split("scope.launch")[0]
    assert "hereState = null" in controller_kt.split("fun beginManualAreaLoad")[1].split("fun completeManualAreaLoad")[0]
    assert "val workingController = remember { WorkingLocationController" in main_kt
    assert "workingController.resolveOutcomeAttribution" in main_kt


def test_h01_per_stop_relational_fact_binding_and_structured_selection() -> None:
    from farol import course

    stops = [
        {
            "hour_index": 1,
            "window_label": "1:00 PM - 2:00 PM",
            "zone": "bellevue_core",
            "zone_label": "Bellevue core",
            "expected_net_per_hour": 30,
            "sample_trips": 5,
            "navigation_available": True,
            "staging_spot": "Bellevue approved curb",
            "hot_venues": ["Tavern Hall (75%)"],
            "spillout_venues": [],
            "events": [],
            "flight_arrivals": 0,
            "primary_trigger": "Historical archive",
        },
        {
            "hour_index": 2,
            "window_label": "2:00 PM - 3:00 PM",
            "zone": "kirkland_waterfront",
            "zone_label": "Kirkland waterfront",
            "expected_net_per_hour": 10,
            "sample_trips": 3,
            "navigation_available": False,
            "staging_spot": "unapproved area reference",
            "hot_venues": [],
            "spillout_venues": [],
            "events": [],
            "flight_arrivals": 0,
            "primary_trigger": "Historical archive",
        },
    ]

    valid_bound = {
        "headline": "Bellevue core → Kirkland waterfront",
        "immediate_move": "[1:00 PM - 2:00 PM] Stage at Bellevue approved curb in Bellevue core (~$30/hr paid-trip archive (5 trips)). Tavern Hall (75%).",
        "mid_shift_pivot": "[2:00 PM - 3:00 PM] Consider Kirkland waterfront (~$10/hr paid-trip archive (3 trips)): Historical archive.",
        "airport_and_late_bank": "Sea-Tac forecast not active (0 flights loaded). Late window: Kirkland waterfront (Historical archive).",
        "tactical_watchouts": "0 Sound Transit Link stations within 5 mi have live train telemetry. Navigation stays gated to approved curbs.",
    }
    # Free-form prose responses are rejected even if text matches rendered output;
    # only structured stop-ID selections are accepted.
    assert course._validate_llm_action_plan(valid_bound, stops, 0) is False

    # 1. Swap rates between stops ($10 on Bellevue or $30 on Kirkland, or compound sentence swap)
    swap_rate_bel = {
        **valid_bound,
        "immediate_move": "[1:00 PM - 2:00 PM] Stage at Bellevue approved curb in Bellevue core (~$10/hr paid-trip archive (5 trips)).",
    }
    swap_rate_kirk = {
        **valid_bound,
        "mid_shift_pivot": "[2:00 PM - 3:00 PM] Consider Kirkland waterfront (~$30/hr paid-trip archive (3 trips)): Historical archive.",
    }
    compound_swap = {
        **valid_bound,
        "mid_shift_pivot": "[2:00 PM - 3:00 PM] Consider Kirkland waterfront ($30/hr paid-trip archive) and Bellevue core ($10/hr paid-trip archive).",
    }
    assert course._validate_llm_action_plan(swap_rate_bel, stops, 0) is False
    assert course._validate_llm_action_plan(swap_rate_kirk, stops, 0) is False
    assert course._validate_llm_action_plan(compound_swap, stops, 0) is False

    # 2. Swap sample trips between stops (3 trips on Bellevue)
    swap_trips = {
        **valid_bound,
        "immediate_move": "[1:00 PM - 2:00 PM] Stage at Bellevue approved curb in Bellevue core (~$30/hr paid-trip archive (3 trips)).",
    }
    assert course._validate_llm_action_plan(swap_trips, stops, 0) is False

    # 3. Swap time windows between stops
    swap_window_imm = {
        **valid_bound,
        "immediate_move": "[2:00 PM - 3:00 PM] Stage at Bellevue approved curb in Bellevue core (~$30/hr paid-trip archive (5 trips)).",
    }
    swap_window_piv = {
        **valid_bound,
        "mid_shift_pivot": "[1:00 PM - 2:00 PM] Consider Kirkland waterfront (~$10/hr paid-trip archive (3 trips)): Historical archive.",
    }
    assert course._validate_llm_action_plan(swap_window_imm, stops, 0) is False
    assert course._validate_llm_action_plan(swap_window_piv, stops, 0) is False

    # 4. Swap approval / staging onto unapproved Kirkland stop
    swap_stage_kirk = {
        **valid_bound,
        "mid_shift_pivot": "[2:00 PM - 3:00 PM] Stage at Kirkland waterfront (~$10/hr paid-trip archive (3 trips)).",
    }
    swap_curb_claim_kirk = {
        **valid_bound,
        "tactical_watchouts": "Kirkland waterfront curb is approved.",
    }
    assert course._validate_llm_action_plan(swap_stage_kirk, stops, 0) is False
    assert course._validate_llm_action_plan(swap_curb_claim_kirk, stops, 0) is False

    # 5. Swap venue onto wrong stop
    swap_venue_kirk = {
        **valid_bound,
        "mid_shift_pivot": "[2:00 PM - 3:00 PM] Consider Kirkland waterfront (~$10/hr paid-trip archive (3 trips)): Tavern Hall (75%).",
    }
    assert course._validate_llm_action_plan(swap_venue_kirk, stops, 0) is False

    # 6. Structured stop-ID selection renders deterministically and rejects invalid stop IDs or prose overrides
    selection = {
        "mode": "structured_selection",
        "immediate_stop_id": "stop_0",
        "pivot_stop_id": "stop_1",
        "late_stop_id": "stop_1",
    }
    assert course._validate_llm_action_plan(selection, stops, 0) is True
    assert course._validate_llm_action_plan({**selection, "immediate_stop_id": "stop_1"}, stops, 0) is False
    assert course._validate_llm_action_plan({**selection, "pivot_stop_id": "stop_0"}, stops, 0) is False
    assert course._validate_llm_action_plan({**selection, "late_stop_id": "stop_99"}, stops, 0) is False
    assert course._validate_llm_action_plan({**selection, "mid_shift_pivot": "override"}, stops, 0) is False

    rendered = course.render_bound_action_plan(selection, stops, 0, origin_label="Bellevue core")
    assert rendered is not None
    assert "~$30/hr paid-trip archive (5 trips)" in rendered["immediate_move"]
    assert "~$10/hr paid-trip archive (3 trips)" in rendered["mid_shift_pivot"]

    # 7. Request schema and cache contract enforce structured stop-ID selection only
    schema = course.build_action_plan_selection_schema(stops)
    props = schema["properties"]
    assert props["mode"]["enum"] == ["structured_selection"]
    assert props["immediate_stop_id"]["enum"] == ["stop_0"]
    assert props["pivot_stop_id"]["enum"] == ["stop_1"]
    assert props["late_stop_id"]["enum"] == ["stop_0", "stop_1"]
    assert schema["additionalProperties"] is False


def test_n01_n02_here_local_vs_remote_evidence_and_watch_wording() -> None:
    from farol import here

    data = here.advise("Totem Lake")
    assert data["place"]["zone"] == "totem_lake"
    assert "stay_or_move_card" in data
    assert "recheck_minutes" in data

    # N01: Remote Seattle opportunities must never be labeled as local to Totem Lake
    spoken = data["spoken"]
    if "Seattle" in spoken or "Convention Center" in spoken or "SLU" in spoken:
        assert "Active local window" not in spoken
        assert "Local activity window" not in spoken

    for w in data["nearby"]:
        assert "is_same_zone" in w
        assert "source_type" in w
        assert "freshness_label" in w
        if w["zone"] != "totem_lake":
            assert w["is_same_zone"] is False

    # N02: WATCH must never say "Hold in ..." or "Hold for now"
    if data["action"] == "WATCH":
        assert "Hold" not in data["action_plain"]
        assert "No clear recommendation to move yet" in data["action_plain"]


def test_n03_course_respects_constraints_and_first_stop_feasibility() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from farol import course

    # Simulate 4:56 PM (4 minutes left in the 4-5 PM hour) starting from Totem Lake
    now_dt = datetime(2026, 10, 21, 16, 56, tzinfo=ZoneInfo("America/Los_Angeles"))
    payload = course.build_6h_shift_course(
        origin_area="Totem Lake",
        pull_all=False,
        now=now_dt,
        minutes_available=90,
        reposition_under_minutes=20,
        finish_near="Kirkland",
    )
    assert payload["origin_zone"] == "totem_lake"
    assert payload["constraints_applied"]["minutes_available"] == 90
    assert payload["constraints_applied"]["reposition_under_minutes"] == 20
    assert payload["constraints_applied"]["finish_near_zone"] == "kirkland_waterfront"
    # 90 minutes = at most 2 hourly stops
    assert len(payload["stops"]) <= 2

    # First stop at 4:56 PM had only 4 minutes remaining in the 4:00-5:00 PM hour,
    # so base_hour advances to 5:00 PM and must NOT pick an unreachable remote zone like Capitol Hill
    first_stop = payload["stops"][0]
    assert first_stop["zone"] != "capitol_hill"
    assert "Hold in Capitol Hill" not in payload["action_plan"]["immediate_move"]
    for stop in payload["stops"]:
        assert stop["drive_minutes_from_prev"] <= 20


def test_n09_flightaware_peak_hour_selects_highest_arrival_count(monkeypatch) -> None:
    from datetime import datetime, timezone
    from farol.adapters import base as adapter_base
    from farol.adapters import flightaware

    # Simulate 6 hourly pages where earlier hours have 26 arrivals (0 long-haul)
    # and a later hour has 21 arrivals (4 long-haul, higher weighted score 29 vs 26)
    counts_and_lh = [(26, 0), (26, 0), (24, 1), (21, 4), (15, 0), (12, 0)]
    call_idx = {"i": 0}

    def fake_fetch_json(url, **kwargs):
        idx = call_idx["i"]
        call_idx["i"] += 1
        planes, lh = counts_and_lh[idx % len(counts_and_lh)]
        rows = []
        for p in range(planes):
            orig = "RJTT" if p < lh else "KLAX"
            rows.append({
                "ident": f"ASA{idx}{p:02d}",
                "origin": {"code": orig},
                "scheduled_in": f"2026-10-21T{15 + idx:02d}:{(p * 2) % 60:02d}:00Z",
            })
        return {"scheduled_arrivals": rows, "links": {}}, "live", "2026-10-21T15:00:00Z"

    monkeypatch.setattr(flightaware, "_api_key", lambda: "test-key")
    monkeypatch.setattr(flightaware, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(adapter_base, "write_cache", lambda *a, **kw: None)

    res = flightaware.seatac_6h_forecast(
        now=datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc),
        pull=True,
    )
    assert res["selection_basis"] == "most_forecast_arrivals"
    peak_hours = [h for h in res["hours"] if h["is_peak"]]
    assert len(peak_hours) == 1
    assert peak_hours[0]["estimated_planes"] == 26
    assert "~26 planes" in res["best_hour_label"]




