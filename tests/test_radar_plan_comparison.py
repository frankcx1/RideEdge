"""Independent planning, time-varying evidence, and inspectable alternatives."""
import copy
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from farol import local, local_runtime, radar
from farol.adapters import flightaware

NOW = datetime(2026, 10, 25, 2, tzinfo=UTC)
ORIGIN = radar.origin("Seattle")


def option(key, weight, lat=47.61, lon=-122.337):
    return {"id": key, "name": key, "activity_weight": weight, "latitude": lat,
            "longitude": lon, "route": {"minutes": 0}, "ends_at": None,
            "zone": "seattle_core", "category": "Places"}


def test_lookahead_does_not_get_trapped_at_first_greedy_winner():
    a, b = option("a", 20), option("b", 19, lat=47.66)
    slots = [{"starts_at": (NOW+timedelta(hours=i)).isoformat(), "options": [a, b]} for i in range(6)]
    for slot in slots[1:]:
        slot["options"] = [a, {**b, "activity_weight": 40}]
    assert radar.algorithm_sequence(slots, ORIGIN) == ["b"]*6


def test_later_evidence_changes_destination_and_preserves_alternatives():
    def rows(snapshot, besttime, at, now):
        offset = int((at-now).total_seconds()/3600)
        candidates = [option("a", 60 if offset < 2 else 10), option("b", 10 if offset < 2 else 70)]
        return [{**r, "strength": "Scheduled activity", "evidence": [], "maps_url": "", "pin_basis": "venue"} for r in candidates], []
    with patch.object(radar, "candidates", side_effect=rows):
        view = radar.build(ORIGIN, {}, {}, now=NOW)
    assert [s["selected_id"] for s in view["plan"]] == ["a", "a", "b", "b", "b", "b"]
    assert all(len(s["options"]) == 2 for s in view["plan"])
    assert view["plan"][1]["repeat_area"]
    assert "not an instruction to wait" in view["plan"][1]["outlook_note"]


def test_model_does_not_see_algorithm_choices_scores_or_order():
    view = radar.build(ORIGIN, {}, {}, now=NOW)
    baseline = copy.deepcopy(view["algorithm_plan"])
    def complete(**kw):
        prompt = json.loads(kw["user"])
        assert "algorithm_plan" not in prompt
        assert '"score"' not in kw["user"]
        assert '"activity_weight"' not in kw["user"]
        assert '"arrival_relevant"' not in kw["user"]
        assert '"strength"' not in kw["user"]
        assert '"selected_id"' not in kw["user"]
        choices = {}
        for i, slot in enumerate(prompt["intervals"]):
            ids = list(slot["options"])
            assert ids == sorted(ids)
            choices[f"slot_{i}"] = ids[-1] if ids else "none"
            choices[f"reason_{i}"] = "travel"
        return {"choices": [{"message": {"content": json.dumps(choices)}}]}, "live", NOW.isoformat()
    with patch.object(local_runtime, "settings", return_value=("http://localhost/v1/chat/completions", "qwen-test")), \
         patch.object(local_runtime, "session", return_value=nullcontext()), patch.object(local, "complete", side_effect=complete):
        result = radar.ask_model(view)
    assert result["algorithm_plan"] == baseline
    assert result["comparison"]["state"] == "ready"
    assert len(result["comparison"]["hours"]) == 6
    assert result["now"][0]["id"] == result["plan"][0]["selected_id"]


def test_pool_preserves_distinct_districts_instead_of_only_top_venues():
    rows = [option(str(i), 80-i) for i in range(12)]
    rows.append({**option("other_district", 20), "zone": "capitol_hill"})
    assert "other_district" in {r["id"] for r in radar.planning_pool(rows)}


def test_expired_airport_peak_is_not_recommended_from_cache():
    cached = {"payload": {"state": "ready", "fetched_at": (NOW-timedelta(days=1)).isoformat(),
              "best_hour_label": "Yesterday", "best_lot_arrival_time": "Yesterday", "hours": []}}
    with patch("farol.adapters.base.read_cache", return_value=cached):
        result = flightaware.seatac_6h_forecast(now=NOW)
    assert result["state"] == "stale"
    assert result["best_lot_arrival_time"] == ""
    assert "Yesterday" not in result["best_hour_label"]


def test_cached_airport_peak_moves_to_remaining_hour():
    cached = {"payload": {"report_schema_version": 1, "state": "ready", "fetched_at": NOW.isoformat(), "hours": [
        {"ends_at": (NOW-timedelta(minutes=1)).isoformat(), "estimated_planes": 40, "is_peak": True},
        {"starts_at": NOW.isoformat(), "ends_at": (NOW+timedelta(hours=1)).isoformat(), "estimated_planes": 20,
         "mode": "cache", "fetched_at": NOW.isoformat(),
         "hour_label": "Upcoming", "lot_arrival_target": "Later", "is_peak": False}]}}
    with patch("farol.adapters.base.read_cache", return_value=cached):
        result = flightaware.seatac_6h_forecast(now=NOW)
    assert len(result["hours"]) == 1
    assert result["hours"][0]["is_peak"]
    assert "Upcoming" in result["best_hour_label"]
