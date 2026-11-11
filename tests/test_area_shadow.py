import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from farol.area_shadow import area_brief, model_input, rank_areas, scheduled_open
from farol.besttime_filter import normalize_filter
from farol.neighborhood import FIELDS, profile

NOW = datetime(2026, 10, 27, 3, 48, tzinfo=UTC)
CENTER = SimpleNamespace(id="fixture", label="Fixture", latitude=47.67, longitude=-122.2)


def receipt(*, live=False, value=60, curve=None):
    return {
        "http_status": 200,
        "retrieved_at": NOW.isoformat(),
        "parameters": {"live" if live else "now": "true", "limit": 50},
        "payload": {
            "status": "OK",
            "window": {"time_local_index": 14},
            "venues": [
                {
                    "venue_id": "one",
                    "venue_name": "Fixture",
                    "venue_type": "BAR",
                    "venue_lat": 47.67,
                    "venue_lng": -122.2,
                    "day_raw": [value],
                    "day_raw_whole": curve if curve is not None else [60] * 24,
                    "day_info": {"day_int": 0},
                }
            ],
        },
    }


@pytest.mark.parametrize(
    "value,expected",
    [(0, 0), (130, 130), (None, None), (-1, None), (True, None), (float("nan"), None)],
)
def test_live_filter_shape_preserves_zero_and_rejects_bad_numbers(value, expected):
    r = receipt(live=True, value=value)
    v = normalize_filter(r, "raw.json")["venues"][0]
    assert v["live_percent"] == expected
    assert v["typical_now"] == 60
    assert v["open_status"] is None
    assert v["measurement_time"] is None
    assert v["provenance"]["typical"]["receipt"] == "raw.json"


def test_current_hour_forecast_is_never_live_and_provider_error_is_unavailable():
    r = receipt(value=99)
    assert normalize_filter(r, "raw")["venues"][0]["live_percent"] is None
    r["payload"]["status"] = "Error"
    assert normalize_filter(r, "raw")["state"] == "unavailable"
    assert not normalize_filter(r, "raw")["venues"]


def test_missing_live_does_not_erase_zero_and_stale_reading_does_not_dominate():
    live = receipt(live=True, value=0)
    typical = receipt()
    a = area_brief(CENTER, [("l", live), ("t", typical)], NOW, {"minutes": 2})
    assert len(a["venues"]) == 1
    assert a["venues"][0]["live_percent"] == 0
    assert rank_areas([a], enabled=True)[0]["activity_points"] == 0
    a = area_brief(CENTER, [("l", live), ("t", typical)], NOW + timedelta(hours=2), {"minutes": 2})
    assert a["venues"][0]["live_percent"] is None
    assert rank_areas([a], enabled=True)[0]["activity_points"] > 0


def test_out_of_radius_and_duplicate_places_cannot_multiply_support():
    r = receipt(live=True)
    outside = copy.deepcopy(r["payload"]["venues"][0])
    outside.update(venue_id="far", venue_lat=48.0)
    r["payload"]["venues"] += [outside, copy.deepcopy(r["payload"]["venues"][0])]
    a = area_brief(CENTER, [("l", r)], NOW, {"minutes": 2})
    assert len(a["venues"]) == 1
    assert len(rank_areas([a], enabled=True)[0]["support"]) == 1


def test_explicit_gate_income_independence_and_order_invariance():
    a = area_brief(CENTER, [("l", receipt(live=True))], NOW, {"minutes": 2})
    b = copy.deepcopy(a)
    b["id"] = "other"
    b["route"]["minutes"] = 10
    with pytest.raises(ValueError):
        rank_areas([a, b])
    before = rank_areas([a, b], enabled=True, structural=True)
    a["neighborhood"] = {"median_household_income": 9000000}
    assert rank_areas([b, a], enabled=True, structural=True) == before
    data = model_input([b, a])
    assert "score" not in str(data)
    assert [x["id"] for x in data["areas"]] == ["fixture", "other"]


def test_weekly_schedule_overnight_margin_and_unknown():
    venue = {"day_int": 0, "opening_periods": {"24h": [{"opens": 18, "closes": 2}]}}
    assert scheduled_open(venue, NOW) is True
    assert scheduled_open(venue, datetime(2026, 10, 27, 8, 55, tzinfo=UTC)) is False
    assert scheduled_open({}, NOW) is None
    venue["opening_periods"]["24h"][0]["opens"] = 0
    assert scheduled_open(venue, NOW) is None  # ambiguous 6AM-based day, not invented closure


def census_fixture():
    geo = {
        "http_status": 200,
        "payload": {
            "features": [
                {"attributes": {"GEOID": "530330001001", "AREALAND": 2589988.110336}},
                {"attributes": {"GEOID": "530330001002", "AREALAND": 2589988.110336}},
            ]
        },
    }
    fields = [code + suffix for code in FIELDS.values() for suffix in ("E", "M")]
    header = ["state", "county", "tract", "block group", *fields]
    rows = [
        ["53", "033", "000100", str(i), *["100" if f.endswith("E") else "10" for f in fields]]
        for i in (1, 2)
    ]
    return geo, {"http_status": 200, "payload": [header, *rows]}


def test_structural_estimates_have_geography_moe_and_per_field_provenance():
    geo, acs = census_fixture()
    p = profile(geo, acs, geography_id="geo", acs_id="acs")
    assert p["state"] == "available"
    assert p["metrics"]["population_per_land_sq_mile"]["estimate"] == 100
    assert p["metrics"]["population"]["moe90_approx"] == pytest.approx(200**0.5)
    assert "median_household_income" not in p["metrics"]
    assert (
        p["block_groups"][0]["fields"]["median_household_income"]["provenance"]["estimate_field"]
        == "B19013_001E"
    )


@pytest.mark.parametrize("bad", ["-666666666", "null", None])
def test_unavailable_census_values_never_become_population_zero(bad):
    geo, acs = census_fixture()
    acs["payload"][1][4] = bad
    p = profile(geo, acs, geography_id="geo", acs_id="acs")
    assert p["state"] == "partial"
    assert p["metrics"]["population"]["estimate"] is None
    assert p["metrics"]["population_per_land_sq_mile"]["estimate"] is None


def test_truncated_geography_and_http200_html_do_not_create_estimates():
    geo, acs = census_fixture()
    geo["payload"]["exceededTransferLimit"] = True
    assert profile(geo, acs, geography_id="g", acs_id="a")["state"] == "unavailable"
    assert (
        profile({}, {"http_status": 200, "payload": None}, geography_id="g", acs_id="a")["metrics"]
        == {}
    )


def test_topcoded_income_is_not_an_exact_dollar_value():
    geo, acs = census_fixture()
    col = acs["payload"][0].index("B19013_001E")
    acs["payload"][1][col] = "250001"
    value = profile(geo, acs, geography_id="g", acs_id="a")["block_groups"][0]["fields"][
        "median_household_income"
    ]
    assert value["estimate"] is None
    assert value["provider_estimate_code"] == "250001"


def test_lone_park_cannot_win_with_100_percent_and_travel_can_change_winner():
    r = receipt(live=True, value=100)
    r["payload"]["venues"][0]["venue_type"] = "PARK"
    park = area_brief(CENTER, [("l", r)], NOW, {"minutes": 1})
    dining = area_brief(CENTER, [("l", receipt(live=True, value=25))], NOW, {"minutes": 10})
    dining["id"] = "dining"
    assert rank_areas([park, dining], enabled=True)[0]["id"] == "dining"
    nearer = copy.deepcopy(dining)
    nearer.update(id="nearer", route={"minutes": 1})
    assert rank_areas([nearer, dining], enabled=True)[0]["id"] == "nearer"
    nearer["route"]["minutes"] = 20
    assert rank_areas([nearer, dining], enabled=True)[0]["id"] == "dining"


def test_closing_before_arrival_excludes_support_and_structural_bonus_is_bounded():
    r = receipt(live=True)
    r["payload"]["venues"][0]["day_info"]["venue_open_close_v2"] = {
        "24h": [{"opens": 10, "closes": 21}]
    }
    a = area_brief(CENTER, [("l", r)], NOW, {"minutes": 15})
    assert a["venues"][0]["scheduled_open_at_arrival"] is False
    a["neighborhood"] = {
        "state": "available",
        "metrics": {"population_per_land_sq_mile": {"estimate": 1000000, "moe90_approx": 1}},
    }
    score = rank_areas([a], enabled=True, structural=True)[0]
    assert score["activity_points"] == 0
    assert score["structural_points"] <= 4


def test_production_discovery_accepts_filtered_curve_without_claiming_closure(monkeypatch):
    import io
    import json

    from farol import besttime_live
    from farol.zones import load_zones

    r = receipt(curve=[0] * 24)
    r["payload"]["venues"][0]["day_raw_whole"][15] = 60
    r["payload"]["venues"][0]["venue_address"] = "Fixture public address"
    requests = []

    def fake_open(req, **kwargs):
        requests.append(req.full_url)
        return io.BytesIO(json.dumps(r["payload"]).encode())

    monkeypatch.setattr(besttime_live, "urlopen", fake_open)
    output = {}
    besttime_live._merge_radar_hotspots(
        by_id=output,
        lat=47.67,
        lon=-122.2,
        radius_m=1000,
        private_key="test",
        public_key="test",
        now=NOW,
        registry=load_zones(),
    )
    assert "now=true" in requests[0] and "busy_min" not in requests[0]
    entry = next(iter(output.values()))
    assert entry["live"]["open_status"] is None
    assert entry["live"]["available"] is False
    assert all(h["closed"] is None for h in entry["forecast"]["days"][0]["hours"])
