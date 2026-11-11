"""Expired sessions cannot retain or republish location-bearing radar history."""
import copy
import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException, Response

from farol import radar, radar_api


@pytest.fixture
def session(monkeypatch):
    now = datetime.now(UTC)
    origin = radar.origin("Seattle Center")
    view = radar.build(origin, {}, {}, now=now)
    view["context_generation"] = 10
    for key, value in {"_context": origin, "_view": view, "_generation": 10, "_last_touch": 100.,
                       "_next_run": 100., "_refreshing": False, "_last_provider_pull": 100.,
                       "_snapshots": {view["snapshot_id"]: view}, "_ask_jobs": {},
                       "_stop": threading.Event(), "_wake": threading.Event()}.items():
        monkeypatch.setattr(radar_api, key, value)
    clock = [100.]
    monkeypatch.setattr(radar_api.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(radar_api, "start", lambda: None)
    monkeypatch.setattr(radar_api, "read_inputs", lambda: ({}, {}))
    monkeypatch.setattr("farol.local_runtime.cleanup_status", dict)
    return clock, view


def test_inactive_session_clears_all_retained_origins_and_answers_without_cancelling_work(session):
    clock, view = session
    radar_api._ask_jobs["old"] = {"state": "ready", "answer": {**view, "question": "private fixture question"}}
    radar_api._refreshing = True
    clock[0] += radar_api.SESSION_SECONDS
    radar_api.prune_private_state()
    assert radar_api._context is not None
    clock[0] += .01
    with patch("farol.adapters.routes.clear_private_cache") as clear:
        radar_api.prune_private_state()
        radar_api.prune_private_state()
    assert radar_api._context is radar_api._view is None
    assert not radar_api._snapshots and not radar_api._ask_jobs
    assert radar_api._generation == 11
    assert radar_api._refreshing  # Owned work must finish and clean up itself.
    clear.assert_called_once()
    with pytest.raises(HTTPException) as error:
        radar_api.get_radar(Response())
    assert error.value.status_code == 409


def test_old_snapshot_and_answer_payloads_expire_without_extending_active_session(session):
    _, view = session
    old = {**view, "generated_at": (datetime.now(UTC)-timedelta(minutes=21)).isoformat()}
    radar_api._snapshots["old"] = old
    radar_api._ask_jobs.update(old={"state": "ready", "answer": old}, current={"state": "ready", "answer": view})
    radar_api.prune_private_state()
    assert "old" not in radar_api._snapshots and "old" not in radar_api._ask_jobs
    assert radar_api._ask_jobs["current"]["answer"] == view
    assert radar_api._last_touch == 100.
    assert radar_api._view is view


def test_new_origin_discards_previous_origin_history_and_starts_new_generation(session):
    _, old = session
    radar_api._ask_jobs["old"] = {"state": "ready", "answer": old}
    radar_api.set_context(radar_api.ContextRequest(area="Bellevue"), Response())
    assert radar_api._generation == 11
    assert radar_api._view["origin"]["zone"] == "bellevue_core"
    assert list(radar_api._snapshots) == [radar_api._view["snapshot_id"]]
    assert not radar_api._ask_jobs


def test_late_question_answer_cannot_repopulate_an_expired_session(session):
    clock, view = session
    pending, cleaned = [], []

    def answer(*args, **kwargs):
        assert kwargs["valid"]()
        try:
            clock[0] += radar_api.SESSION_SECONDS + 1
            return copy.deepcopy(view)
        finally:
            cleaned.append(True)

    with patch.object(radar_api, "_start_ask_work", side_effect=pending.append), \
            patch.object(radar, "ask_model", side_effect=answer):
        job = radar_api.ask(radar_api.AskRequest(snapshot_id=view["snapshot_id"], question="Fixture question"), Response())
        pending[0]()
    assert cleaned == [True]
    assert not radar_api._ask_jobs and not radar_api._snapshots
    assert radar_api._context is radar_api._view is None
    with pytest.raises(HTTPException) as error:
        radar_api.ask_job(job["job_id"], Response())
    assert error.value.status_code == 404


def test_late_scheduled_result_cannot_repopulate_expired_context(session):
    clock, view = session

    def answer(*args, **kwargs):
        assert kwargs["valid"]()
        clock[0] += radar_api.SESSION_SECONDS + 1
        return copy.deepcopy(view)

    with patch.object(radar_api, "_routes", return_value={}), patch.object(radar, "ask_model", side_effect=answer):
        radar_api.run_once()
    assert radar_api._context is radar_api._view is None
    assert not radar_api._snapshots
    assert not radar_api._refreshing


def test_session_expiring_between_validation_and_admission_cannot_create_a_job(session):
    clock, view = session

    def validate(_):
        clock[0] += radar_api.SESSION_SECONDS + 1
        return {"evidence_stale": False}

    with patch.object(radar_api, "_public", side_effect=validate), \
            patch.object(radar_api, "_start_ask_work") as start, pytest.raises(HTTPException) as error:
        radar_api.ask(radar_api.AskRequest(snapshot_id=view["snapshot_id"], question="Fixture question"), Response())
    assert error.value.status_code == 409
    assert not radar_api._ask_jobs
    start.assert_not_called()


def test_stop_invalidates_results_but_does_not_pretend_active_cleanup_has_finished(session):
    _, view = session
    radar_api._refreshing = True
    radar_api._ask_jobs["held"] = {"state": "running", "answer": view}
    radar_api.stop()
    assert radar_api._stop.is_set() and radar_api._wake.is_set()
    assert radar_api._generation == 11
    assert radar_api._refreshing
    assert radar_api._context is radar_api._view is None
    assert not radar_api._ask_jobs and not radar_api._snapshots
