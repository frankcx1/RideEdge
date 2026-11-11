import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import Response
from pydantic import ValidationError

from farol import radar, radar_api
from farol.radar_contract import RadarView, project

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/contracts/radar-v1.json"
NOW = datetime(2026, 11, 1, 6, tzinfo=UTC)
ORIGIN = {"label": "Seattle Center", "zone": "seattle_center", "mode": "selected_area",
          "latitude": 47.6205, "longitude": -122.3509}


def test_shared_fixture_and_additive_fields_validate():
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    value["future_optional_field"] = {"additional": True}
    parsed = RadarView.model_validate(value)
    assert parsed.schema_version == 1
    assert parsed.now[0].id == parsed.plan[0].selected_id
    assert parsed.model_dump()["future_optional_field"] == {"additional": True}
    assert (parsed.plan[-1].ends_at - parsed.plan[0].starts_at).total_seconds() == 6*3600


@pytest.mark.parametrize("value", [True, "1", 1.0, 2])
def test_wrong_schema_type_or_major_fails(value):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["schema_version"] = value
    with pytest.raises(ValidationError):
        RadarView.model_validate(payload)


def test_missing_required_coordinates_never_become_zero():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    del payload["now"][0]["latitude"]
    with pytest.raises(ValidationError):
        RadarView.model_validate(payload)


def test_expiry_is_recomputed_without_mutating_stored_view():
    view = radar.build(ORIGIN, {}, {}, now=NOW)
    original = copy.deepcopy(view)
    fresh = project(view, NOW)
    late = project(view, NOW+timedelta(minutes=21))
    assert fresh["now"] and not late["now"]
    assert late["evidence_stale"] and late["plan"]
    assert fresh["decision_revision"] == late["decision_revision"]
    assert view == original


def test_small_origin_change_rechecks_actual_radius_and_route():
    view = radar.build(ORIGIN, {}, {}, now=NOW)
    lead = view["now"][0]
    # Synthetic boundary fixture: same previously chosen ID, now outside 5 mi.
    lead["latitude"] = ORIGIN["latitude"] + 4.95/69.1
    lead["longitude"] = ORIGIN["longitude"]
    lead["route"] = {"minutes": 1, "miles": .2, "basis": "live traffic", "fetched_at": NOW.isoformat()}
    view["origin"] = {**ORIGIN, "latitude": ORIGIN["latitude"] - .2/69.1}
    projected = project(view, NOW)
    assert projected["now"] == []
    assert projected["evidence_stale"]
    assert view["now"][0]["route"]["basis"] == "live traffic"  # no mutation


def test_stale_device_fix_and_event_arrival_deadline_gate_actions():
    device = {**ORIGIN, "mode": "device", "fix_at": NOW.isoformat(), "accuracy_meters": 10}
    view = radar.build(device, {}, {}, now=NOW)
    lead = view["now"][0]
    lead["ends_at"] = (NOW+timedelta(minutes=lead["route"]["minutes"]+11)).isoformat()
    assert project(view, NOW)["now"]
    assert not project(view, NOW+timedelta(minutes=2))["now"]
    expired = project(view, NOW+timedelta(minutes=6))
    assert expired["location_stale"] and not expired["further"]


def test_source_expiry_can_be_shorter_than_snapshot_expiry():
    view = radar.build(ORIGIN, {}, {}, now=NOW)
    evidence = view["now"][0]["evidence"][0]
    evidence.update(basis="live", fetched_at=(NOW-timedelta(minutes=44)).isoformat(),
                    expires_at=(NOW+timedelta(seconds=30)).isoformat())
    assert project(view, NOW)["now"]
    assert not project(view, NOW+timedelta(seconds=31))["now"]


def test_scheduler_uses_actual_monotonic_deadline_and_preview_is_independent():
    view = radar.build(ORIGIN, {}, {}, now=datetime.now(UTC))
    with patch.multiple(radar_api, _context=ORIGIN, _view=view, _last_touch=100, _next_run=220,
                        _refreshing=False), patch.object(radar_api.time, "monotonic", return_value=100):
        public = radar_api._public(view)
        deadline = radar.stamp(public["next_refresh_at"])
        assert (deadline-radar.stamp(public["server_time"])).total_seconds() == 120
        assert radar_api._public(view, preview=True)["scheduler"]["state"] == "preview"


def test_api_projection_satisfies_contract():
    view = radar.build(ORIGIN, {}, {}, now=datetime.now(UTC))
    with patch.multiple(radar_api, _context=ORIGIN, _view=view, _last_touch=radar_api.time.monotonic()):
        parsed = RadarView.model_validate(radar_api.get_radar(Response()))
        assert parsed.schema_version == 1 and len(parsed.plan) == 6


def test_ask_uses_latest_fix_without_changing_candidate_snapshot():
    now = datetime.now(UTC)
    old = {**ORIGIN, "mode": "device", "fix_at": (now-timedelta(minutes=6)).isoformat(), "accuracy_meters": 10}
    current = {**old, "fix_at": now.isoformat()}
    view = radar.build(old, {}, {}, now=now)
    view["context_generation"] = 7
    with patch.multiple(radar_api, _context=current, _generation=7, _snapshots={view["snapshot_id"]: view}, _ask_jobs={},
                        _last_touch=radar_api.time.monotonic()), \
            patch.object(radar_api, "_start_ask_work") as schedule:
        result = radar_api.ask(radar_api.AskRequest(snapshot_id=view["snapshot_id"], question="Compare options"), Response())
        assert result["state"] == "running"
        schedule.assert_called_once()
        assert view["origin"]["fix_at"] == old["fix_at"]  # stored snapshot stays immutable


def test_old_completed_question_is_not_returned_as_current_after_origin_change():
    result = {"state": "ready", "job_id": "fixture", "context_generation": 7,
              "answer": {"private": "old", "generated_at": datetime.now(UTC).isoformat()}}
    with patch.multiple(radar_api, _generation=8, _ask_jobs={"fixture": result}):
        response = radar_api.ask_job("fixture", Response())
        assert response["state"] == "failed" and "answer" not in response
