import copy
import json
import time
from io import BytesIO
from unittest.mock import patch

import pytest

from farol import model_metrics, radar_api, studio_monitor
from farol.model_queue import ModelQueue


def test_numeric_receipts_rates_missing_fields_and_private_data(tmp_path):
    payload = {"choices": [{"message": {"content": "PRIVATE ANSWER"}}],
               "usage": {"prompt_tokens": 100, "completion_tokens": 20},
               "timings": {"predicted_n": 20, "predicted_ms": 500, "prompt_per_second": 2000,
                           "prompt_n": 40, "cache_n": 60}}
    model_metrics.record(payload, 1.25, "qwen-test")
    result = model_metrics.snapshot()["samples"][0]
    assert result["generation_tokens_per_second"] == 40
    assert result["prompt_tokens_per_second"] == 2000
    assert result["request_seconds"] == 1.25
    assert result["cached_tokens"] == 60
    assert "PRIVATE ANSWER" not in model_metrics.path().read_bytes().decode("latin1")
    missing = model_metrics.receipt({"usage": {"completion_tokens": 30}}, 2, "qwen")
    assert missing["generation_tokens_per_second"] is None  # Never mistake HTTP throughput for decode speed.
    bad = model_metrics.receipt({"timings": {"predicted_ms": 0, "predicted_n": 5, "prompt_per_second": float('nan')}}, 1, "qwen")
    assert bad["generation_tokens_per_second"] is bad["prompt_tokens_per_second"] is None
    for _ in range(105):
        model_metrics.record({}, 1, "qwen")
    assert model_metrics.snapshot()["retained_count"] == 100
    assert len(model_metrics.snapshot()["samples"]) == 12


def test_metrics_failure_never_breaks_model_response(monkeypatch, tmp_path):
    target = tmp_path / "not-a-database"
    target.mkdir()
    monkeypatch.setenv("RIDEEDGE_MODEL_METRICS_FILE", str(target))
    model_metrics.record({}, 1, "qwen")
    assert model_metrics.snapshot()["state"] == "unavailable"


def test_queue_history_counts_failures_and_is_bounded():
    queue = ModelQueue()
    for _ in range(14):
        with queue.admit("radar-plan"):
            assert queue.status()["active_since"]
    with pytest.raises(ValueError), queue.admit("radar-question"):
        raise ValueError("PRIVATE QUESTION")
    status = queue.status()
    assert status["completed"] == 14 and status["failed"] == 1
    assert len(status["recent"]) == 12 and status["recent"][0]["state"] == "failed"
    assert "PRIVATE QUESTION" not in json.dumps(status)


class Alive:
    def is_alive(self):
        return True


def test_monitor_observes_scheduler_without_extending_session(monkeypatch):
    monkeypatch.setattr(studio_monitor, "probes", lambda: {"model": {}, "hardware": {}})
    monkeypatch.setattr(radar_api, "_thread", Alive())
    monkeypatch.setattr(radar_api, "_stop", __import__('threading').Event())
    monkeypatch.setattr(radar_api, "_context", {"latitude": 47.5, "longitude": -122.1})
    monkeypatch.setattr(radar_api, "_last_touch", time.monotonic())
    monkeypatch.setattr(radar_api, "_next_run", time.monotonic() + 800)
    monkeypatch.setattr(radar_api, "_refreshing", False)
    monkeypatch.setattr(radar_api, "_view", {"runtime": None})
    with patch("farol.local_runtime.cleanup_status", return_value={}):
        before = radar_api._last_touch
        result = studio_monitor.snapshot()
        assert result["scheduler"]["state"] == "scheduled"
        assert result["scheduler"]["next_review_at"]
        assert radar_api._last_touch == before
        assert "latitude" not in json.dumps(result)
        monkeypatch.setattr(radar_api, "_last_touch", time.monotonic() - radar_api.SESSION_SECONDS - 1)
        result = studio_monitor.snapshot()
        assert result["scheduler"]["state"] == "session_expired"
        assert result["scheduler"]["next_review_at"] is None


def test_model_probe_requires_expected_identity_and_health():
    class Response(BytesIO):
        status = 200
    with patch("farol.local_runtime.settings", return_value=("http://127.0.0.1:1234/v1/chat/completions", "qwen")):
        with patch.object(studio_monitor, "urlopen", side_effect=[Response(b'{"data":[{"id":"qwen"}]}'), Response(b'{}')]):
            assert studio_monitor.probe_model()["loaded"] is True
        with patch.object(studio_monitor, "urlopen", return_value=Response(b'{"data":[{"id":"other"}]}')) as call:
            result = studio_monitor.probe_model()
            assert result["state"] == "different_model" and not result["loaded"]
            assert call.call_count == 1
        with patch.object(studio_monitor, "urlopen", side_effect=OSError()):
            assert studio_monitor.probe_model()["state"] == "unavailable"
