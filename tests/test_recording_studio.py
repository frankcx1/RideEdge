import copy
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from farol.api import app
from farol.radar_contract import RadarView
from farol.studio import demo_scene, studio_data


def test_demo_contracts_and_changes_are_consistent():
    scenes = [demo_scene(i) for i in range(8)]
    winners = []
    for s in scenes:
        RadarView.model_validate(s["radar"])
        winners.append(s["radar"]["now"][0]["id"])
        assert len(s["health"]["feeds"]) == 23
        assert len(s["radar"]["plan"]) == 6
        assert s["radar"]["qwen"]["state"] == "demo"
        assert s["radar"]["synthetic"] is True
        assert s["radar"]["now"][0]["qwen_reason"]
    assert len(set(winners)) == 8
    assert all(p["radius_miles"] <= 5 for s in scenes for p in s["radar"]["now"])
    assert scenes[0]["radar"]["now"][0]["id"] == "demo:bellevue"
    assert scenes[7]["radar"]["now"][0]["id"] == "demo:kirkland"
    assert scenes[7]["radar"]["plan"][-1]["selected_id"] is None


def test_replay_reads_no_live_sources_or_model():
    with patch("farol.collect.feed_health_view", side_effect=AssertionError("live read")), \
         patch("farol.radar_api.source_participation", side_effect=AssertionError("live state")), \
         patch("urllib.request.urlopen", side_effect=AssertionError("network")):
        result = studio_data("replay", 1)
        assert result["runtime"] is None
        assert len(result["health"]["feeds"]) == 23
        assert "selected" not in result and "plan" not in result
        assert result["besttime"]["state"] == "paused"


def test_studio_live_is_read_only_and_does_not_expose_origin():
    from farol import radar_api
    view = demo_scene(0)["radar"]
    original = copy.deepcopy(view)
    with patch.object(radar_api, "_view", view), \
         patch("farol.collect.feed_health_view", return_value={"feeds":[]}), \
         patch("farol.studio_monitor.probes", return_value={"model":{}, "hardware":{}}), \
         patch.object(radar_api, "source_participation", side_effect=AssertionError("mutating accessor")), \
         patch.object(radar_api, "run_once", side_effect=AssertionError("inference")), \
         patch("urllib.request.urlopen", side_effect=AssertionError("network")):
        result = studio_data("live", 0)
        assert "origin" not in result
        assert "selected" not in result and "plan" not in result
        assert "latitude" not in json.dumps(result)
        assert result["runtime"]["scheduler"]["last_review_state"] == "demo"
        assert view == original
    client = TestClient(app)
    assert client.get("/studio").status_code == 200
    assert client.get("/api/studio?mode=bad").status_code == 422
    assert client.get("/api/studio?mode=replay&step=8").status_code == 422
