import copy
import json
import os
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from farol import brain, grok, local_runtime, model_queue, qwen
from farol.adapters import grok_research, grok_watch
from farol.adapters.base import FeedError
from farol.api import app
from farol.tonight import tonight_brief

URL = "http://127.0.0.1:1234/v1/chat/completions"
ALIAS = "qwen3.8-27b"


@pytest.fixture(autouse=True)
def isolated_policy(monkeypatch):
    monkeypatch.setattr(model_queue, "queue", model_queue.ModelQueue())
    monkeypatch.setenv("FAROL_BRAIN", "qwen")
    monkeypatch.setenv("FAROL_LOCAL_URL", URL)
    monkeypatch.setenv("FAROL_LOCAL_MODEL", ALIAS)
    monkeypatch.setenv("FAROL_LOCAL_MANAGE", "ondemand")
    monkeypatch.setattr(qwen, "_running", None)
    monkeypatch.setattr(qwen, "_retry_until", 0)
    monkeypatch.setattr(qwen, "_failures", {})
    monkeypatch.setattr(qwen, "_last", {"mode": "idle"})
    monkeypatch.setattr(local_runtime, "_last_cleanup", {})


def test_qwen_is_default_and_does_not_switch_to_cloud_outside_a_shift(monkeypatch):
    monkeypatch.delenv("FAROL_BRAIN")
    assert grok.brain_name() == "qwen"
    for active in (False, True):
        with patch("farol.shift.active", return_value=active):
            assert brain._effective_brain() == "qwen"


def test_cloud_research_watch_and_narration_are_blocked_even_with_a_key(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    now = datetime.now(UTC)
    with patch("farol.grok.fetch_json") as network, \
         patch.object(grok_research, "fetch_json") as research_network, \
         patch.object(grok_research, "read_cache", side_effect=AssertionError("No old cloud evidence")), \
         patch.object(grok_watch, "read_cache", side_effect=AssertionError("No old cloud evidence")):
        for adapter in (grok_research, grok_watch):
            rows, status = adapter.fetch(now, now + timedelta(hours=6))
            assert rows == [] and status.mode == "disabled"
        with pytest.raises(FeedError, match="disabled"):
            grok.complete(system="test", user="{}", cache_key="test", prompt_cache_key="test")
        with pytest.raises(FeedError, match="disabled"):
            grok_research._call_grok(now, now + timedelta(hours=6))
    network.assert_not_called()
    research_network.assert_not_called()


@pytest.mark.parametrize("status", ["valid", "orphan-grace", "stale", "expired-live", "acquiring",
                                    "reclaiming", "releasing", "restore-failed", "malformed"])
def test_other_gpu_work_is_never_reclaimed_or_interrupted(status):
    with patch.object(local_runtime, "lease_status", return_value={
        "status": status, "lease": {"owner": "opencode-qwen", "lease_id": "other"}}), \
         patch("farol.shift.status", return_value={"phase": "idle"}), \
         patch("farol.shift.start") as start, patch("farol.shift.stop") as stop, \
         patch.object(local_runtime, "model_ready") as probe, \
         pytest.raises(local_runtime.ModelBusy, match="opencode-qwen"):
        with local_runtime.session(URL, ALIAS):
            pytest.fail("Must not send a prompt while another borrower owns the GPU")
    start.assert_not_called()
    stop.assert_not_called()
    probe.assert_not_called()


@pytest.mark.parametrize("generation_fails", [False, True])
def test_idle_loan_is_restored_after_success_or_generation_failure(generation_fails):
    with patch.object(local_runtime, "lease_status", return_value={"status": "free"}), \
         patch("farol.shift.status", return_value={"phase": "idle"}), \
         patch("farol.shift.start", return_value={"ok": True}) as start, \
         patch("farol.shift.stop", return_value={"ok": True}) as stop, \
         patch.object(local_runtime, "model_ready", return_value=True):
        try:
            with local_runtime.session(URL, ALIAS):
                if generation_fails:
                    raise FeedError("Test inference failure")
        except FeedError:
            assert generation_fails
    assert start.call_args.kwargs == {"owner_pid": os.getpid(), "model_profile": "qwen", "mode": "narrating"}
    stop.assert_called_once()


def test_driving_lease_is_reused_and_retained():
    with patch.object(local_runtime, "lease_status", return_value={
        "status": "valid", "lease": {"owner": "farol", "lease_id": "ours"}}), \
         patch("farol.shift.status", return_value={"phase": "driving", "owner_pid": os.getpid(),
                                                   "lease_id": "ours"}), \
         patch("farol.shift.start") as start, patch("farol.shift.stop") as stop, \
         patch.object(local_runtime, "model_ready", return_value=True):
        with local_runtime.session(URL, ALIAS):
            pass
    start.assert_not_called()
    stop.assert_not_called()


def test_failed_acquisition_cannot_stop_another_owner():
    with patch.object(local_runtime, "lease_status", return_value={"status": "free"}), \
         patch("farol.shift.status", return_value={"phase": "idle"}), \
         patch("farol.shift.start", return_value={"ok": False}), \
         patch("farol.shift.stop") as stop, pytest.raises(local_runtime.ModelBusy):
        with local_runtime.session(URL, ALIAS):
            pytest.fail("Acquisition failed")
    stop.assert_not_called()


def test_model_mismatch_after_a_loan_still_restores_the_loan():
    with patch.object(local_runtime, "lease_status", return_value={"status": "free"}), \
         patch("farol.shift.status", return_value={"phase": "idle"}), \
         patch("farol.shift.start", return_value={"ok": True}), \
         patch("farol.shift.stop", return_value={"ok": True}) as stop, \
         patch.object(local_runtime, "model_ready", return_value=False), \
         pytest.raises(FeedError, match="does not match"):
        with local_runtime.session(URL, ALIAS):
            pytest.fail("Model identity mismatch")
    stop.assert_called_once()


def test_lease_restore_failure_is_not_silently_ignored():
    with patch.object(local_runtime, "lease_status", return_value={"status": "free"}), \
         patch("farol.shift.status", return_value={"phase": "idle"}), \
         patch("farol.shift.start", return_value={"ok": True}), \
         patch("farol.shift.stop", return_value={"ok": False}), \
         patch.object(local_runtime, "model_ready", return_value=True):
        with local_runtime.session(URL, ALIAS) as outcome:
            pass
    assert outcome.inference_state == "completed"
    assert outcome.release_result["state"] == "restoration_failed"
    assert local_runtime.cleanup_status()["state"] == "restoration_failed"


@pytest.mark.parametrize("cleanup_exception", [False, True])
def test_cleanup_failure_never_masks_original_generation_error(cleanup_exception):
    failure = ValueError("original model output failure")
    with patch.object(local_runtime, "lease_status", return_value={"status": "free"}), \
         patch("farol.shift.status", return_value={"phase": "idle"}), \
         patch("farol.shift.start", return_value={"ok": True}), \
         patch("farol.shift.stop", side_effect=OSError("private diagnostic") if cleanup_exception else None,
               return_value={"ok": False}) as stop, \
         patch.object(local_runtime, "model_ready", return_value=True):
        with pytest.raises(ValueError) as caught:
            with local_runtime.session(URL, ALIAS) as outcome:
                raise failure
    assert caught.value is failure
    assert outcome.inference_state == "failed"
    assert outcome.release_result["state"] == "restoration_failed"
    assert "private diagnostic" not in json.dumps(outcome.public())
    stop.assert_called_once()


def test_free_lease_alone_cannot_clear_prior_cleanup_failure():
    local_runtime._record_cleanup({"state": "restoration_failed"})
    with patch.object(local_runtime, "lease_status", return_value={"status": "free"}), \
         patch("farol.shift.status", return_value={"phase": "error"}), \
         patch("farol.shift.start") as start, \
         pytest.raises(local_runtime.RestorationBlocked):
        with local_runtime.session(URL, ALIAS):
            pytest.fail("Unverified recovery")
    start.assert_not_called()


def test_radar_keeps_valid_answer_with_cleanup_warning():
    from farol import radar
    now = datetime(2026, 10, 25, 2, 30, tzinfo=UTC)
    view = radar.build(radar.origin("Seattle"), {}, {}, now=now)

    def complete(**kw):
        schema = kw["response_schema"]["properties"]
        selection = {key: value["enum"][0] for key, value in schema.items()}
        return {"choices": [{"message": {"content": json.dumps(selection)}}]}, "live", now.isoformat()

    with patch.object(local_runtime, "lease_status", return_value={"status": "free"}), \
         patch("farol.shift.status", return_value={"phase": "idle"}), \
         patch("farol.shift.start", return_value={"ok": True}), \
         patch("farol.shift.stop", return_value={"ok": False}), \
         patch.object(local_runtime, "model_ready", return_value=True), \
         patch("farol.local.complete", side_effect=complete):
        result = radar.ask_model(view)
    assert result["qwen"]["state"] == "ready"
    assert result["qwen"]["warning"]
    assert result["runtime"]["cleanup"]["state"] == "restoration_failed"
    assert result["now"][0]["id"] == result["plan"][0]["selected_id"]


def test_a_new_loan_gets_a_fresh_heartbeat_event(monkeypatch):
    import threading

    from farol import shift

    old_event = threading.Event()
    old_event.set()
    old_thread = MagicMock()
    old_thread.is_alive.return_value = True
    monkeypatch.setattr(shift, "_hb_stop", old_event)
    monkeypatch.setattr(shift, "_hb_thread", old_thread)
    with patch.object(shift.threading, "Thread") as new_thread:
        shift._start_heartbeat()
    assert old_event.is_set()
    assert shift._hb_stop is not old_event and not shift._hb_stop.is_set()
    assert new_thread.call_args.kwargs["args"] == (shift._hb_stop,)


def test_explicit_external_server_sharing_does_not_manage_its_lifecycle(monkeypatch):
    monkeypatch.setenv("FAROL_LOCAL_MANAGE", "external")
    with patch.object(local_runtime, "lease_status", side_effect=AssertionError("Not our server")), \
         patch.object(local_runtime, "model_ready", return_value=True), \
         patch("farol.shift.start") as start, patch("farol.shift.stop") as stop:
        with local_runtime.session(URL, ALIAS):
            pass
    start.assert_not_called()
    stop.assert_not_called()


def test_model_identity_is_checked_before_a_prompt(monkeypatch):
    monkeypatch.setenv("FAROL_LOCAL_MANAGE", "external")
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({"data": [{"id": "Cydonia"}]}).encode()
    with patch.object(local_runtime, "urlopen", return_value=response) as request, \
         pytest.raises(FeedError, match="different model"):
        with local_runtime.session(URL, ALIAS):
            pytest.fail("Cannot narrate with Cydonia")
    assert request.call_args.args[0].endswith("/v1/models")


@pytest.mark.parametrize("endpoint", ["https://api.example.com/v1/chat/completions",
    "http://user:password@127.0.0.1/v1/chat/completions", "http://127.0.0.1/v1/models"])
def test_qwen_policy_only_sends_to_a_local_completion_endpoint(monkeypatch, endpoint):
    monkeypatch.setenv("FAROL_LOCAL_URL", endpoint)
    with pytest.raises(FeedError, match="loopback"):
        local_runtime.settings()


def test_qwen_mode_does_not_start_gemma_on_the_gpu():
    with patch("farol.shift.status", return_value={"phase": "idle"}), \
         patch("farol.shift.start") as start:
        response = TestClient(app).post("/api/shift/start?model=gemma")
    assert response.status_code == 400
    start.assert_not_called()


def test_brief_returns_immediately_and_only_one_background_request_is_started():
    brief = tonight_brief()
    brief["mock_feeds"] = False
    with patch.object(qwen, "read_cache", return_value=None), \
         patch.object(qwen, "WorkThread") as thread, patch("farol.local.complete") as complete:
        for _ in range(3):
            result = brain.apply(copy.deepcopy(brief))
            assert result["brain"]["model"] == ALIAS
            assert result["brain"]["mode"] == "warming"
            assert result["narration"] is None
    thread.assert_called_once()
    complete.assert_not_called()


def test_busy_result_is_visible_and_rate_limited_without_cloud_fallback():
    brief = tonight_brief()
    brief["mock_feeds"] = False
    with patch.object(qwen, "read_cache", return_value=None), \
         patch.object(qwen, "WorkThread") as thread, \
         patch.object(local_runtime, "session", side_effect=local_runtime.ModelBusy("Coding session is using Qwen")), \
         patch("farol.local.complete") as local, patch("farol.brain.complete") as cloud:
        brain.apply(copy.deepcopy(brief))
        qwen._work(*thread.call_args.kwargs["args"])
        result = brain.apply(copy.deepcopy(brief))
        changed = copy.deepcopy(brief)
        changed["shift_decision"]["value_of_time_per_hour"] = 999
        assert brain.apply(changed)["brain"]["mode"] == "busy"
    assert result["brain"]["mode"] == "busy"
    assert result["brain"]["model"] == ALIAS
    assert result["brain"]["retry_after_seconds"] == 90
    thread.assert_called_once()
    local.assert_not_called()
    cloud.assert_not_called()


def test_success_is_cached_guarded_and_does_not_change_engine_scores():
    brief = tonight_brief()
    brief["mock_feeds"] = False
    before = copy.deepcopy(brief)
    payload = {"choices": [{"message": {"content": json.dumps({
        "headline": "MOVE", "spoken": "Guaranteed $90/hr at an open curb.",
        "shift_rationale": "Guaranteed", "now_move": "MOVE", "risks": [], "opportunity_notes": {}})}}]}
    cache = {}
    def save(key, raw, **kwargs):
        cache[key] = {"fetched_at": datetime.now(UTC).isoformat(), "payload": raw}
    with patch.object(qwen, "read_cache", side_effect=lambda key: cache.get(key)), \
         patch.object(qwen, "write_cache", side_effect=save), \
         patch.object(qwen, "WorkThread") as thread, \
         patch.object(local_runtime, "session", return_value=nullcontext()), \
         patch("farol.local.complete", return_value=(payload, "live", "unused")) as complete:
        brain.apply(copy.deepcopy(brief))
        qwen._work(*thread.call_args.kwargs["args"])
        result = brain.apply(copy.deepcopy(brief))
    assert result["brain"]["model"] == ALIAS and result["brain"]["mode"] == "cache"
    assert "$90" not in json.dumps(result["narration"])
    assert result["narration"]["now_move"] == "WATCH"
    assert result["shift_decision"] == before["shift_decision"]
    assert [(x["id"], x["score"]) for x in result["opportunities"]] == [(x["id"], x["score"]) for x in before["opportunities"]]
    assert complete.call_args.kwargs["model_profile"] == "qwen"
    assert "personal" not in json.loads(complete.call_args.kwargs["user"])
    thread.assert_called_once()
