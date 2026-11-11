from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from farol.api import app
from farol.podcast import recording_plan


def test_recording_plan_preserves_transcript_order_and_real_calculation():
    with patch("farol.adapters.gather_signals", side_effect=AssertionError("no collection")), \
         patch("farol.local.complete", side_effect=AssertionError("no model")):
        plan = recording_plan()
    assert plan["timing"] == "estimated_from_word_position"
    assert plan["word_count"] == 1163
    assert [cue["id"] for cue in plan["cues"]] == [
        "intro", "hotspots", "data", "around", "collect", "reasoning", "gemma", "qwen",
        "decision", "cohost", "local", "flight", "transit", "ending"]
    fractions = [cue["fraction"] for cue in plan["cues"]]
    assert fractions == sorted(set(fractions))
    assert fractions[0] == 0 and fractions[-1] < 1
    assert plan["states"][0]["comparison"]["answer"].startswith("Watch Bellevue")
    assert plan["states"][1]["comparison"]["answer"].startswith("Watch Kirkland")
    for state in plan["states"]:
        assert state["context"]["mode"] == "demo"
        assert not state["context"]["private_history_read"]
        assert not state["context"]["navigation_available"]


def test_changed_transcript_fails_instead_of_inventing_timing():
    with pytest.raises(ValueError, match="missing or out of order"):
        recording_plan("Unrelated transcript")


def test_recording_routes_and_public_evaluation_fields():
    client = TestClient(app)
    for path in ("/podcast", "/podcast.js", "/podcast.css", "/api/podcast"):
        response = client.get(path)
        assert response.status_code == 200
    response = client.get("/api/podcast")
    assert response.headers["cache-control"] == "no-store"
    for row in response.json()["model_checks"]:
        assert set(row) == {"model", "profile", "passed", "total", "guarded_passed"}
    with patch("farol.podcast.recording_plan", side_effect=ValueError("private filename")):
        error = client.get("/api/podcast")
        assert error.status_code == 503
        assert "private filename" not in error.text
