from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from farol import besttime_control as policy
from farol.besttime import BestTimeClient
from farol import besttime_live


@pytest.fixture(autouse=True)
def isolated_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("RIDEEDGE_BESTTIME_CONTROL_FILE", str(tmp_path / "policy.sqlite3"))


def test_paused_blocks_all_transports_and_force_poll_without_touching_cache(tmp_path):
    assert policy.status()["state"] == "paused"
    with patch.object(besttime_live, "urlopen", side_effect=AssertionError("paid call")), \
            patch("farol.besttime.urlopen", side_effect=AssertionError("paid call")), \
            patch.object(besttime_live, "save", side_effect=AssertionError("cache rewrite")):
        assert besttime_live.poll_besttime_venues(force_live=True)["http_requests_made"] == 0
        with pytest.raises(policy.BestTimePaused):
            besttime_live._bt_post("/forecasts/live", {}, "private", "public")
        with pytest.raises(policy.BestTimePaused):
            BestTimeClient("private", "public", tmp_path)._request("GET", "/test")
        with pytest.raises(policy.BestTimePaused):
            besttime_live._merge_radar_hotspots(by_id={}, lat=0, lon=0, radius_m=1,
                                              private_key="p", public_key="p", now=None, registry=None)


def test_allowance_is_atomic_expires_and_pause_does_not_require_restart():
    policy.configure(10, 3)
    def attempt(_):
        try:
            policy.reserve_request()
            return 1
        except policy.BestTimePaused:
            return 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(20))) == 3
    assert policy.status()["enabled"] is False
    policy.configure(1, 3)
    with patch.object(policy.time, "time", return_value=policy.status()["expires_at_epoch"] + 1):
        with pytest.raises(policy.BestTimePaused):
            policy.reserve_request()
    policy.configure(10, 3)
    policy.configure()
    with pytest.raises(policy.BestTimePaused):
        policy.reserve_request()
