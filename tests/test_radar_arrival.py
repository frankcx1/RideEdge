"""Arrival-time opportunity checks shared by ranking, both planners and actions."""
import copy
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from farol import local, local_runtime, radar
from farol.radar_contract import RadarView, project

NOW = datetime(2026, 10, 25, 2, 30, tzinfo=UTC)
ORIGIN = radar.origin("Bellevue")


def event(start=30, end=75, **changes):
    return {"id": "concert", "kind": "event_exit", "zone": "bellevue_core",
            "basis": "scheduled", "source": "fixture:events", "fetched_at": NOW.isoformat(),
            "starts_at": (NOW + timedelta(minutes=start)).isoformat(),
            "ends_at": (NOW + timedelta(minutes=end)).isoformat(),
            "expires_at": (NOW + timedelta(hours=4)).isoformat(),
            "details": {"venue": "Fixture Hall", "latitude": ORIGIN["latitude"],
                        "longitude": ORIGIN["longitude"], "title": "Estimated concert exit"}, **changes}


def route(minutes):
    return {"minutes": minutes, "miles": 1, "basis": "fixture traffic", "fetched_at": NOW.isoformat()}


def build(signals, minutes=5, venues=()):
    return radar.build(ORIGIN, {"signals": signals}, {"venues": list(venues)}, now=NOW,
                       routes={"signal:concert": route(minutes)})


def test_upcoming_exit_is_inspectable_but_not_a_reason_to_go_early():
    view = build([event()])
    saved = copy.deepcopy(view)
    nearby = next(r for r in view["nearby"] if r["id"] == "signal:concert")
    assert not nearby["arrival_eligible"]
    assert nearby["activity_weight"] == 0
    assert all(r["id"] != nearby["id"] for r in view["now"])
    assert all(r["id"] != nearby["id"] for r in view["plan"][0]["options"])
    assert any(r["id"] == nearby["id"] for r in view["plan"][1]["options"])
    public = project(view, NOW)
    card = next(r for r in public["nearby"] if r["id"] == nearby["id"])
    assert not card["actionable"]
    assert card["unavailable_reason"] == "opportunity_not_active_on_arrival"
    public["scheduler"] = {"state": "preview", "next_review_at": None, "session_expires_at": None}
    RadarView.model_validate(public)
    assert view == saved


@pytest.mark.parametrize(("minutes", "eligible"), [(29.9, False), (30, True), (65, True), (65.1, False)])
def test_arrival_window_boundaries(minutes, eligible):
    rows, _ = radar.candidates({"signals": [event()]}, {}, NOW, NOW)
    card = next(r for r in rows if r["id"] == "signal:concert")
    assert radar.on_arrival(card, NOW, route(minutes))["arrival_eligible"] is eligible


def test_future_event_cannot_boost_independently_busy_venue():
    venue = {"requested": {"id": "hall", "name": "Fixture Hall", "zone": "bellevue_core",
                           "address": "100 Fixture St", "city": "Bellevue",
                           "latitude": ORIGIN["latitude"], "longitude": ORIGIN["longitude"]},
             "identity_matched": True,
             "forecast": {"venue": {"venue_id": "hall", "venue_name": "Fixture Hall",
                                    "venue_address": "100 Fixture St Bellevue", "venue_lat": ORIGIN["latitude"],
                                    "venue_lon": ORIGIN["longitude"]}},
             "live": {"venue_id": "hall", "identity_matched": True,
                      "available": True, "busyness": 70, "retrieved_at": NOW.isoformat()}}
    with_event, without = build([event()], venues=[venue]), build([], venues=[venue])
    mixed = next(r for r in with_event["nearby"] if r["id"] == "venue:hall")
    live = next(r for r in without["nearby"] if r["id"] == "venue:hall")
    assert mixed["activity_weight"] == live["activity_weight"]
    assert mixed["strength"] == "Current activity"
    assert mixed["arrival_eligible"] and len(mixed["evidence"]) == 2
    assert not mixed["evidence"][1]["arrival_relevant"]


def test_different_preceding_choice_rechecks_start_time_for_both_methods():
    view = build([event(start=75, end=120)])
    # In hour two the exit is useful from a 20-minute preceding leg, but not a
    # zero-minute repeated stay. Both methods must reject the latter sequence.
    rows, _ = radar.candidates({"signals": [event(start=75, end=120)]}, {}, NOW+timedelta(hours=1), NOW)
    concert = next(r for r in rows if r["id"] == "signal:concert")
    concert = radar.on_arrival(concert, NOW+timedelta(hours=1), route(20))
    concert["route"] = route(20)
    fallback = copy.deepcopy(view["plan"][0]["options"][0])
    fallback["activity_weight"] = 1
    slot = {"starts_at": (NOW+timedelta(hours=1)).isoformat(),
            "options": [concert, fallback], "selected_id": concert["id"]}
    first = {"starts_at": NOW.isoformat(), "options": [fallback], "selected_id": fallback["id"]}
    with patch.object(radar, "estimate_route", return_value=route(0)):
        assert radar.algorithm_sequence([first, slot], ORIGIN)[1] == fallback["id"]
        with pytest.raises(ValueError, match="not reachable"):
            radar.annotate_plan({"origin": ORIGIN, "plan": [first, slot]})


def test_faster_updated_route_invalidates_formerly_timed_arrival():
    view = build([event()], minutes=30)
    assert view["now"][0]["id"] == "signal:concert"
    view["origin"] = {**ORIGIN, "latitude": ORIGIN["latitude"] + .001}
    with patch.object(radar, "estimate_route", return_value=route(2)):
        public = project(view, NOW)
    assert not public["now"]
    assert public["evidence_stale"]


def test_qwen_receives_start_and_end_windows_without_algorithm_contributions():
    view = build([event(start=0)])
    ids = sorted({r["id"] for s in view["plan"] for r in s["options"]})
    aliases = {key: f"p{i:02d}" for i, key in enumerate(ids)}

    def complete(**kwargs):
        prompt = json.loads(kwargs["user"])
        prompt["evidence"] = {eid: dict(zip(prompt["evidence_layouts"][row[0]], row[1:], strict=True))
                              for eid, row in prompt["evidence"].items()}
        evidence = next(e for e in prompt["evidence"].values() if prompt["sources"][e["source"]] == "fixture:events")
        assert prompt["times"][evidence["starts_at"]] == NOW.isoformat()
        assert prompt["times"][evidence["ends_at"]] == (NOW+timedelta(minutes=75)).isoformat()
        assert evidence["role"] == "opportunity"
        assert '"activity_weight"' not in kwargs["user"]
        assert '"arrival_relevant"' not in kwargs["user"]
        choices = {}
        for i, slot in enumerate(view["plan"]):
            choices[f"slot_{i}"] = aliases.get(slot["selected_id"], "none")
            choices[f"reason_{i}"] = "timing"
        return {"choices": [{"message": {"content": json.dumps(choices)}}]}, "live", NOW.isoformat()

    with patch.object(local_runtime, "settings", return_value=("http://localhost/v1/chat/completions", "qwen-test")), \
            patch.object(local_runtime, "session", return_value=nullcontext()), \
            patch.object(local, "complete", side_effect=complete):
        result = radar.ask_model(view)
    assert result["qwen"]["state"] == "ready"
    assert result["now"][0]["id"] == result["plan"][0]["selected_id"]


@pytest.mark.parametrize("reverse", [False, True])
def test_routine_train_context_does_not_disable_independent_event(reverse):
    concert = event(start=0)
    train = event(start=0, id="train", kind="special_event", source="onebusaway:station_arrivals")
    view = build([concert, train] if not reverse else [train, concert])
    hall = next(r for r in view["nearby"] if r["name"] == "Fixture Hall")
    assert hall["arrival_eligible"] and not hall.get("context_only")
    assert hall["activity_weight"] == 42
