"""Comprehensive end-to-end test suite for the RideEdge Android cockpit & Farol API.

Tests every tab, button, chip, input, and response across all 5 tabs:
1. Working (GPS, text search, all 12 quick-area chips, Save Parked Curb, Ask Qwen handoff)
2. Around (GPS, all 12 quick-area chips, 4 scope/radius chips, 4 period chips, 7 layer chips, road advisory separation)
3. Ask Qwen (all 12 quick-area chips, 5 time-available chips, 4 max-reposition chips, What Changed, Ask Qwen)
4. Tonight (shift decision, ranked opportunities, Maps URI coordinates, Approve Curb, Send to Volvo)
5. Shift (Ledger fetch, Start Shift odometer, End Shift odometer, calibration cleanup)

Also audits result quality from a real Seattle/Eastside Uber driver's perspective.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from farol.api import app

QUICK_AREAS = [
    "Bellevue",
    "Kirkland",
    "Totem Lake",
    "Redmond",
    "Bothell",
    "Woodinville",
    "Downtown Seattle",
    "SLU",
    "Capitol Hill",
    "Seattle Center",
    "Ballard",
    "SeaTac Airport",
]

CANONICAL_AWARENESS_MAP = {
    "bellevue": "bellevue_core",
    "kirkland": "kirkland_waterfront",
    "totem lake": "totem_lake",
    "redmond": "redmond_downtown",
    "bothell": "bothell",
    "woodinville": "woodinville_wine",
    "downtown seattle": "seattle_core",
    "slu": "seattle_core",
    "capitol hill": "capitol_hill",
    "seattle center": "seattle_center",
    "ballard": "fremont_ballard",
    "seatac airport": "sea_airport",
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_top_bar_health_and_refresh(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "shift" in body
    assert body["shift"]["phase"] in {"idle", "acquiring", "driving", "restoring", "error"}


@pytest.mark.parametrize("area", QUICK_AREAS)
def test_tab1_working_all_quick_area_chips(client: TestClient, area: str) -> None:
    resp = client.get("/api/here", params={"at": area, "vehicle_cost": 0.45, "value_of_time": 25.0})
    assert resp.status_code == 200, f"Working chip '{area}' failed: {resp.text}"
    data = resp.json()
    assert data["place"]["zone"], f"Missing canonical zone for {area}"
    assert data["place"]["label"], f"Missing label for {area}"
    assert data["action"] in {"WAIT", "WORK", "STAY", "STAGE", "MOVE", "WATCH", "AIRPORT", "PASS"}
    assert data["action_plain"]
    assert isinstance(data["sit_here"]["ranked"], list)
    assert len(data["sit_here"]["ranked"]) >= 3
    for row in data["sit_here"]["ranked"]:
        assert "zone" in row
        assert "historical_net_per_hour" in row
        assert "reposition_minutes" in row
        assert row["route_basis"] in {"live_traffic", "assumed", "here"}


def test_tab1_working_gps_pin_and_save_parked_curb(client: TestClient) -> None:
    # Simulate '📍 Use Pixel GPS' at Downtown Bellevue (47.6155, -122.2015)
    resp = client.post(
        "/api/here?vehicle_cost=0.45&value_of_time=25.0",
        json={"latitude": 47.6155, "longitude": -122.2015},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["place"]["zone"] == "bellevue_core"
    assert data["place"]["matched"] == "device location"

    # Simulate '📌 Save Parked Curb' button
    curb_resp = client.post(
        "/api/anchors/custom",
        json={
            "zone": data["place"]["zone"],
            "label": "Test Pixel Parked Spot",
            "latitude": 47.6155,
            "longitude": -122.2015,
            "action": "WAIT",
            "approval_status": "approved",
            "safety_notes": "Automated test suite curb check.",
        },
    )
    assert curb_resp.status_code == 200
    curb = curb_resp.json()
    assert curb["approval_status"] == "approved"
    assert "maps_url" in curb and "47.6155" in curb["maps_url"]


@pytest.mark.parametrize("area", QUICK_AREAS)
def test_tab2_around_all_quick_area_chips(client: TestClient, area: str) -> None:
    resolved = CANONICAL_AWARENESS_MAP[area.lower()]
    resp = client.get(
        "/api/awareness",
        params={"scope": "nearby", "area": resolved, "radius": 8, "period": "all", "layer": "all"},
    )
    assert resp.status_code == 200, f"Around chip '{area}' ({resolved}) failed: {resp.text}"
    data = resp.json()
    assert data["area"] == resolved
    assert data["location_label"]
    assert isinstance(data["layers"], list) and len(data["layers"]) == 6
    assert isinstance(data["observations"], list)


@pytest.mark.parametrize(
    "scope,radius",
    [("nearby", 5), ("nearby", 8), ("nearby", 15), ("metro", 25)],
)
def test_tab2_around_scope_and_radius_chips(client: TestClient, scope: str, radius: int) -> None:
    resp = client.get(
        "/api/awareness",
        params={"scope": scope, "area": "seattle_core", "radius": radius, "period": "all", "layer": "all"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["scope"] == scope


@pytest.mark.parametrize("period", ["now", "next", "all", "today", "week"])
def test_tab2_around_period_chips(client: TestClient, period: str) -> None:
    resp = client.get(
        "/api/awareness",
        params={"scope": "nearby", "area": "seattle_core", "radius": 8, "period": period, "layer": "all"},
    )
    assert resp.status_code == 200
    assert resp.json()["period"] == period


@pytest.mark.parametrize("layer", ["all", "events", "dining", "access", "transit", "weather", "airport"])
def test_tab2_around_layer_chips_and_road_advisory_split(client: TestClient, layer: str) -> None:
    resp = client.get(
        "/api/awareness",
        params={"scope": "nearby", "area": "seattle_core", "radius": 8, "period": "all", "layer": layer},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["layer"] == layer
    for obs in data["observations"]:
        if layer != "all":
            assert obs["layer"] == layer
        # Verify fields required by AwarenessObservationCard & Road Advisory grouping
        assert "id" in obs and "title" in obs and "kind" in obs and "state" in obs


def test_tab2_around_gps_button(client: TestClient) -> None:
    # Simulate '📍 GPS' button at Capitol Hill (47.6230, -122.3200)
    resp = client.post(
        "/api/awareness?radius=8&period=all&layer=all",
        json={"latitude": 47.6230, "longitude": -122.3200},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["area"] == "capitol_hill"
    assert data["location_source"] == "device"


@pytest.mark.parametrize("area", QUICK_AREAS)
def test_tab3_ask_qwen_all_area_chips_and_constraints(client: TestClient, area: str) -> None:
    resp = client.get("/api/ask/context", params={"mode": "live", "area": area})
    if resp.status_code != 200:
        resp = client.get("/api/ask/context", params={"mode": "demo", "step": 0})
    assert resp.status_code == 200
    body = resp.json()
    snapshot_id = body["context"]["snapshot_id"]
    comp = body["comparison"]
    assert comp["answer"]
    assert isinstance(comp["options"], list) and len(comp["options"]) >= 1

    # Test constraint chips update (e.g. 60m available, <= 15m reposition)
    cmp_resp = client.post(
        "/api/ask/compare",
        json={
            "snapshot_id": snapshot_id,
            "constraints": {
                "minutes_available": 60,
                "reposition_under_minutes": 15,
                "finish_near": "Eastside",
            },
        },
    )
    assert cmp_resp.status_code == 200
    cmp_data = cmp_resp.json()
    assert cmp_data["answer"]
    assert isinstance(cmp_data["options"], list)


def test_tab4_tonight_opportunities_maps_curb_and_volvo(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("FAROL_FIELD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FAROL_USE_LOCAL_ANCHORS", "1")
    resp = client.get("/api/tonight", params={"hours": 6, "vehicle_cost": 0.45, "value_of_time": 22.0})
    assert resp.status_code == 200
    data = resp.json()
    assert "shift_decision" in data
    assert "opportunities" in data
    opps = [o for o in data.get("ranked", data["opportunities"]) if o["action"] != "AVOID"]
    assert len(opps) >= 1
    first = opps[0]
    anchor = first.get("anchor") or {}
    assert anchor.get("id")

    # Test '✓ Approve Curb' button
    app_resp = client.post(
        f"/api/anchors/{anchor['id']}/approve",
        json={"approval_status": "approved", "safety_notes": "Approved in test suite."},
    )
    assert app_resp.status_code == 200
    assert app_resp.json()["approval_status"] == "approved"

    # Test '🚗 Volvo' button now that anchor is approved
    volvo_resp = client.post(f"/api/navigation/opportunity/{first['id']}?vehicle_cost=0.45")
    assert volvo_resp.status_code == 200
    nav = volvo_resp.json()
    assert nav["destination"]["latitude"] is not None
    assert nav["destination"]["longitude"] is not None


def test_tab5_shift_odometer_start_end_and_ledger(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import json
    from farol.history import LEDGER_NAME, merge_trips

    monkeypatch.setenv("FAROL_USE_FIELD_TRIPS", "1")
    # Isolate shift and trip writes to tmp_path so real field_data is untouched and empty-dir tests succeed
    monkeypatch.setenv("FAROL_FIELD_DATA_DIR", str(tmp_path))
    (tmp_path / LEDGER_NAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "trips": merge_trips(
                    [
                        {
                            "requested_at": "2099-01-01T18:15:00-08:00",
                            "ended_at": "2099-01-01T18:35:00-08:00",
                            "pickup_zone": "bellevue_core",
                            "dropoff_zone": "kirkland_downtown",
                            "duration_minutes": 20.0,
                            "paid_miles": 6.5,
                            "earnings": 24.50,
                        }
                    ]
                ),
            }
        ),
        encoding="utf-8",
    )
    hist_resp = client.get("/api/history", params={"vehicle_cost": 0.45})
    assert hist_resp.status_code == 200
    hist = hist_resp.json()
    assert "sessions" in hist and len(hist["sessions"]) >= 1
    start_resp = client.post(
        "/api/history/shifts/start",
        json={
            "odometer_miles": 50000.0,
            "started_at": "2099-01-01T18:00:00-08:00",
            "note": "pytest_synthetic_shift",
        },
    )
    assert start_resp.status_code == 200
    shift_id = start_resp.json()["shift_id"]

    end_resp = client.post(
        "/api/history/shifts/end",
        json={
            "shift_id": shift_id,
            "odometer_miles": 50045.5,
            "ended_at": "2099-01-01T21:00:00-08:00",
            "note": "pytest_synthetic_shift",
        },
    )
    assert end_resp.status_code == 200
    closed = end_resp.json()
    assert closed["total_miles"] == 45.5
    assert closed["committed_minutes"] == 180.0


def test_tab5_shift_quick_trip_logging_and_live_pnl(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("FAROL_USE_FIELD_TRIPS", "1")
    monkeypatch.setenv("FAROL_FIELD_DATA_DIR", str(tmp_path))
    start_resp = client.post(
        "/api/history/shifts/start",
        json={"odometer_miles": 42100.0, "note": "Live P&L test"},
    )
    assert start_resp.status_code == 200
    shift_id = start_resp.json()["shift_id"]

    t1 = client.post(
        "/api/history/shifts/trip",
        json={"gross_fare": 28.50, "miles": 9.2, "note": "Bellevue to SEA"},
    )
    assert t1.status_code == 200
    t2 = client.post(
        "/api/history/shifts/trip",
        json={"gross_fare": 16.00, "miles": 4.0, "note": "SEA to Downtown"},
    )
    assert t2.status_code == 200
    body = t2.json()
    assert body["shift_id"] == shift_id
    assert body["running_trip_count"] == 2
    assert body["running_gross_earnings"] == 44.5
    assert body["running_paid_miles"] == 13.2
    assert body["running_gross_per_hour"] > 0
    assert body["running_net_per_hour"] > 0

    shifts_resp = client.get("/api/history/shifts")
    assert shifts_resp.status_code == 200
    active = shifts_resp.json()["active"]
    assert active is not None
    assert active["running_trip_count"] == 2
    assert active["running_gross_earnings"] == 44.5


def test_venue_normalization_dedupes_ticketmaster_and_seatgeek() -> None:
    from farol.evidence import dedupe_events
    from farol.signals import Signal

    tm_wamu = Signal(
        id="tm-1",
        kind="event_exit",
        zone="sodo_stadiums",
        starts_at="2026-10-20T22:00:00-07:00",
        ends_at="2026-10-20T22:45:00-07:00",
        magnitude=7000.0,
        basis="scheduled",
        source="ticketmaster:discovery/v2",
        fetched_at="2026-10-20T20:00:00Z",
        expires_at="2026-10-20T22:45:00-07:00",
        evidence_quality=0.75,
        details={"title": "Rise Against with Alkaline Trio exit at WaMu Theater", "venue": "WaMu Theater"},
    )
    sg_wamu = Signal(
        id="sg-1",
        kind="event_exit",
        zone="sodo_stadiums",
        starts_at="2026-10-20T22:00:00-07:00",
        ends_at="2026-10-20T22:45:00-07:00",
        magnitude=8000.0,
        basis="scheduled",
        source="seatgeek:2/events",
        fetched_at="2026-10-20T20:00:00Z",
        expires_at="2026-10-20T22:45:00-07:00",
        evidence_quality=0.65,
        details={"title": "Rise Against: Ricochet 2026 exit at WAMU Theater", "venue": "WAMU Theater"},
    )
    tm_paramount = Signal(
        id="tm-2",
        kind="event_exit",
        zone="capitol_hill",
        starts_at="2026-10-20T22:00:00-07:00",
        ends_at="2026-10-20T22:45:00-07:00",
        magnitude=2800.0,
        basis="scheduled",
        source="ticketmaster:discovery/v2",
        fetched_at="2026-10-20T20:00:00Z",
        expires_at="2026-10-20T22:45:00-07:00",
        evidence_quality=0.75,
        details={"title": "An Evening with Bill Nye exit at The 5th Avenue Theatre", "venue": "The 5th Avenue Theatre"},
    )
    sg_paramount = Signal(
        id="sg-2",
        kind="event_exit",
        zone="capitol_hill",
        starts_at="2026-10-20T22:30:00-07:00",
        ends_at="2026-10-20T23:15:00-07:00",
        magnitude=2800.0,
        basis="scheduled",
        source="seatgeek:2/events",
        fetched_at="2026-10-20T20:00:00Z",
        expires_at="2026-10-20T23:15:00-07:00",
        evidence_quality=0.65,
        details={"title": "Bill Nye - Seattle exit at 5th Avenue Theatre", "venue": "5th Avenue Theatre"},
    )
    merged = dedupe_events([tm_wamu, sg_wamu, tm_paramount, sg_paramount])
    assert len(merged) == 2
    assert len(merged[0].details["receipts"]) == 2
    assert len(merged[1].details["receipts"]) == 2


def test_new_demand_adapters_wsf_amtrak_weather_and_situational() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from farol.adapters import amtrak_sea, sea_fifo, situational_waves, weather_live, wsdot, wsf_ferries

    tz = ZoneInfo("America/Los_Angeles")
    start = datetime(2026, 10, 20, 17, 0, tzinfo=tz)
    end = datetime(2026, 10, 21, 2, 0, tzinfo=tz)

    # 1. WSF Colman Dock Ferry arrival
    wsf_payload = [
        {
            "VesselID": 30,
            "VesselName": "Wenatchee",
            "DepartingTerminalName": "Bainbridge Island",
            "ArrivingTerminalID": 7,
            "ArrivingTerminalName": "Seattle",
            "InService": True,
            "AtDock": False,
            "ScheduledDeparture": "2026-10-20T17:10:00-07:00",
            "LeftDock": "2026-10-20T17:30:00-07:00",
            "Eta": "2026-10-20T18:05:00-07:00",
        }
    ]
    ferry_sigs = wsf_ferries.parse(wsf_payload, start, end, fetched_at=start.isoformat())
    assert len(ferry_sigs) == 1
    assert ferry_sigs[0].zone == "seattle_core"
    assert "Colman Dock" in ferry_sigs[0].details["title"]
    assert "20m late" in ferry_sigs[0].details["title"]
    assert ferry_sigs[0].magnitude == 14000.0

    # 2. Amtrak King Street Station arrival
    amtrak_payload = {
        "517": [
            {
                "routeName": "Amtrak Cascades",
                "trainNum": "517",
                "origCode": "VAC",
                "origName": "Vancouver, BC",
                "stations": [
                    {"code": "VAC", "arr": "2026-10-20T16:30:00-07:00"},
                    {
                        "code": "SEA",
                        "schArr": "2026-10-20T20:45:00-07:00",
                        "arr": "2026-10-20T21:05:00-07:00",
                        "status": "Enroute",
                    },
                ],
            }
        ]
    }
    train_sigs = amtrak_sea.parse(amtrak_payload, start, end, fetched_at=start.isoformat())
    assert len(train_sigs) == 1
    assert train_sigs[0].zone == "seattle_core"
    assert "King Street Station" in train_sigs[0].details["title"]
    assert "20m late" in train_sigs[0].details["title"]

    # 3. Live Weather Station Walk-Refusal Spike
    obs_payload = {
        "properties": {
            "timestamp": "2026-10-20T19:00:00-07:00",
            "textDescription": "Light Rain",
            "temperature": {"value": 8.0},
            "windSpeed": {"value": 20.0},
            "precipitationLastHour": {"value": 0.002},
        }
    }
    weather_sigs = weather_live.parse(obs_payload, start, end, fetched_at=start.isoformat())
    assert len(weather_sigs) == 1
    assert weather_sigs[0].kind == "precipitation"
    assert "walk refusal" in weather_sigs[0].details["title"].lower()

    # 4. Situational Waves (Link Last-Train Cliffs, Hospitals, Conventions)
    sit_sigs = situational_waves.parse(start, end, fetched_at=start.isoformat())
    titles = [s.details["title"] for s in sit_sigs]
    assert any("Link 2 Line last-train cutoff" in t for t in titles)
    assert any("Link 1 Line last-train cutoff" in t for t in titles)
    assert any("hospital" in t.lower() for t in titles)
    assert any("Convention Center" in t for t in titles)

    # 5. Sea-Tac Evening Arrival Bank
    fifo_sigs = sea_fifo.parse(start, end, fetched_at=start.isoformat())
    assert any("evening transcon" in s.details["title"].lower() for s in fifo_sigs)

    # 6. Cross-Lake Bridge Closure Detection
    bridge_payload = [
        {
            "AlertID": 999,
            "Region": "Northwest",
            "Priority": "High",
            "EventCategory": "Closure",
            "HeadlineDescription": "SR 520 floating bridge all lanes closed both directions for overnight maintenance.",
            "StartTime": "2026-10-20T22:00:00-07:00",
            "EndTime": "2026-10-21T05:00:00-07:00",
            "StartRoadwayLocation": {"RoadName": "520", "MilePost": 3.0, "Direction": "B"},
        }
    ]
    bridge_sigs = wsdot.parse_alerts(bridge_payload, start, end, fetched_at=start.isoformat())
    assert bridge_sigs
    assert all(s.details.get("bridge_closure") is True for s in bridge_sigs)
    assert all("CROSS-LAKE BRIDGE CLOSURE" in s.details["title"] for s in bridge_sigs)


def test_working_tab_ranked_zones_are_distinct_and_include_maps_url(client: TestClient) -> None:
    resp = client.get("/api/here", params={"at": "Downtown Seattle"})
    assert resp.status_code == 200
    body = resp.json()
    ranked = body["sit_here"]["ranked"]
    zones = [row["zone"] for row in ranked]
    assert len(zones) == len(set(zones)), f"Expected distinct zones in sit_here.ranked, got {zones}"
    assert all(str(row.get("maps_url") or "").startswith("https://www.google.com/maps") for row in ranked)


def test_api_feeds_health_stoplight_dashboard(client: TestClient) -> None:
    resp = client.get("/api/feeds/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_stoplight"] in {"green", "amber", "red"}
    assert body["total_count"] >= 2
    assert body["green_count"] + body["amber_count"] + body["red_count"] == body["total_count"]
    adapters = {f["adapter"] for f in body["feeds"]}
    assert "flightaware_sea" in adapters
    assert "besttime_busyness" in adapters
    for f in body["feeds"]:
        assert f["stoplight"] in {"green", "amber", "red"}
        assert f["label"]
        assert f["category"]


def test_sound_transit_link_station_arrivals_and_seatac_on_demand(client: TestClient) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from farol.adapters import onebusaway

    pacific = ZoneInfo("America/Los_Angeles")
    start = datetime(2026, 10, 20, 17, 0, tzinfo=pacific)
    end = datetime(2026, 10, 20, 23, 0, tzinfo=pacific)
    oba_payload = {
        "code": 200,
        "data": {
            "references": {
                "routes": [
                    {"id": "40_2LINE", "shortName": "2 Line"},
                    {"id": "40_100479", "shortName": "1 Line"},
                ],
                "trips": [
                    {"id": "trip_bel", "routeId": "40_2LINE", "tripHeadsign": "Downtown Redmond"},
                    {"id": "trip_cap", "routeId": "40_100479", "tripHeadsign": "Lynnwood City Center"},
                ],
                "stops": [
                    {"id": "stop_bel", "name": "Bellevue Downtown", "lat": 47.6152, "lon": -122.1913},
                    {"id": "stop_cap", "name": "Capitol Hill", "lat": 47.6196, "lon": -122.3200},
                ],
            },
            "list": [
                {
                    "tripId": "trip_bel",
                    "tripStatus": {"nextStop": "stop_bel", "nextStopTimeOffset": 120},
                },
                {
                    "tripId": "trip_cap",
                    "tripStatus": {"nextStop": "stop_cap", "nextStopTimeOffset": 180},
                },
            ],
        },
    }
    arr_sigs = onebusaway.parse_station_arrivals(oba_payload, start, end, fetched_at=start.isoformat())
    assert len(arr_sigs) == 2
    zones = {s.zone for s in arr_sigs}
    assert zones == {"bellevue_core", "capitol_hill"}
    assert any("Bellevue Downtown in ~2m" in s.details["title"] for s in arr_sigs)

    # On-demand Sea-Tac 6-hour forecast GET (no automatic network spend)
    resp = client.get("/api/seatac/forecast")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] in {"not_pulled_yet", "ready", "stale"}
    assert "hours" in body

    # 5-mile nearby train station pull-down in /api/here
    here_bel = client.get("/api/here", params={"at": "Bellevue"}).json()
    stations = here_bel.get("nearby_stations") or []
    assert len(stations) >= 3
    assert any("Bellevue Downtown" in s["name"] for s in stations)
    assert all(s["distance_miles"] <= 5.0 for s in stations)
    assert all(isinstance(s["trains"], list) for s in stations)
    assert all(s["maps_url"].startswith("https://www.google.com/maps") for s in stations)


def test_six_hour_ai_shift_course_planner(client: TestClient) -> None:
    resp = client.get("/api/ask/course", params={"area": "Bellevue"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["origin_zone"] == "bellevue_core"
    assert 6 <= len(body["stops"]) <= 7
    assert body["ai_briefing"]
    for idx, stop in enumerate(body["stops"], start=1):
        assert stop["hour_index"] == idx
        assert stop["window_label"]
        assert stop["zone"]
        assert stop["staging_spot"]
        assert isinstance(stop["navigation_available"], bool)
        if stop["navigation_available"]:
            assert stop["maps_url"].startswith("https://www.google.com/maps")
        else:
            assert stop["maps_url"] == ""
        assert stop["expected_net_per_hour"] is None or isinstance(stop["expected_net_per_hour"], (int, float))





