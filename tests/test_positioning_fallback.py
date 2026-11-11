import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from farol import decision_engine as engine, decision_policy, radar, positioning_fallback
from farol.radar_contract import RadarView, project

NOW = datetime(2026, 11, 7, 20, 5, tzinfo=UTC)
ORIGIN = radar.origin("Downtown Kirkland")


def build(enabled=True, origin=ORIGIN, signals=(), routes=None, at=NOW):
    policy = {**decision_policy.load(), "positioning_fallback_enabled": enabled}
    return engine.build(origin, {"signals": list(signals)}, {}, now=at, routes=routes, policy=policy)


def answer(view):
    request, _, catalog = engine.compile_request(view)
    result = {f"window_{i}": {"choice_id": "none_supported", "support_ids": [], "reason_code": "insufficient_support"}
              for i in range(6)}
    candidate = request["windows"][0]["candidates"][0]
    result["window_0"] = {"choice_id": candidate["id"], "support_ids": candidate["support_ids"][:1],
                          "reason_code": "positioning_fallback"}
    return request, catalog, result


def test_paused_without_events_can_offer_honest_nearest_catalog_options():
    view = build()
    assert view["now"] and view["decision_state"] == "contextual_fallback"
    assert "paused" in view["activity_coverage"]
    assert all(p["decision_class"] == "contextual_fallback" and p["activity_weight"] == 0 for p in view["now"])
    assert all(p["hours_status"] == "unknown" and "unverified" in p["strength"] for p in view["now"])
    pool = view["plan"][0]["options"]
    assert view["now"][0]["id"] == min(pool, key=positioning_fallback.sort_key)["id"]
    assert all(not slot["options"] for slot in view["plan"][1:])
    assert project(view, NOW)["now"][0]["actionable"]


def test_gate_off_keeps_context_inspectable_but_not_actionable():
    view = build(False)
    assert not view["now"] and view["nearby"]
    assert all(not p["actionable"] for p in project(view, NOW)["nearby"])
    assert view["decision_state"] == "none_supported"


def test_supported_opportunity_wins_and_model_never_receives_fallback_in_that_window():
    event = {"id": "exit", "zone": ORIGIN["zone"], "kind": "event_exit", "source": "fixture:event",
             "basis": "scheduled", "starts_at": NOW.isoformat(), "ends_at": (NOW+timedelta(hours=1)).isoformat(),
             "fetched_at": NOW.isoformat(), "expires_at": (NOW+timedelta(hours=1)).isoformat(),
             "details": {"title": "Fixture exit", "latitude": ORIGIN["latitude"], "longitude": ORIGIN["longitude"]}}
    view = build(signals=[event])
    assert view["now"][0]["id"] == "signal:exit"
    assert all(p["decision_class"] == "supported_opportunity" for p in view["plan"][0]["options"])
    request, _, _ = engine.compile_request(view)
    assert all(e["family"] != "positioning_context" for e in request["evidence"].values())


def test_qwen_must_preserve_context_classification_and_cite_the_catalog():
    view = build()
    request, catalog, result = answer(view)
    out = engine.apply(view, result, request, catalog, now=NOW)
    assert out["decision_state"] == "contextual_fallback"
    assert "unverified" in out["now"][0]["qwen_reason"]
    result["window_0"]["reason_code"] = "activity"
    with pytest.raises(ValueError, match="supported activity"):
        engine.apply(view, result, request, catalog, now=NOW)
    from farol.local_runtime import failure_status
    try:
        engine.apply(view, result, request, catalog, now=NOW)
    except engine.DecisionValidationError as error:
        assert failure_status(error)["state"] == "rejected"
        assert "unavailable" not in failure_status(error)["detail"]
    result["window_0"]["reason_code"] = "positioning_fallback"
    result["window_0"]["support_ids"] = ["invented"]
    with pytest.raises(ValueError, match="Evidence"):
        engine.apply(view, result, request, catalog, now=NOW)


def test_qwen_can_abstain_instead_of_inventing_a_supported_move():
    view = build()
    request, catalog, result = answer(view)
    result["window_0"] = {"choice_id": "none_supported", "support_ids": [], "reason_code": "insufficient_support"}
    out = engine.apply(view, result, request, catalog, now=NOW)
    assert out["decision_audit"]["model"][0] is None
    assert out["decision_audit"]["contextual_alternatives_after_abstention"]
    assert out["decision_state"] == "contextual_fallback"
    assert "no supported Qwen choice" in out["plan"][0]["selection_basis"]
    assert "Qwen selected no supported move" in out["now"][0]["qwen_reason"]
    assert out["now"][0]["id"] == view["now"][0]["id"]
    assert project(out, NOW)["now"][0]["actionable"]


def test_decoding_schema_rejects_activity_for_context_and_support_for_abstention():
    from jsonschema import Draft202012Validator
    view = build()
    _, schema, _ = engine.compile_request(view)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    _, _, result = answer(view)
    assert validator.is_valid(result)
    for reason in ("activity", "travel", "event_exit", "closing_window"):
        invalid = copy.deepcopy(result)
        invalid["window_0"]["reason_code"] = reason
        assert not validator.is_valid(invalid)
    invalid = copy.deepcopy(result)
    invalid["window_0"]["choice_id"] = "none_supported"
    assert not validator.is_valid(invalid)
    invalid["window_0"] = {"choice_id": "none_supported", "support_ids": [], "reason_code": "insufficient_support"}
    assert validator.is_valid(invalid)
    # Empty outlook windows cannot choose an area from a different window.
    invalid["window_1"] = copy.deepcopy(result["window_0"])
    assert not validator.is_valid(invalid)


def test_validation_reason_never_echoes_untrusted_exception_text():
    from farol.local_runtime import failure_status
    public = failure_status(engine.DecisionValidationError("Contextual positioning cannot be described as supported activity"))
    assert "Contextual positioning" in public["detail"]
    private = failure_status(engine.DecisionValidationError("secret coordinates or provider text"))
    assert "secret" not in private["detail"]


def test_qwen_abstention_cannot_restore_expired_contextual_options():
    view = build()
    request, catalog, result = answer(view)
    result["window_0"] = {"choice_id": "none_supported", "support_ids": [], "reason_code": "insufficient_support"}
    for row in view['plan'][0]['options']:
        for e in row['evidence']:
            e['expires_at'] = (NOW+timedelta(minutes=1)).isoformat()
    out = engine.apply(view, result, request, catalog, now=NOW+timedelta(minutes=2))
    assert not out['now'] and out['decision_state'] == 'none_supported'


@pytest.mark.parametrize("change", [{"closed": True}, {"latitude": 0}, {"longitude": float("nan")},
                                    {"id": "signal:transit"}, {"latitude": 47.9}])
def test_closed_invalid_or_uncatalogued_pins_cannot_be_fallbacks(change):
    row = copy.deepcopy(build()["now"][0])
    row.update(change)
    assert positioning_fallback.prepare(row, NOW, NOW) is None


def test_no_catalog_and_outside_policy_hours_remain_no_option(monkeypatch):
    registry = radar.load_zones()
    monkeypatch.setattr(radar, "load_zones", lambda: replace(registry, pickup_centers=()))
    assert not build()["now"]
    monkeypatch.setattr(radar, "load_zones", lambda: replace(registry, pickup_centers=tuple(
        replace(c, active_start_hour=18, active_end_hour=23) for c in registry.pickup_centers)))
    assert not build()["now"]


def test_route_time_gate_separates_further_and_infeasible_is_rejected():
    view = build()
    destinations = view["nearby"]+view["further"]
    routes = {p["id"]: {"minutes": 16, "miles": 4, "basis": "live traffic", "fetched_at": NOW.isoformat()}
              for p in destinations}
    limited = build(routes=routes)
    assert not limited["now"] and limited["further"]
    assert all(p["route"]["minutes"] > 15 or not p["within_now_radius"] for p in limited["further"])
    for route in routes.values():
        route["feasible"] = False
    assert not build(routes=routes)["now"]


def test_stale_gps_and_expired_review_withhold_navigation():
    origin = {**ORIGIN, "mode": "device", "fix_at": NOW.isoformat()}
    view = build(origin=origin)
    assert project(view, NOW)["now"]
    stale = project(view, NOW+timedelta(minutes=6))
    assert stale["location_stale"] and not stale["now"]
    assert "Location is stale" in stale["decision_message"]
    assert not project(build(), NOW+timedelta(minutes=21))["now"]


def test_movement_changes_proximity_choice_without_fixed_favorite():
    first = build(origin=radar.origin("Downtown Kirkland"))
    second = build(origin=radar.origin("Downtown Redmond"))
    assert first["now"][0]["id"] != second["now"][0]["id"]
    for view in (first, second):
        assert all(p["within_now_radius"] and p["route"]["minutes"] <= 15 for p in view["now"])


def test_unknown_gate_values_fail_closed():
    import yaml
    policy = yaml.safe_load(decision_policy.PATH.read_bytes())
    policy["positioning_fallback_enabled"] = "yes"
    with pytest.raises(ValueError, match="boolean"):
        decision_policy.parse(yaml.safe_dump(policy).encode())


def test_http_contract_preserves_fallback_type_and_coverage(monkeypatch):
    from fastapi.testclient import TestClient
    from farol.api import app
    from farol import radar_api
    from unittest.mock import patch
    policy = {**decision_policy.load(), "mode": "live", "positioning_fallback_enabled": True}
    monkeypatch.setattr(decision_policy, "load", lambda: policy)
    monkeypatch.setattr(decision_policy, "status", lambda: policy)
    with patch.object(radar_api, "read_inputs", return_value=({}, {})):
        response = TestClient(app).post('/api/radar/preview', json={'area': 'Downtown Kirkland'})
    assert response.status_code == 200
    payload = response.json()
    # The current daytime catalog window is supplied by the real clock in this
    # API path; domain tests above exercise explicit overnight/closed windows.
    if payload['now']:
        assert payload['now'][0]['decision_class'] == 'contextual_fallback'
        assert payload['now'][0]['hours_status'] == 'unknown'
        assert 'unverified' in payload['decision_message']
        assert payload['now'][0]['evidence'][0]['role'] == 'context'
    assert payload['venue_coverage']['collection_paused']
    RadarView.model_validate(payload)
