"""Behavioral contracts for the new activity-led phone experience."""
from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from farol import radar, radar_api
from farol.api import app

NOW = datetime(2026, 10, 25, 2, 30, tzinfo=UTC)  # Saturday 7:30 PM Pacific
ORIGIN = radar.origin("Bellevue")


def venue(vid="local", lat=None, lon=None, value=90, age=5, typical=None):
    at = NOW.astimezone(radar.PACIFIC)
    lat = lat if lat is not None else ORIGIN["latitude"]
    lon = lon if lon is not None else ORIGIN["longitude"]
    return {"requested": {"id": vid, "name": vid, "zone": "bellevue_core",
            "address": "100 Fixture St", "city": "Bellevue", "latitude": lat, "longitude": lon},
            "identity_matched": True,
            "live": {"venue_id": vid, "identity_matched": True, "available": True,
                     "busyness": value, "retrieved_at": (NOW-timedelta(minutes=age)).isoformat()},
            "forecast": {"venue": {"venue_id": vid, "venue_name": vid, "venue_address": "100 Fixture St Bellevue",
                                   "venue_lat": lat, "venue_lon": lon},
                         "retrieved_at": NOW.isoformat(), "days": [{"hours": [
                {"weekday": at.weekday(), "hour": at.hour, "typical_busyness": typical}]}]}}


def signal(**overrides):
    return {"id": "show", "kind": "event_exit", "zone": "bellevue_core", "basis": "scheduled",
            "source": "test:events", "starts_at": NOW.isoformat(), "ends_at": (NOW+timedelta(minutes=60)).isoformat(),
            "expires_at": (NOW+timedelta(minutes=60)).isoformat(), "fetched_at": NOW.isoformat(),
            "details": {"title": "Show ending", "venue": "Hall"}, **overrides}


def build(venues=(), signals=(), ctx=ORIGIN):
    return radar.build(ctx, {"signals": list(signals)}, {"venues": list(venues)}, now=NOW)


def test_exact_radius_before_rounding_and_separate_further():
    degrees = 5 / 3958.8 * 180 / 3.141592653589793
    near = venue("inside", lat=ORIGIN["latitude"]+degrees-.000001)
    far = venue("outside", lat=ORIGIN["latitude"]+degrees+.000001)
    view = build([near, far])
    assert "venue:inside" in {r["id"] for r in view["nearby"]}
    assert "venue:outside" not in {r["id"] for r in view["nearby"]}
    assert "venue:outside" in {r["id"] for r in view["further"]}


@pytest.mark.parametrize("changes", [
    {"expires_at": (NOW-timedelta(seconds=1)).isoformat()},
    {"fetched_at": (NOW-timedelta(days=3)).isoformat()},
    {"fetched_at": None}, {"expires_at": None},
    {"fetched_at": (NOW+timedelta(hours=1)).isoformat()},
])
def test_expired_or_undated_signal_cannot_recommend_move(changes):
    view = build(signals=[signal(**changes)])
    assert "signal:show" not in {r["id"] for r in view["nearby"]}
    assert view["excluded_count"] == 1


def test_old_live_is_typical_or_absent_never_live():
    v = venue(age=61, typical=80)
    view = build([v])
    card = next(r for r in view["nearby"] if r["id"] == "venue:local")
    assert card["strength"] == "Typical pattern"
    assert card["busyness"] == 80
    v["forecast"]["retrieved_at"] = (NOW-timedelta(days=15)).isoformat()
    assert "venue:local" not in {r["id"] for r in build([v])["nearby"]}


def test_live_zero_does_not_fall_back_to_busy_typical():
    assert "venue:local" not in {r["id"] for r in build([venue(value=0, typical=90)])["nearby"]}


def test_closed_venue_does_not_get_recommended():
    v = venue(typical=90)
    v["live"]["open_status"] = False
    assert "venue:local" not in {r["id"] for r in build([v])["nearby"]}


def test_unmatched_venue_identity_rejected():
    v = venue()
    v["forecast"]["venue"]["venue_address"] = "999 Wrong Branch Bellevue"
    assert "venue:local" not in {r["id"] for r in build([v])["nearby"]}


def test_five_mile_boundary_cannot_be_bypassed_by_qwen():
    view = build([venue()])
    choices = [s["selected_id"] or "none" for s in view["plan"]]
    choices[0] = "airport-or-far-away"
    with pytest.raises(ValueError):
        radar.apply_selection(view, choices)


def test_qwen_choice_keeps_now_and_plan_in_sync_and_does_not_mutate_input():
    view = build([venue("first"), venue("second", value=80)])
    choices = [s["selected_id"] or "none" for s in view["plan"]]
    choices[0] = "venue:second"
    result = radar.apply_selection(view, choices)
    assert result["now"][0]["id"] == result["plan"][0]["selected_id"] == "venue:second"
    assert view["now"][0]["id"] == "venue:first"


def test_no_personal_trip_history_or_experimental_import_is_used():
    with patch("farol.trips.load_observed_trips", side_effect=AssertionError("history called")), \
         patch("farol.history.summarize_zone_outcomes", side_effect=AssertionError("outcomes called")):
        assert build([venue()])["now"][0]["id"] == "venue:local"


def test_home_gets_commercial_area_best_guess_not_residential_wait():
    view = build(ctx=radar.origin("Home"))
    assert view["now"]
    assert view["now"][0]["id"].startswith("hub:")
    assert view["now"][0]["strength"] == "Best guess"


def test_seattle_night_has_commercial_fallback():
    view = build(ctx=radar.origin("Capitol Hill"))
    assert any(r["id"].startswith("district:") for r in view["now"])


def test_airport_arrivals_do_not_create_queue_recommendations():
    view = build(signals=[signal(zone="sea_airport", kind="airport_arrivals")], ctx=radar.origin("SEA"))
    assert not any(r["zone"] == "sea_airport" for r in view["nearby"]+view["further"])


def test_routine_train_arrivals_are_visible_context_not_move_triggers():
    view = build(signals=[signal(kind="special_event", source="onebusaway:station_arrivals",
                                details={"title": "Link Light Rail arriving in 3 minutes"})])
    assert "signal:show" in {r["id"] for r in view["nearby"]}
    assert "signal:show" not in {r["id"] for r in view["now"]}
    assert all(s["selected_id"] != "signal:show" for s in view["plan"])


def test_future_plan_never_calls_live_busyness_a_forecast():
    view = build([venue()])
    for slot in view["plan"][1:]:
        assert all(r["strength"] != "Current activity" for r in slot["options"])


@pytest.mark.parametrize("now", [NOW, datetime(2026, 11, 1, 8, 45, tzinfo=UTC)])
def test_rolling_plan_covers_six_elapsed_hours_including_dst(now):
    view = radar.build(ORIGIN, {}, {}, now=now)
    assert len(view["plan"]) == 6
    assert radar.stamp(view["plan"][-1]["ends_at"])-radar.stamp(view["plan"][0]["starts_at"]) == timedelta(hours=6)


def test_stale_route_cannot_retain_live_status():
    card = radar.candidates({}, {"venues": [venue()]}, NOW, NOW)[0][0]
    routes = {card["id"]: {"minutes": 1, "miles": 1, "basis": "live traffic", "fetched_at": (NOW-timedelta(minutes=11)).isoformat()}}
    assert radar.rank([card], ORIGIN, NOW, NOW, routes)[0]["route"]["basis"] == "estimated"


def test_future_expired_request_rejected_without_model_call():
    with patch.object(radar_api, "_snapshots", {"old": build()}), patch.object(radar, "ask_model") as model:
        response = TestClient(app).post("/api/radar/ask", json={"snapshot_id": "old", "question": "where?"})
    assert response.status_code == 409
    model.assert_not_called()


def test_preview_does_not_change_working_context():
    with patch.object(radar_api, "_context", copy.deepcopy(ORIGIN)), patch.object(radar_api, "read_inputs", return_value=({}, {})):
        response = TestClient(app).post("/api/radar/preview", json={"area": "Kirkland"})
        assert response.status_code == 200
        assert radar_api._context == ORIGIN
        assert response.json()["origin"]["zone"] != ORIGIN["zone"]


def test_stale_phone_location_rejected():
    result = TestClient(app).post("/api/radar/context", json={"latitude": 47.61, "longitude": -122.2,
                                "fix_at": "2020-01-01T00:00:00Z", "accuracy_meters": 5})
    assert result.status_code == 400


def test_late_background_result_does_not_replace_newer_location():
    view = build()
    def changed_context(*args, **kwargs):
        radar_api._generation += 1
        radar_api._view = {"sentinel": "newer location"}
        return view
    with patch.multiple(radar_api, _context=ORIGIN, _view=view, _generation=1,
                        _refreshing=False, _last_touch=radar_api.time.monotonic(),
                        _last_provider_pull=radar_api.time.monotonic()), \
         patch.object(radar_api, "read_inputs", return_value=({}, {})), \
         patch.object(radar_api, "_routes", return_value={}), \
         patch.object(radar, "ask_model", side_effect=changed_context):
        radar_api.run_once()
        assert radar_api._view == {"sentinel": "newer location"}


def test_cached_outlook_cannot_present_old_immediate_guidance():
    view = build([venue()])
    view["generated_at"] = "2020-01-01T00:00:00Z"
    public = radar_api._public(view)
    assert public["evidence_stale"]
    assert public["now"] == []
    assert public["further"] == []
    assert public["plan"]  # inspectable with the stale label


@pytest.mark.parametrize("reason", ["activity", "fallback"])
def test_model_contract_selection_is_validated_end_to_end(reason):
    import json
    from contextlib import nullcontext

    from farol import local, local_runtime

    view = build([venue()])
    payload = {f"slot_{i}": s["selected_id"] or "none" for i, s in enumerate(view["plan"])}
    payload.update({f"reason_{i}": reason for i in range(6)})
    with patch.object(local_runtime, "settings", return_value=("http://localhost/v1/chat/completions", "qwen-test")), \
         patch.object(local_runtime, "session", return_value=nullcontext()), \
         patch.object(local, "complete", return_value=({"choices": [{"message": {"content": json.dumps(payload)}}]}, "live", NOW.isoformat())):
        result = radar.ask_model(view)
    assert result["qwen"]["state"] == "ready"
    assert result["now"][0]["id"] == result["plan"][0]["selected_id"]
    assert result["now"][0]["qwen_reason"]
    if reason == "fallback":
        assert result["now"][0]["strength"] == "Current activity"
        assert result["now"][0]["qwen_reason"] == "Qwen selected this option from the supplied evidence."
        assert result["plan"][0]["qwen_reason_review"]["reported_code"] == "fallback"
        assert result["plan"][0]["qwen_reason_review"]["state"] == "not_applicable"


def test_ask_returns_a_job_without_waiting_for_gpu_startup():
    current = datetime.now(UTC)
    view = radar.build(ORIGIN, {}, {}, now=current)
    with patch.object(radar_api, "_snapshots", {view["snapshot_id"]: view}), \
         patch.object(radar_api, "_ask_jobs", {}), \
         patch.object(radar_api, "_start_ask_work") as start:
        client = TestClient(app)
        response = client.post("/api/radar/ask", json={"snapshot_id": view["snapshot_id"], "question": "Why this area?"})
        assert response.status_code == 202
        start.assert_called_once()
        job = client.get("/api/radar/ask/jobs/"+response.json()["job_id"])
        assert job.json()["state"] == "running"
        assert client.post("/api/radar/ask", json={"snapshot_id": view["snapshot_id"], "question": "Another?"}).status_code == 409
