import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from farol.api import app
from farol.awareness import PACIFIC, build_view, venue_activity, write_snapshot
from farol.besttime import normalize_forecast
from farol.signals import Signal

NOW = datetime(2026, 9, 18, 20, tzinfo=PACIFIC)


def signal(**changes):
    row = Signal("show", "event_exit", "capitol_hill", (NOW + timedelta(hours=1)).isoformat(),
                 (NOW + timedelta(hours=2)).isoformat(), 8000, "scheduled", "test:events",
                 (NOW - timedelta(minutes=10)).isoformat(),
                 (NOW + timedelta(hours=2)).isoformat(), .7,
                 {"title": "Theater concert", "kickoff": (NOW - timedelta(hours=1)).isoformat(),
                  "exit_timing_basis": "assumed show duration"})
    return replace(row, **changes)


def snapshot(*signals, feeds=()):
    return {"collected_at": NOW.isoformat(), "window_end": (NOW + timedelta(hours=6)).isoformat(),
            "signals": [asdict(row) for row in signals], "feeds": list(feeds)}


def besttime_report(*, retrieved=None, available=True, value=120, matched=True):
    receipt = {"http_status": 200, "retrieved_at": (NOW - timedelta(hours=12)).isoformat(),
               "payload": {"status": "OK", "venue_info": {}, "analysis": [
                   {"day_info": {"day_int": day}, "day_raw": [0] * 19 + [70] + [0] * 4}
                   for day in range(7)
               ]}}
    return {"venues": [{"requested": {"id": "tavern_law", "name": "Tavern Law",
                                       "area": "Capitol Hill"}, "identity_matched": matched,
                        "forecast": normalize_forecast(receipt),
                        "live": {"available": available, "busyness": value,
                                 "typical_this_hour": 100, "delta_percentage_points": value - 100,
                                 "retrieved_at": retrieved or (NOW - timedelta(minutes=15)).isoformat()}}]}


def test_events_visible_without_anchors_and_underway_before_exit():
    with patch("farol.signals.load_anchors", side_effect=AssertionError("anchors not required")):
        view = build_view(snapshot(signal()), now=NOW, period="now")
    event = view["observations"][0]
    assert event["state"] == "scheduled underway"
    assert event["window_starts_at"] == (NOW + timedelta(hours=1)).isoformat()
    assert "estimated" in event["timing_label"].lower()
    assert "assumed show duration" in event["detail"]
    assert "navigation" not in event


def test_live_venue_note_agrees_with_available_reading_and_its_age():
    recent = build_view(None, now=NOW, besttime=besttime_report())["venue_activity"][0]
    assert recent["live_recent"] and "unavailable" not in recent["note"].lower()
    old = build_view(None, now=NOW + timedelta(hours=2),
                     besttime=besttime_report())["venue_activity"][0]
    assert old["live_value"] == 120 and not old["live_recent"]
    assert "old" in old["note"].lower()


def test_nearby_filters_areas_but_preserves_metro_weather():
    rain = signal(id="rain", kind="precipitation", zone="all", details={"title": "Rain forecast"})
    view = build_view(snapshot(signal(), rain), now=NOW, scope="nearby", area="bellevue", radius=0)
    assert [row["id"] for row in view["observations"]] == ["rain"]
    assert view["area"] == "bellevue_core"
    assert "straight-line" in view["distance_note"]


def test_same_road_alert_is_one_observation_with_several_areas():
    road = signal(kind="highway_alert", id="road-bellevue", zone="bellevue_core",
                  source="wsdot:test", details={"title": "I-405 closure", "headline": "Ramp closure"})
    other = replace(road, id="road-kirkland", zone="kirkland_waterfront")
    view = build_view(snapshot(road, other), now=NOW)
    assert len(view["observations"]) == 1
    assert set(view["observations"][0]["zones"]) == {"bellevue_core", "kirkland_waterfront"}
    assert next(row for row in view["layers"] if row["id"] == "access")["count"] == 1


def test_published_road_advisory_does_not_claim_future_closure_is_active_now():
    road = signal(kind="highway_alert", details={"title": "Construction on I-405",
                  "description": "All lanes close at 11:30 p.m. tonight."},
                  starts_at=NOW.isoformat())
    view = build_view(snapshot(road), now=NOW, period="now")
    row = view["observations"][0]
    assert row["state"] == "road advisory"
    assert row["timing_label"] == "Restriction times unverified"
    assert "11:30 p.m." in row["detail"]


def test_topics_and_half_open_time_windows_exclude_ended_and_boundary_starts():
    ended = signal(id="ended", ends_at=NOW.isoformat(), starts_at=(NOW - timedelta(hours=1)).isoformat())
    later = signal(id="later", details={"title": "Later exit"})
    view = build_view(snapshot(ended, later), now=NOW, period="next")
    assert not view["observations"]
    assert build_view(snapshot(later), now=NOW, period="later")["observations"]
    assert not build_view(snapshot(later), now=NOW, layer="weather")["observations"]


def test_six_hour_window_is_elapsed_time_across_daylight_saving_change():
    fall_back = datetime(2026, 11, 1, 0, tzinfo=PACIFIC)
    begins = (fall_back.astimezone(UTC) + timedelta(hours=6, minutes=30)).astimezone(PACIFIC)
    too_late = signal(starts_at=begins.isoformat(), ends_at=(begins + timedelta(hours=1)).isoformat(),
                      details={"title": "Outside six elapsed hours"})
    assert not build_view(snapshot(too_late), now=fall_back)["observations"]


def test_stale_traffic_and_failed_refresh_are_not_presented_as_current():
    road = signal(kind="travel_delay", basis="live", fetched_at=(NOW - timedelta(hours=2)).isoformat())
    view = build_view(snapshot(road), now=NOW)
    assert view["observations"][0]["freshness"] == "old source data"
    current = replace(road, fetched_at=NOW.isoformat())
    view = build_view(snapshot(current, feeds=[{"source": current.source, "mode": "stale_cache"}]), now=NOW)
    assert view["observations"][0]["freshness"] == "source refresh failed"


@pytest.mark.parametrize("fetched", ["", "bad-time", "2026-09-18T21:00:00-07:00"])
def test_missing_invalid_and_future_source_times_stay_unknown(fetched):
    view = build_view(snapshot(signal(fetched_at=fetched)), now=NOW)
    assert view["observations"][0]["freshness"] == "time unknown"


def test_google_hours_retain_each_venues_actual_source_age(monkeypatch):
    from farol.adapters import places

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test")
    catalog = [{"id": key, "place_id": key, "name": key, "zone": "bellevue_core"}
               for key in ("old", "new")]
    payload = {"regularOpeningHours": {"periods": [
        {"open": {"day": 5, "hour": 12}, "close": {"day": 6, "hour": 2}},
    ]}}
    def details(key):
        return payload, "cache", (NOW - timedelta(hours=48) if key == "old" else NOW).isoformat()
    with patch.object(places, "load_venues", return_value=catalog), \
            patch.object(places, "_details", side_effect=details):
        signals, _ = places.fetch(NOW, NOW + timedelta(hours=7))
    view = build_view(snapshot(*signals), now=NOW)
    rows = {row["id"].split("-")[1]: row for row in view["observations"]}
    assert rows["old"]["freshness"] == "old source data"
    assert rows["new"]["freshness"] == "recently checked"


def test_old_snapshot_and_missing_snapshot_do_not_claim_no_activity():
    saved = snapshot()
    saved["collected_at"] = (NOW - timedelta(hours=3)).isoformat()
    view = build_view(saved, now=NOW)
    assert view["snapshot"]["state"] == "old"
    assert "Coverage may be incomplete" in view["empty_note"]
    assert build_view(None, now=NOW)["snapshot"]["state"] == "missing"


def test_overnight_besttime_profile_and_old_live_reading():
    early = NOW + timedelta(hours=5)
    report = besttime_report(retrieved=(NOW - timedelta(hours=12)).isoformat())
    rows = venue_activity(report, early, early, early + timedelta(hours=1))
    assert rows[0]["typical_now"] == 70
    assert rows[0]["window_peak"]["value"] == 70
    assert rows[0]["live_value"] == 120
    assert not rows[0]["live_recent"]


@pytest.mark.parametrize("available,value,matched,expected", [
    (False, 0, True, 0), (True, 0, True, 1), (True, 120, True, 1), (True, 90, False, 0),
])
def test_live_coverage_counts_availability_instead_of_truthiness(available, value, matched, expected):
    view = build_view(snapshot(), now=NOW,
                      besttime=besttime_report(available=available, value=value, matched=matched))
    assert view["busyness_coverage"]["sampled"] == 1
    assert view["busyness_coverage"]["recent_live"] == expected
    assert view["busyness_coverage"]["above_typical"] == (1 if expected and value > 100 else 0)


def test_corrupt_besttime_report_does_not_hide_event_feeds():
    view = build_view(snapshot(signal()), now=NOW, besttime={"venues": [{"bad": "schema"}]})
    assert len(view["observations"]) == 1
    assert view["busyness_coverage"]["sampled"] == 0


def test_snapshot_redacts_keys_and_never_requires_a_model_or_navigation(tmp_path, monkeypatch):
    monkeypatch.setenv("FAROL_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("TEST_API_KEY", "sensitive_test_value")
    row = signal(details={"title": "Event", "url": "https://test?key=sensitive_test_value"})
    write_snapshot([row], [{"source": "test", "detail": "sensitive_test_value"}], NOW,
                   NOW + timedelta(hours=6))
    text = (tmp_path / "awareness_snapshot.json").read_text()
    assert "sensitive_test_value" not in text
    stored = json.loads(text)
    assert len(stored["signals"]) == 1


def test_api_reads_saved_sources_without_network_or_models(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_FEEDS", "0")
    monkeypatch.setenv("FAROL_CACHE_DIR", str(tmp_path))
    (tmp_path / "awareness_snapshot.json").write_text(json.dumps(snapshot(signal())))
    with patch("farol.adapters.gather_signals", side_effect=AssertionError("no collection")), \
            patch("farol.besttime.BestTimeClient._request", side_effect=AssertionError("no spend")), \
            patch("farol.awareness.saved_besttime", return_value=None):
        response = TestClient(app).get("/api/awareness")
    assert response.status_code == 200
    assert response.json()["demo"] is False


def test_api_demo_page_assets_and_location_validation(monkeypatch):
    monkeypatch.setenv("MOCK_FEEDS", "1")
    client = TestClient(app)
    assert client.get("/awareness").status_code == 200
    assert client.get("/awareness.js").status_code == 200
    assert client.get("/api/awareness").json()["demo"] is True
    assert client.get("/api/health").json()["awareness_available"] is True
    for query in ("scope=bad", "period=bad", "layer=bad", "area=unknown", "radius=nan"):
        assert client.get("/api/awareness?" + query).status_code == 400
    assert client.post("/api/awareness", json={"latitude": 0, "longitude": 0}).status_code == 400
    result = client.post("/api/awareness", json={"latitude": 47.616, "longitude": -122.201})
    assert result.status_code == 200
    assert result.json()["scope"] == "nearby"
    assert "latitude" not in result.text
    assert "longitude" not in result.text


def test_device_location_labels_seattle_instead_of_default_kirkland(monkeypatch):
    monkeypatch.setenv("MOCK_FEEDS", "1")
    client = TestClient(app)
    result = client.post("/api/awareness?area=totem_lake", json={
        "latitude": 47.6062, "longitude": -122.3321})
    assert result.status_code == 200
    view = result.json()
    assert view["area"] == "seattle_core"
    assert view["location_label"] == "Seattle core"
    assert view["location_source"] == "device"
    assert result.headers["cache-control"] == "no-store"
    assert "47.6062" not in result.text and "-122.3321" not in result.text
    manual = client.get("/api/awareness?scope=nearby&area=totem_lake").json()
    assert manual["area"] == "totem_lake"
    assert manual["location_source"] == "selected_area"


def test_gps_radius_uses_actual_pin_not_the_nearest_area_center():
    # Radius zero at a pin away from the zone center must not force-include it.
    row = signal(zone="seattle_core")
    view = build_view(snapshot(row), now=NOW, scope="nearby", radius=0,
                      latitude=47.6062, longitude=-122.3321)
    assert view["area"] == "seattle_core"
    assert not view["observations"]
