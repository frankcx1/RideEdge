import copy
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from farol import besttime_live, collect, radar
from farol.besttime import normalize_forecast, normalize_live, review_entry

NOW = datetime(2026, 10, 25, 2, 30, tzinfo=UTC)
REQUESTED = {"id": "fixture", "name": "Fixture Dining", "address": "100 Fixture St", "city": "Bellevue",
             "zone": "bellevue_core", "latitude": 47.6155, "longitude": -122.2015}
INFO = {"venue_id": "provider-fixture", "venue_name": "Fixture Dining", "venue_address": "100 Fixture St Bellevue",
        "venue_lat": 47.6155, "venue_lng": -122.2015}


def receipt(live=False):
    analysis = ({"venue_live_busyness_available": True, "venue_live_busyness": 90,
                 "venue_forecast_busyness_available": True, "venue_forecasted_busyness": 60} if live
                else [{"day_info": {"day_int": 5}, "day_raw": [60] * 24}])
    return {"http_status": 200, "retrieved_at": NOW.isoformat(),
            "payload": {"status": "OK", "venue_info": dict(INFO), "analysis": analysis}}


def entry():
    return {"requested": dict(REQUESTED), "identity_matched": True,
            "forecast": normalize_forecast(receipt()),
            "live": normalize_live(receipt(True), INFO["venue_id"])}


def test_retained_wrong_branch_is_rejected_despite_true_flag_and_available_reading():
    retained = entry()
    retained["forecast"]["venue"]["venue_address"] = "900 Wrong Branch Bellevue"
    saved = copy.deepcopy(retained)
    checked = review_entry(retained)
    assert not checked["identity_matched"]
    assert checked["identity_review"]["reported_identity_matched"] is True
    assert not checked["identity_review"]["live_matched"]
    view = radar.build(radar.origin("Bellevue"), {}, {"venues": [retained]}, now=NOW)
    assert all(r["id"] != "venue:fixture" for s in view["plan"] for r in s["options"])
    assert any(e["code"] == "unmatched_venue" for e in view["excluded"])
    assert retained == saved


def test_legacy_live_without_identity_uses_matched_weekly_pattern_and_discloses_why(tmp_path):
    retained = entry()
    del retained["live"]["venue_id"]
    del retained["live"]["identity_matched"]
    checked = review_entry(retained)
    assert checked["identity_matched"] and not checked["identity_review"]["live_matched"]
    assert checked["live"]["busyness"] == 90
    assert review_entry(checked) == checked
    view = radar.build(radar.origin("Bellevue"), {}, {"venues": [retained]}, now=NOW)
    venue = next(r for r in view["nearby"] if r["id"] == "venue:fixture")
    assert venue["busyness"] == 60 and venue["strength"] == "Typical pattern"
    health = {"feeds": [{"adapter": "besttime_busyness", "label": "BestTime", "category": "venues"}]}
    with patch.object(collect, "feed_health_view", return_value=health), \
            patch("farol.adapters.base.cache_dir", return_value=tmp_path), \
            patch("farol.awareness.saved_besttime", return_value={"venues": [retained]}):
        record = collect.feed_detail_view("besttime_busyness", NOW)["records"][0]
    assert record["live_busyness_pct"] == 90 and not record["live_usable_for_radar"]
    assert "Live venue identity is unverified" in record["detail"]


@pytest.mark.parametrize("failure", [None, "wrong_forecast_branch", "wrong_live_id", "provider_error", "bool", "nan"])
def test_actual_poller_does_not_resurrect_rejected_live_values(tmp_path, monkeypatch, failure):
    fc, live = receipt(), receipt(True)
    if failure == "wrong_forecast_branch":
        fc["payload"]["venue_info"]["venue_address"] = "900 Wrong Branch Bellevue"
    elif failure == "wrong_live_id":
        live["payload"]["venue_info"]["venue_id"] = "wrong-id"
    elif failure == "provider_error":
        live["payload"]["status"] = "Error"
    elif failure in {"bool", "nan"}:
        live["payload"]["analysis"]["venue_live_busyness"] = True if failure == "bool" else float("nan")
    monkeypatch.setenv("BESTTIME_API_KEY_PRIVATE", "fixture-private")
    monkeypatch.setenv("BESTTIME_API_KEY_PUBLIC", "fixture-public")
    monkeypatch.setattr(besttime_live, "BESTTIME_UBER_VENUES", [REQUESTED])
    monkeypatch.setattr(besttime_live, "_active_dir", lambda: tmp_path)
    monkeypatch.setattr(besttime_live, "_read_json", lambda path: None)
    monkeypatch.setattr(besttime_live, "_PUBLISHED_BY_CONTEXT", {})
    monkeypatch.setattr(besttime_live, "_merge_radar_hotspots", lambda **kwargs: 0)
    monkeypatch.setattr(besttime_live, "_inject_besttime_signals_into_snapshot", lambda *args: None)
    saved = {}
    monkeypatch.setattr(besttime_live, "save", lambda path, data: saved.update({path.name: copy.deepcopy(data)}))
    with patch.object(besttime_live, "_bt_post", side_effect=[fc, live]) as transport:
        besttime_live.poll_besttime_venues("Bellevue", max_venues=1)
    checked = saved["report.json"]["venues"][0]
    assert transport.call_count == 2
    assert checked["identity_matched"] is (failure != "wrong_forecast_branch")
    usable = checked["live"].get("available") and checked["identity_review"]["live_matched"]
    assert bool(usable) is (failure is None)
    if failure != "wrong_forecast_branch":
        assert transport.call_args_list[1].args[1] == {"venue_id": INFO["venue_id"]}
    # Invalid provider values stay in the sanitized raw receipt, never promoted by a fallback.
    assert saved["fixture.live.json"]["payload"]["status"] == live["payload"]["status"]


def test_unmatched_entry_cannot_inject_live_demand_signals():
    retained = entry()
    retained["forecast"]["venue"]["venue_address"] = "900 Wrong Branch Bellevue"
    writes = []
    with patch.object(besttime_live, "_read_json", return_value={"signals": []}), \
            patch.object(besttime_live, "save", side_effect=lambda path, data: writes.append(data)):
        besttime_live._inject_besttime_signals_into_snapshot([retained], NOW+timedelta(minutes=1))
    assert writes and writes[-1]["signals"] == []
