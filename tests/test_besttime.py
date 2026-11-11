import io
import json
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from farol.besttime import (
    BestTimeClient,
    BudgetExceeded,
    normalize_forecast,
    normalize_live,
    sanitize,
    save,
    venue_match,
)
from farol.besttime_pilot import render_html, run


def response(analysis, **info):
    return {"http_status": 200, "retrieved_at": "2026-09-18T15:00:00+00:00", "payload": {
        "status": "OK", "analysis": analysis, "venue_info": {"venue_id": "ven_test", **info},
    }}


def test_friday_overnight_is_saturday_and_closed_is_distinct_from_zero():
    raw = [0] * 24
    raw[19] = 70
    forecast = normalize_forecast(response([{
        "day_info": {"day_int": 4}, "day_raw": raw,
        "hour_analysis": [{"hour": 6, "intensity_nr": 999}, {"hour": 7, "intensity_nr": -2}],
    }]))
    hours = forecast["days"][0]["hours"]
    assert hours[19] == {"hour": 1, "weekday": 5, "label": "Saturday 01:00",
                         "typical_busyness": 70, "closed": None}
    assert hours[0]["closed"] is True
    assert hours[1]["closed"] is False
    assert hours[1]["typical_busyness"] == 0
    assert forecast["provider_analysis_time"] is None


@pytest.mark.parametrize("available,value,expected", [(False, 0, None), (True, 0, 0),
                                                        (True, 145, 145), (True, -1, None),
                                                        (True, float("nan"), None)])
def test_live_availability_not_truthiness_or_capped_at_100(available, value, expected):
    live = normalize_live(response({
        "venue_live_busyness_available": available, "venue_live_busyness": value,
        "venue_forecast_busyness_available": True, "venue_forecasted_busyness": 50,
    }), "ven_test")
    assert live["busyness"] == expected
    assert live["available"] is (expected is not None)
    assert live["delta_percentage_points"] == (expected - 50 if expected is not None else None)
    assert live["measurement_time"] is None


def test_wrong_venue_and_http_200_provider_error_are_not_live():
    receipt = response({"venue_live_busyness_available": True, "venue_live_busyness": 90})
    assert not normalize_live(receipt, "ven_other")["available"]
    receipt["payload"]["status"] = "Error"
    assert not normalize_live(receipt, "ven_test")["available"]
    assert not normalize_forecast(receipt)["available"]


def test_closed_venue_no_live_response_retains_baseline_without_inventing_live_zero():
    receipt = response({"venue_live_busyness_available": False,
                        "venue_forecast_busyness_available": True,
                        "venue_forecasted_busyness": 0}, venue_open="Closed")
    receipt["payload"].update(status="Error", message="No live data available.")
    live = normalize_live(receipt, "ven_test")
    assert live["state"] == "unavailable"
    assert live["busyness"] is None
    assert live["typical_this_hour"] == 0
    assert live["open_status"] == "Closed"
    assert normalize_live(receipt, "ven_other")["open_status"] is None


def test_wrong_branch_is_rejected():
    requested = {"name": "Caffe Vita", "city": "Seattle", "address": "1005 E Pike St"}
    assert venue_match(requested, {"venue_name": "Caffe Vita",
                                   "venue_address": "1005 E Pike St Seattle, WA 98122"})
    assert not venue_match(requested, {"venue_name": "Caffe Vita",
                                      "venue_address": "472 1st Ave N Seattle, WA 98109"})
    assert not venue_match(requested, {"venue_name": "Other Business",
                                      "venue_address": "1005 E Pike St Seattle, WA 98122"})


def test_budget_counts_failed_attempts_and_resume_does_not_retry(tmp_path):
    client = BestTimeClient("private", "public", tmp_path, budget=2)
    with patch.object(client, "_request", return_value={"http_status": 503, "payload": {}}) as call:
        first = client.fetch("one", "forecast", {"venue_name": "One"})
        assert client.fetch("one", "forecast", {"venue_name": "One"}) == first
        assert call.call_count == 1
        with pytest.raises(BudgetExceeded):
            client.fetch("one", "live", {"venue_id": "ven_one"})
    # An interrupted request may have reached BestTime; do not retry it on resume.
    save(tmp_path / "requests/one.forecast.json", {"parameters": {"venue_name": "One"},
                                                 "reserved_credits": 2, "state": "pending"})
    with patch.object(client, "_request") as call:
        assert client.fetch("one", "forecast", {"venue_name": "One"})["state"] == "pending"
        call.assert_not_called()


def test_credentials_removed_from_payload_links_and_errors(tmp_path):
    client = BestTimeClient("pri_testSecret", "pub_testSecret", tmp_path)
    body = json.dumps({"status": "Error", "url": "https://example/?key=pri_testSecret",
                       "api_key_public": "pub_testSecret"}).encode()
    error = HTTPError("https://example/pri_testSecret", 403, "bad", {}, io.BytesIO(body))
    with patch("farol.besttime.urlopen", side_effect=error):
        result = client.fetch("test", "live", {"venue_id": "ven_test"})
    assert "testSecret" not in json.dumps(result)
    assert "testSecret" not in (tmp_path / "requests/test.live.json").read_text()
    with patch("farol.besttime.urlopen", side_effect=URLError("pri_testSecret")):
        assert "testSecret" not in json.dumps(client._request("GET", "/test"))
    assert sanitize({"key": "different-secret"}, ("different-secret",)) == {"key": "REDACTED"}


def test_access_denial_stops_additional_live_calls_and_html_escapes(tmp_path):
    client = BestTimeClient("private", "public", tmp_path, budget=6)
    venues = [{"id": key, "name": '<script>alert("x")</script>', "address": "100 Test St",
               "city": "Seattle", "area": "Test"} for key in ("one", "two")]
    def fake_fetch(key, kind, params):
        if kind == "live":
            return {"http_status": 403, "payload": {"status": "Error"}}
        return response([], venue_id=key, venue_name=venues[0]["name"],
                        venue_address="100 Test St Seattle", venue_timezone="America/Los_Angeles")
    with patch.object(client, "key_status", return_value={"valid": True, "active": True,
                      "credits_forecast": 100, "credits_query": 100, "retrieved_at": "test"}), \
            patch.object(client, "fetch", side_effect=fake_fetch) as fetch:
        report = run(client, venues)
    assert [call.args[1] for call in fetch.call_args_list] == ["forecast", "live", "forecast"]
    assert report["summary"]["live_coverage"] == 0
    assert "<script>" not in render_html(report)
    assert "&lt;script&gt;" in render_html(report)


def test_evening_refresh_reuses_weekly_data_and_preserves_baseline_age(tmp_path):
    client = BestTimeClient("private", "public", tmp_path, budget=1)
    requested = {"id": "venue", "name": "Tavern Law", "city": "Seattle",
                 "address": "1406 12th Ave", "area": "Capitol Hill"}
    forecast = normalize_forecast(response([{"day_info": {"day_int": 4}, "day_raw": [50] * 24}],
                                           venue_name="Tavern Law",
                                           venue_address="1406 12th Ave Seattle, WA 98122",
                                           venue_timezone="America/Los_Angeles"))
    previous = {"venues": [{"requested": requested, "forecast": forecast}]}
    with patch.object(client, "key_status", return_value={"valid": True, "active": True,
                      "credits_forecast": 82, "credits_query": 100, "retrieved_at": "evening"}), \
            patch.object(client, "fetch", return_value=response({
                "venue_live_busyness_available": True, "venue_live_busyness": 95,
                "venue_forecast_busyness_available": True, "venue_forecasted_busyness": 70,
            })) as fetch:
        report = run(client, [requested], previous)
    fetch.assert_called_once_with("venue", "live", {"venue_id": "ven_test"})
    assert report["venues"][0]["forecast"]["retrieved_at"] == "2026-09-18T15:00:00+00:00"
    assert report["venues"][0]["live"]["delta_percentage_points"] == 25
