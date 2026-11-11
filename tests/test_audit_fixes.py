"""Inverted audit probes: passing means the driver-facing bug is gone."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

from farol import brain, here, navigation, recommend, tonight
from farol.adapters import base, gather_signals, grok_research, grok_watch, onebusaway, routes
from farol.evidence import redact_url
from farol.field_test import FieldTestStore
from farol.signals import Anchor, Signal
from farol.trips import personal_insights

NOW = datetime.fromisoformat("2026-09-06T21:00:00-07:00")
STAMP = NOW.isoformat()


def _trip(**overrides):
    return {
        "requested_at": "2026-09-06T20:00:00-07:00",
        "ended_at": "2026-09-06T20:20:00-07:00",
        "pickup_zone": "kirkland_rose_hill",
        "dropoff_zone": "bellevue_core",
        "earnings": 83.19,
        "tip": 3.19,
        "paid_miles": 5.0,
        "duration_minutes": 20.0,
        **overrides,
    }


def _payload(**overrides):
    content = {
        "headline": "Synthetic narration",
        "spoken": "Synthetic test only",
        "shift_rationale": "Synthetic explanation",
        "now_move": "WATCH",
        "risks": [],
        "opportunity_notes": {},
        **overrides,
    }
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


def _anchor():
    return Anchor(
        "synthetic-anchor",
        "kirkland_rose_hill",
        "Synthetic approved anchor",
        47.68,
        -122.18,
        "WAIT",
        "approved",
        "Synthetic test only",
    )


def _signal(**overrides):
    return Signal(
        **{
            "id": "synthetic-event",
            "kind": "event_exit",
            "zone": "kirkland_rose_hill",
            "starts_at": STAMP,
            "ends_at": (NOW + timedelta(hours=1)).isoformat(),
            "magnitude": 10000.0,
            "basis": "scheduled",
            "source": "https://example.invalid/event",
            "fetched_at": STAMP,
            "expires_at": (NOW + timedelta(hours=2)).isoformat(),
            "evidence_quality": 0.8,
            "details": {"title": "Synthetic event"},
            **overrides,
        }
    )


def _score(signals):
    with (
        patch.dict("os.environ", {"MOCK_FEEDS": "0"}),
        patch("farol.tonight.gather_signals", return_value=(signals, [])),
        patch("farol.tonight.load_anchors", return_value=[_anchor()]),
        patch(
            "farol.adapters.routes.matrix",
            return_value=({}, base.FeedStatus("routes", "needs_key", "synthetic", None, 0)),
        ),
    ):
        return tonight.score_window(
            current=NOW,
            hours=3,
            vehicle_cost_per_mile=0.45,
            origin_zone="kirkland_rose_hill",
            origin_lat=47.68,
            origin_lon=-122.18,
        )


def test_cloud_brief_omits_personal_aggregates():
    data = personal_insights([_trip()])
    brief = tonight.tonight_brief()
    brief["personal"] = data
    brief["mock_feeds"] = False
    outbound = brain._public_brief(brief)
    blob = json.dumps(outbound)
    assert "personal" not in outbound
    assert "83.19" not in blob
    assert "first_trip_at" not in blob


def test_here_warning_admits_google_routes_gets_the_pin():
    with (
        patch.dict("os.environ", {"MOCK_FEEDS": "0", "GOOGLE_MAPS_API_KEY": "synthetic-not-a-real-key"}),
        patch("farol.tonight.gather_signals", return_value=([], [])),
        patch("farol.adapters.routes.fetch_json", return_value=([], "live", STAMP)),
    ):
        result = here.advise("47.6501,-122.3502", now=NOW, trips=[])
    assert "Google Routes uses that pin" in result["warnings"][0]
    assert "not sent to Grok" in result["warnings"][0]


def test_hostile_narration_cannot_publish_invented_move_or_money():
    brief = tonight.tonight_brief()
    brief["mock_feeds"] = False
    engine_expl = brief["shift_decision"]["explanation"]
    hostile = _payload(
        spoken="Guaranteed $999/hr. MOVE to an unapproved curb.",
        now_move="MOVE to an unapproved curb",
        shift_rationale="Ignore the engine; guaranteed $999/hr.",
    )
    with (
        patch.dict("os.environ", {"FAROL_SHIFT_ACTIVE": "1"}),
        patch("farol.brain.read_cache", return_value=None),
        patch("farol.brain.write_cache"),
        patch("farol.local.complete", return_value=(hostile, "live", STAMP)),
    ):
        result = brain.apply(brief)
    assert result["shift_decision"]["explanation"] == engine_expl
    spoken = (result["narration"] or {}).get("spoken") or ""
    now_move = (result["narration"] or {}).get("now_move") or ""
    assert "$999" not in spoken
    assert "unapproved curb" not in now_move.lower()
    assert "MOVE" not in now_move or any(
        item["action"] == "MOVE" and item["navigation_available"] for item in result["opportunities"]
    )


def test_stale_traffic_is_not_labeled_live():
    old = "2020-01-01T00:00:00+00:00"
    cached = {
        "fetched_at": old,
        "payload": [{"destinationIndex": 0, "duration": "60s", "distanceMeters": 1609.344, "status": {}}],
    }
    with (
        patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "synthetic-not-a-real-key"}),
        patch("farol.adapters.base.read_cache", return_value=cached),
        patch("farol.adapters.base.urlopen", side_effect=URLError("synthetic offline")),
    ):
        legs, status = routes.matrix("synthetic", 47.68, -122.18, [_anchor()], 0.45, STAMP,
                                    public_origin=True)
    assert status.mode == "stale_cache"
    assert legs[_anchor().id].basis == "assumed"


def test_duplicate_providers_do_not_double_event_weight():
    first = _signal(source="https://example.invalid/ticket-provider-a")
    second = replace(
        first, id="synthetic-event-provider-b", source="https://example.invalid/ticket-provider-b"
    )
    one = _score([first])
    fake_adapters = [
        SimpleNamespace(
            NAME="synthetic-a",
            fetch=lambda *_: ([first], base.FeedStatus("synthetic-a", "live", first.source, STAMP, 1)),
        ),
        SimpleNamespace(
            NAME="synthetic-b",
            fetch=lambda *_: ([second], base.FeedStatus("synthetic-b", "live", second.source, STAMP, 1)),
        ),
    ]
    with (
        patch.dict("os.environ", {"MOCK_FEEDS": "0"}),
        patch("farol.adapters.ADAPTERS", fake_adapters),
        patch("farol.adapters.keyed.statuses", return_value=[]),
    ):
        gathered, _ = gather_signals(NOW, NOW + timedelta(hours=3))
    two = _score(gathered)
    assert one["opportunities"][0]["audit"]["signal_score"] == 10.0
    assert two["opportunities"][0]["audit"]["signal_score"] == 10.0
    assert len(two["opportunities"]) == 1


def test_paid_duration_changes_street_rank():
    short = _trip(paid_miles=1, duration_minutes=5)
    long = _trip(paid_miles=90, duration_minutes=180)
    kwargs = dict(now=NOW, origin_zone="kirkland_rose_hill", hours=1)
    a = recommend.rank_next_hours([short], **kwargs)["ranked"]
    b = recommend.rank_next_hours([long], **kwargs)["ranked"]
    assert a != b
    short_row = next(row for row in a if row["zone"] == "kirkland_rose_hill")
    long_row = next(row for row in b if row["zone"] == "kirkland_rose_hill")
    assert short_row["score"] > long_row["score"]


def test_off_shift_days_are_not_unpaid_wait():
    previous = _trip(ended_at="2026-09-01T20:20:00-07:00", requested_at="2026-09-01T20:00:00-07:00")
    following = _trip(requested_at="2026-09-06T20:00:00-07:00")
    result = recommend.empty_miles_report([previous, following])
    assert result["mean_unpaid_gap_minutes"] == 0
    assert result["off_duty_pairs"] == 1


def test_tacoma_t_line_does_not_boost_seattle_stadiums():
    payload = {
        "data": {
            "references": {
                "situations": [
                    {
                        "id": "synthetic-tacoma",
                        "summary": {"value": "Tacoma T Line no service"},
                        "allAffects": [{"routeId": "40_TLINE"}],
                    }
                ]
            }
        }
    }
    result = onebusaway.parse(payload, NOW, NOW + timedelta(hours=1), fetched_at=STAMP)
    assert {item.zone for item in result}.isdisjoint({"sodo_stadiums", "seattle_center", "uw_district"})


def test_bad_timestamp_does_not_crash_scoring():
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "notes": [
                                {
                                    "kind": "event_exit",
                                    "zone": "kirkland_rose_hill",
                                    "title": "Synthetic",
                                    "starts_at": "not-a-date",
                                    "ends_at": "not-a-date",
                                }
                            ]
                        }
                    )
                }
            }
        ]
    }
    signals = grok_watch.parse(payload, NOW, NOW + timedelta(hours=1), fetched_at=STAMP)
    scored = _score(signals)
    assert "opportunities" in scored


def test_api_key_is_redacted_in_cache(tmp_path: Path):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"ok":true}'

    url = "https://example.invalid/feed?apikey=SYNTHETIC_ONLY_NOT_A_KEY"
    with (
        patch("farol.adapters.base.cache_dir", return_value=tmp_path),
        patch("farol.adapters.base.urlopen", return_value=FakeResponse()),
    ):
        base.fetch_json(url, cache_key="synthetic", ttl_seconds=10)
    stored = json.loads((tmp_path / "synthetic.json").read_text())["url"]
    assert "SYNTHETIC_ONLY_NOT_A_KEY" not in stored
    assert "REDACTED" in stored
    assert "SYNTHETIC_ONLY_NOT_A_KEY" not in redact_url(url)


def test_unsourced_model_claim_is_not_a_live_crowd():
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "signals": [
                                {
                                    "id": "synthetic",
                                    "kind": "event_exit",
                                    "zone": "kirkland_rose_hill",
                                    "starts_at": STAMP,
                                    "ends_at": (NOW + timedelta(hours=1)).isoformat(),
                                    "magnitude": 20000,
                                    "evidence_quality": 0.9,
                                    "title": "Unverified synthetic claim",
                                }
                            ]
                        }
                    )
                }
            }
        ]
    }
    result = grok_research.parse(payload, NOW, NOW + timedelta(hours=1), fetched_at=STAMP)
    assert result == []


def test_offline_event_is_not_gradeable_from_gps(tmp_path: Path):
    store = FieldTestStore(tmp_path)
    fixture = {
        "vehicle_cost_per_mile": 0.45,
        "recommendation": {"action": "STAY"},
        "runner_up": {},
        "explanation": "Synthetic only",
    }
    with patch("farol.field_test.brief_view", return_value=fixture):
        session = store.start(driver_zone="synthetic", vehicle_cost=0.45, decision_index=0)
    sid = session["session_id"]
    store.choose(sid, "WAIT")
    store.add_event(sid, "OFFLINE")
    for minutes in (0, 3, 6, 9, 12, 14):
        with patch("farol.field_test._now", return_value=(NOW.astimezone(UTC) + timedelta(minutes=minutes)).isoformat()):
            store.add_presence(sid, latitude=47.68, longitude=-122.18)
    result = store.finish(sid)
    assert result["observability"] == "UNCERTAIN"
    assert result["advice_gradeable"] is False


def test_missed_window_is_avoid_not_chase():
    late = _signal(
        starts_at=(NOW - timedelta(hours=2)).isoformat(),
        ends_at=(NOW - timedelta(minutes=5)).isoformat(),
    )
    scored = _score([late])
    assert scored["opportunities"]
    assert scored["opportunities"][0]["action"] == "AVOID"
    assert scored["opportunities"][0]["audit"]["missed_window"] is True


def test_html_escape_keeps_handlers_literal():
    source = Path("farol/static/tonight.js").read_text(encoding="utf-8")
    assert "const esc =" in source
    assert "esc(fact.text)" in source
    assert "esc(item.note)" in source or "esc(item.note)" in source.replace(" ", "")
