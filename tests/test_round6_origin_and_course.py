"""Round 6 regression tests for origin/pickup-center alias resolution (R5-05) and Plan non-contradiction."""

from __future__ import annotations

from fastapi.testclient import TestClient

from farol.api import app
from farol.course import render_bound_action_plan
from farol.zones import canonical_zone, load_zones, zone_record


def test_r5_05_zones_resolve_home_and_pickup_centers() -> None:
    load_zones.cache_clear()
    assert canonical_zone("home") == "totem_lake"
    assert canonical_zone("example_public_origin") == "totem_lake"
    assert canonical_zone("Village at Totem Lake") == "totem_lake"
    assert canonical_zone("totem_lake_village") == "totem_lake"
    assert canonical_zone("Downtown Kirkland Waterfront") == "kirkland_waterfront"
    assert canonical_zone("Downtown Redmond / Town Center") == "redmond_downtown"
    assert zone_record("home") is not None
    assert zone_record("Village at Totem Lake") is not None


def test_r5_05_api_endpoints_accept_home_and_pickup_center_labels() -> None:
    load_zones.cache_clear()
    client = TestClient(app)
    for path in (
        "/api/here?at=home",
        "/api/ask/context?area=home",
        "/api/awareness?scope=nearby&area=home",
        "/api/here?at=Village%20at%20Totem%20Lake",
        "/api/ask/context?area=Village%20at%20Totem%20Lake",
        "/api/awareness?scope=nearby&area=Village%20at%20Totem%20Lake",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, f"Expected 200 for {path}, got {resp.status_code}: {resp.text}"


def test_plan_render_bound_action_plan_never_combines_move_with_hold_position() -> None:
    stops = [
        {
            "hour_index": 1,
            "window_label": "6:00 PM – 7:00 PM",
            "zone": "central_district",
            "zone_label": "Central District",
            "drive_minutes_from_prev": 17,
            "distance_miles_from_prev": 8.0,
            "navigation_available": False,
            "staging_spot": "Central District",
            "primary_trigger": "⏸ Insufficient live or historical evidence — hold position",
            "hot_venues": [],
            "events": [],
            "flight_arrivals": 0,
            "expected_net_per_hour": None,
            "sample_trips": 0,
        },
        {
            "hour_index": 2,
            "window_label": "7:00 PM – 8:00 PM",
            "zone": "seattle_core",
            "zone_label": "Seattle Core",
            "drive_minutes_from_prev": 10,
            "distance_miles_from_prev": 4.0,
            "navigation_available": False,
            "staging_spot": "Seattle Core",
            "primary_trigger": "🔥 Busy places: Pike Place (65%)",
            "hot_venues": ["Pike Place (65%)"],
            "events": [],
            "flight_arrivals": 0,
            "expected_net_per_hour": 32.0,
            "sample_trips": 8,
        },
    ]
    rendered = render_bound_action_plan(
        selection={"immediate_stop_id": "stop_0", "pivot_stop_id": "stop_1", "late_stop_id": "stop_1"},
        stops=stops,
        fa_total_planes=12,
        top_hotspots=[{"name": "Pike Place", "busyness": 65}],
        fa_forecast={"best_hour_label": "8:00 PM"},
        train_stations=[],
        origin_label="Bellevue Core",
    )
    assert rendered is not None
    immediate = rendered["immediate_move"]
    assert "Move from Bellevue Core to Central District" not in immediate
    assert "Hold in Bellevue Core" in immediate
