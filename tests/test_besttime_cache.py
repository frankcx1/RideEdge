"""Regression coverage for partial scans, retained provenance and no paid calls."""
import copy
import io
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from farol import besttime_cache, besttime_live, radar
from farol.zones import load_zones

FRIDAY = datetime(2026, 11, 6, 20, tzinfo=UTC)  # Friday noon Pacific


def scan(by_id, at, value=75, provider_id="cache-test"):
    record = {"venue_id": provider_id, "venue_name": "Fixture restaurant", "venue_address": "100 Test St",
              "venue_type": "BAR", "venue_lat": 47.6155, "venue_lng": -122.2015, "day_raw": [value]*24}
    with patch("farol.besttime_control.reserve_request"), patch.object(besttime_live, "urlopen",
            return_value=io.BytesIO(json.dumps({"status": "OK", "venues": [record]}).encode())):
        besttime_live._merge_radar_hotspots(by_id=by_id, now=at, lat=47.6155, lon=-122.2015,
            radius_m=1000, private_key="fixture", public_key="fixture", registry=load_zones())
    return by_id["radar_"+provider_id[:28]]


def test_actual_scans_retain_other_weekdays_without_renewing_timestamps():
    rows = {}
    original = copy.deepcopy(scan(rows, FRIDAY))
    saturday = FRIDAY+timedelta(days=1)
    combined = scan(rows, saturday, 90)
    forecast = combined["forecast"]
    fri = besttime_cache.hour_record(forecast, FRIDAY)
    sat = besttime_cache.hour_record(forecast, saturday)
    assert (fri["typical_busyness"], fri["retrieved_at"]) == (75, FRIDAY.isoformat())
    assert (sat["typical_busyness"], sat["retrieved_at"]) == (90, saturday.isoformat())
    assert forecast["retrieved_at"] == FRIDAY.isoformat()  # Conservative legacy compatibility
    assert original["forecast"] in forecast["retained_forecasts"]
    assert fri["provenance"]["provider_venue_id"] == "cache-test"
    assert len(fri["provenance"]["source_record_hash"]) == 64
    # Midnight belongs to the following calendar day, not the 06:00 provider day.
    assert besttime_cache.hour_record(forecast, saturday.replace(hour=10))["retrieved_at"] == FRIDAY.isoformat()
    assert besttime_cache.hour_record(forecast, FRIDAY+timedelta(days=3)) is None


def test_new_partial_scan_does_not_resurrect_expired_hours_or_mutate_input():
    rows = {}
    old = copy.deepcopy(scan(rows, FRIDAY))
    newest = scan(rows, FRIDAY+timedelta(days=15), 85)
    forecast = newest["forecast"]
    now = FRIDAY+timedelta(days=15)
    assert besttime_live._typical_for_hour(forecast, FRIDAY, now=now) is None
    assert besttime_live._typical_for_hour(forecast, now, now=now) == 85
    assert old["forecast"]["retrieved_at"] == FRIDAY.isoformat()
    # The newer valid hour is usable even though the compatibility stamp is old.
    view = radar.build(radar.origin("Bellevue"), {}, {"venues": [newest]}, now=now)
    place = next(p for p in view["nearby"] if p["id"] == "venue:radar_cache-test")
    assert place["busyness"] == 85
    assert place["evidence"][0]["fetched_at"] == now.isoformat()
    assert place["evidence"][0]["forecast_provenance"]["provider_venue_id"] == "cache-test"


def test_full_provider_id_and_identity_must_match_before_merging():
    prefix = "a"*28
    old = scan({}, FRIDAY, provider_id=prefix+"first")
    new = scan({}, FRIDAY+timedelta(days=1), provider_id=prefix+"second")
    assert besttime_cache.merge_entries(old, new) == new
    new = copy.deepcopy(old)
    new["requested"]["address"] = "Wrong branch"
    assert besttime_cache.merge_entries(old, new) == new


def test_late_publication_preserves_newer_hour_but_adds_missing_coverage():
    friday = scan({}, FRIDAY, 60)
    saturday = scan({}, FRIDAY+timedelta(days=1), 80)
    combined = besttime_cache.merge_entries(saturday, friday)
    assert besttime_cache.hour_record(combined["forecast"], FRIDAY+timedelta(days=1))["typical_busyness"] == 80
    newer_friday = scan({}, FRIDAY+timedelta(hours=1), 40)
    merged = besttime_cache.merge_entries(newer_friday, friday)
    assert besttime_cache.hour_record(merged["forecast"], FRIDAY)["typical_busyness"] == 40


def test_closure_unknown_and_expiry_are_distinct_in_coverage_and_ranking():
    record = scan({}, FRIDAY)
    closed = copy.deepcopy(record)
    hour = next(h for h in closed["forecast"]["days"][0]["hours"] if h["hour"] == 12)
    hour["closed"] = True
    view = radar.build(radar.origin("Bellevue"), {}, {"venues": [closed]}, now=FRIDAY)
    assert all(p["id"] != "venue:radar_cache-test" for p in view["now"])
    assert any(e["code"] == "closed_venue" for e in view["excluded"])
    assert besttime_cache.coverage([closed], FRIDAY, FRIDAY)["closed_hour"] == 1
    assert besttime_cache.coverage([record], FRIDAY, FRIDAY)["usable_pattern"] == 1
    assert besttime_cache.coverage([record], FRIDAY+timedelta(days=1), FRIDAY)["missing_hour"] == 1
    assert besttime_cache.coverage([record], FRIDAY, FRIDAY+timedelta(days=15))["expired_hour"] == 1


def test_invalid_timestamp_and_value_never_become_usable_pattern():
    record = scan({}, FRIDAY)
    record["forecast"]["retrieved_at"] = "invalid"
    assert besttime_cache.usable_hour(record["forecast"], FRIDAY, FRIDAY) is None
    record["forecast"]["retrieved_at"] = (FRIDAY+timedelta(hours=1)).isoformat()
    assert besttime_cache.usable_hour(record["forecast"], FRIDAY, FRIDAY) is None


def test_paused_collection_does_not_make_provider_calls():
    with patch.object(besttime_live, "urlopen", side_effect=AssertionError("paid request")):
        result = besttime_live.poll_besttime_venues()
    assert result["mode"] == "paused" and result["http_requests_made"] == 0
