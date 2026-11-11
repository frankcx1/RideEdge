from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from farol.here import advise, resolve
from farol.zones import load_zones
from farol.collect import feed_health_view, feed_detail_view
from farol.adapters import ticketmaster
from farol import uber_intelligence as ui

TZ = ZoneInfo("America/Los_Angeles")


def test_now01_stay_emits_wait_action_and_stay_decision_state():
    now = datetime(2026, 10, 21, 18, 30, tzinfo=TZ)
    res = advise("Bellevue Core", now=now)
    som = res["stay_or_move_card"]
    assert res["action"] in ("WAIT", "MOVE", "WATCH")
    if som["decision_state"] == "STAY":
        assert res["action"] == "WAIT"
        assert som["action"] == "WAIT"


def test_now02_residential_home_preserves_coords_and_evaluates_same_zone_positioning(monkeypatch):
    # Artificial test-only origin; never a driver's saved residence.
    from dataclasses import replace
    registry = replace(load_zones(), origin_latitude=47.73, origin_longitude=-122.20)
    monkeypatch.setattr("farol.here.load_zones", lambda: registry)
    now = datetime(2026, 10, 21, 18, 30, tzinfo=TZ)
    resolved = resolve("Home")
    assert resolved["zone"] == "totem_lake"
    assert resolved["origin_kind"] in ("residential_home", "residential_place")
    assert abs(resolved["latitude"] - registry.origin_latitude) < 1e-3
    assert abs(resolved["longitude"] - registry.origin_longitude) < 1e-3
    assert abs(resolved["latitude"] - 47.7138) > 0.005

    res = advise(
        "Home",
        now=now,
        driver_mode="active_working",
    )
    som = res["stay_or_move_card"]
    assert res["action"] == "MOVE"
    assert som["decision_state"] == "MOVE"
    assert som["recommendation_basis"] in ("positioning_heuristic", "live_opportunity", "historical_and_positioning")
    assert som["destination_label"]
    # Same-zone move from residential home to Village at Totem Lake must have non-zero drive distance/time
    best = res["best"]
    assert best is not None
    assert best["reposition_minutes"] > 0.5
    assert best["reposition_miles"] > 0.2
    if som["recommendation_basis"] == "positioning_heuristic":
        assert "unverified" in som["suitability_reason"].lower() or "unverified" in res["spoken"].lower()


def test_now04_driver_modes_suppress_automatic_positioning():
    now = datetime(2026, 10, 21, 18, 30, tzinfo=TZ)
    for mode in ("offline", "on_break", "waiting_at_home"):
        res = advise(
            "Home",
            now=now,
            driver_mode=mode,
        )
        assert res["action"] == "WATCH"
        assert res["stay_or_move_card"]["decision_state"] in ("OFFLINE", "ON_BREAK", "WAITING_AT_HOME", "WATCH")


def test_ux01_feed_health_counts_reconcile():
    health = feed_health_view()
    assert health["enabled_count"] + health["disabled_count"] == health["total_count"]
    assert health["healthy_count"] + health["degraded_count"] == health["enabled_count"]
    assert health["service_health_note"]
    feeds = health["feeds"]
    assert len(feeds) == health["total_count"]
    enabled_rows = [f for f in feeds if f["enabled"]]
    healthy_rows = [f for f in enabled_rows if f["healthy"]]
    assert len(enabled_rows) == health["enabled_count"]
    assert len(healthy_rows) == health["healthy_count"]


def test_ux02_ticketmaster_detail_exposes_retained_events_and_mapped_signals():
    detail = feed_detail_view("ticketmaster_events")
    assert detail["adapter"] == "ticketmaster_events"
    if detail["detail_state"] == "ready":
        assert detail["unique_events_count"] >= 1
        assert detail["mapped_signals_count"] + detail["excluded_events_count"] == detail["unique_events_count"]
        events = detail["events"]
        assert len(events) == detail["unique_events_count"]
        mapped = [e for e in events if e["mapping_status"] == "mapped_signal"]
        excluded = [e for e in events if e["mapping_status"] != "mapped_signal"]
        assert len(mapped) == detail["mapped_signals_count"]
        assert len(excluded) == detail["excluded_events_count"]
        for ev in events:
            assert ev["source_end_basis"] == "not_reported_by_provider"
            if ev["mapping_status"] == "mapped_signal":
                assert ev["estimated_departure_start"]
                assert ev["estimated_departure_end"]
            else:
                assert ev["exclusion_reason"]


def test_ux02_details_not_saved_fallback_when_no_retained_or_cached_records(tmp_path, monkeypatch):
    monkeypatch.setattr(ticketmaster, "cache_dir", lambda: tmp_path)
    detail = ticketmaster.load_retained_detail()
    assert detail is None


def test_ux03_routine_transit_and_ferry_inventories_excluded_from_now():
    now = datetime(2026, 10, 21, 18, 30, tzinfo=TZ)
    res = advise("Bellevue Core", now=now)
    for row in res["nearby"]:
        hl = row.get("headline", "").lower()
        assert not hl.startswith("link light rail arriving:")
        assert "ferry arrival" not in hl
    spoken = res.get("spoken", "").lower()
    assert "link light rail arriving:" not in spoken


def test_uia01_to_uia10_python_uber_intelligence(tmp_path):
    # UIA01: Labeled multi-area summary lines
    raw = (
        "Summary:\n"
        "- Downtown Seattle: 120 requests in the last 30 mins, 4 min wait, 14 mins away\n"
        "- Bellevue: 45 requests in the last 30 mins, 30+ min wait, 6 mins away\n"
        "As of 6:42 PM."
    )
    draft = ui.parse_assistant_response(raw, created_at="2026-10-21T18:45:00-07:00")
    by_key = {o["area_key"]: o for o in draft["observations"]}
    assert "seattle_core" in by_key
    assert "bellevue_core" in by_key
    assert by_key["seattle_core"]["requests_30m"] == 120
    assert by_key["seattle_core"]["wait_minutes_exact"] == 4.0
    assert by_key["bellevue_core"]["requests_30m"] == 45
    assert by_key["bellevue_core"]["wait_minutes_lower_bound"] == 30.0
    assert draft["reported_source_time_raw"] is not None

    # UIA02: Non-P90 statistics
    raw_stat = "Kirkland: 20 requests in the last 30 mins, median wait 9 min (estimated_wait_time_p50)."
    draft_stat = ui.parse_assistant_response(raw_stat, created_at="2026-10-21T18:45:00-07:00")
    obs_k = draft_stat["observations"][0]
    assert obs_k["wait_statistic"] == "p50"
    assert obs_k["claimed_source_field"] == "estimated_wait_time_p50"

    # UIA05: Conflicting assertions preserved
    raw_conflict = "Bellevue: 5 min wait in card, but narrative says 22 min wait and 18 requests in the last 30 mins vs 60 requests in the last 30 mins."
    draft_c = ui.parse_assistant_response(raw_conflict, created_at="2026-10-21T18:45:00-07:00")
    obs_c = draft_c["observations"][0]
    assert len(obs_c["candidate_exact_waits"]) >= 2

    # UIA06: Post-edit re-validation flags negative / >240 wait or >5000 requests and repository blocks save
    edited = ui.apply_user_review_edits(
        draft,
        {
            draft["observations"][0]["id"]: {"wait_minutes_exact": -5.0},
        },
    )
    assert ui.FLAG_OUT_OF_RANGE_VALUE in edited["observations"][0]["warnings"]
    repo_valid = ui.AssistantObservationRepository(tmp_path / "valid_imports.json")
    save_neg = repo_valid.save_import(edited)
    assert save_neg["saved"] is False

    # UIA08: Corrupt storage file is never overwritten on save
    store_file = tmp_path / "corrupt_imports.json"
    corrupt_bytes = "{not valid json at all!!!"
    store_file.write_text(corrupt_bytes, encoding="utf-8")
    repo_corrupt = ui.AssistantObservationRepository(store_file)
    save_corrupt = repo_corrupt.save_import(draft)
    assert save_corrupt["saved"] is False
    assert ui.FLAG_UNPARSEABLE_STORAGE in save_corrupt["warnings"]
    assert store_file.read_text(encoding="utf-8") == corrupt_bytes


def test_r201_to_r212_round3_backend_safeguards(tmp_path, monkeypatch):
    from farol import here, zones, collect
    from farol.adapters import onebusaway
    from datetime import timedelta

    now = datetime(2026, 10, 21, 12, 0, tzinfo=TZ)
    empty_window = {"opportunities": [], "feeds": []}
    two_trips = [
        {
            "pickup_zone": "totem_lake",
            "dropoff_zone": "totem_lake",
            "requested_at": "2026-10-14T12:00:00-07:00",
            "ended_at": "2026-10-14T12:12:00-07:00",
            "duration_minutes": 12,
            "earnings": 20.0,
            "paid_miles": 2.0,
        }
    ] * 2

    # R2-01: Two ordinary zone trips in totem_lake must not suppress residential driveway positioning
    res_home = here.advise(
        "Home",
        now=now,
        trips=two_trips,
        scored_window=empty_window,
        driver_mode="active_working",
        max_reposition_minutes=20,
    )
    assert res_home["action"] == "MOVE"
    assert res_home["stay_or_move_card"]["recommendation_basis"] == "positioning_heuristic"

    # R2-01: Positioned pickup center holds for 15m when local history is empty
    res_pos = here.advise(
        "Village at Totem Lake",
        now=now,
        trips=[],
        scored_window=empty_window,
        driver_mode="active_working",
        max_reposition_minutes=20,
    )
    assert res_pos["action"] == "WAIT"
    assert res_pos["stay_or_move_card"]["decision_state"] == "STAY"
    assert res_pos["stay_or_move_card"]["recommendation_basis"] == "positioned_pickup_center"

    # R2-01: Neighborhood alias Juanita resolves as neighborhood, not pickup_center
    resolved_juanita = here.resolve("Juanita")
    assert resolved_juanita["origin_kind"] == "neighborhood"
    assert resolved_juanita["place_id"] == "juanita"

    # R2-02: Pickup centers default to anchor_approved=False and unapproved curb has navigation_available=False
    for pc in zones.load_zones().pickup_centers:
        assert pc.anchor_approved is False
    monkeypatch.setattr("farol.tonight.load_anchors", lambda: [])
    res_unapproved = here.advise(
        "Home",
        now=now,
        trips=[],
        scored_window=empty_window,
        driver_mode="active_working",
        max_reposition_minutes=20,
    )
    assert res_unapproved["stay_or_move_card"]["staging_approved"] is False
    assert res_unapproved["stay_or_move_card"]["navigation_available"] is False

    # R2-08: Ticketmaster retained detail rejects mismatched snapshot_id or count mismatch
    import json
    (tmp_path / "source_details").mkdir(exist_ok=True)
    old_tm = {
        "events": [{"id": "old-event", "title": "Old retained event"}],
        "signals": [],
        "fetched_at": "2026-10-14T12:00:00-07:00",
        "window_start": "2026-10-14T12:00:00-07:00",
    }
    (tmp_path / "source_details" / f"{ticketmaster.NAME}.json").write_text(json.dumps(old_tm), encoding="utf-8")
    snap = {
        "snapshot_id": "current-snapshot",
        "collected_at": now.isoformat(),
        "feeds": [
            {
                "adapter": ticketmaster.NAME,
                "mode": "live",
                "fetched_at": now.isoformat(),
                "signal_count": 1,
                "detail": "1 mapped exits from 1 unique TM events",
            }
        ],
    }
    (tmp_path / "awareness_snapshot.json").write_text(json.dumps(snap), encoding="utf-8")
    monkeypatch.setattr("farol.adapters.base.cache_dir", lambda: tmp_path)
    monkeypatch.setattr(ticketmaster, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr("farol.adapters.base.read_cache", lambda *a, **kw: None)
    monkeypatch.setattr("farol.awareness.saved_besttime", lambda *a, **kw: None)
    tm_det = collect.feed_detail_view(ticketmaster.NAME, now=now)
    assert tm_det["detail_state"] == "details_not_saved"
    assert tm_det.get("events", []) == []

    # R2-09: Expired OBA Link telemetry (>10m old) does not rebase arrival ETA at read time
    fetched = now - timedelta(hours=2)
    payload = {
        "data": {
            "references": {
                "routes": [{"id": "40_2LINE", "shortName": "2 Line"}],
                "trips": [{"id": "trip", "routeId": "40_2LINE", "tripHeadsign": "Redmond"}],
                "stops": [{"id": "station", "name": "Bellevue Downtown", "lat": 47.615, "lon": -122.194}],
            },
            "list": [{"tripId": "trip", "tripStatus": {"nextStop": "station", "nextStopTimeOffset": 300}}],
        }
    }
    snap["feeds"] = [
        {
            "adapter": "onebusaway_transit",
            "mode": "cache",
            "fetched_at": fetched.isoformat(),
            "signal_count": 1,
            "detail": "1 station arrivals",
        }
    ]
    (tmp_path / "awareness_snapshot.json").write_text(json.dumps(snap), encoding="utf-8")
    monkeypatch.setattr(
        "farol.adapters.base.read_cache",
        lambda key: {"fetched_at": fetched.isoformat(), "payload": payload} if key == "onebusaway_st40_vehicles" else None,
    )
    oba_a = collect.feed_detail_view("onebusaway_transit", now=now)
    oba_b = collect.feed_detail_view("onebusaway_transit", now=now + timedelta(minutes=5))
    assert oba_a["records"][0]["basis"] == "expired_telemetry"
    assert oba_a["records"][0]["eta_minutes"] is None
    assert oba_a["records"][0]["arrival_time"] == oba_b["records"][0]["arrival_time"]

    # R2-10: Editing drive_minutes does not clear unresolved wait conflicts
    conflict_draft = ui.parse_assistant_response(
        "Bellevue: wait 4 minutes. Bellevue: wait 30 minutes.",
        created_at="2026-10-21T19:00:00Z",
    )
    obs_id = conflict_draft["observations"][0]["id"]
    edited_drive = ui.apply_user_review_edits(conflict_draft, {obs_id: {"drive_minutes": 6.0}})
    assert ui.FLAG_CARD_NARRATIVE_CONFLICT in edited_drive["observations"][0]["warnings"]

    # R2-12: Unknown adapter mode with fetched_at=None is amber and not healthy
    snap["feeds"] = [{"adapter": "onebusaway_transit", "mode": "unknown", "fetched_at": None, "signal_count": 0}]
    (tmp_path / "awareness_snapshot.json").write_text(json.dumps(snap), encoding="utf-8")
    monkeypatch.setattr("farol.adapters.base.read_cache", lambda *a, **kw: None)
    fh = collect.feed_health_view(now=now)
    oba_row = next(r for r in fh["feeds"] if r["adapter"] == "onebusaway_transit")
    assert oba_row["healthy"] is False
    assert oba_row["stoplight"] == "amber"

    # R3-07: Separate sentence metric binds to single area and creates unassigned row when multi-area
    single_area_sep = ui.parse_assistant_response(
        "Totem Lake: 38 requests in the last 30 minutes. Median wait 4 minutes. Source updated at 2026-10-21T20:10:00Z.",
        created_at="2026-10-21T20:12:00Z",
    )
    totem_obs = next(o for o in single_area_sep["observations"] if o["area_key"] == "totem_lake")
    assert totem_obs["requests_30m"] == 38
    assert totem_obs["wait_minutes_exact"] == 4
    assert totem_obs["wait_statistic"] == "p50"

    multi_area_sep = ui.parse_assistant_response(
        "Bellevue: 38 requests in the last 30 minutes. Redmond: 20 requests in the last 30 minutes. Median wait 4 minutes.",
        created_at="2026-10-21T20:12:00Z",
    )
    bel_obs = next(o for o in multi_area_sep["observations"] if o["area_key"] == "bellevue_core")
    red_obs = next(o for o in multi_area_sep["observations"] if o["area_key"] == "redmond_downtown")
    unassigned_obs = next(o for o in multi_area_sep["observations"] if o["area_key"] is None)
    assert bel_obs["wait_minutes_exact"] is None
    assert red_obs["wait_minutes_exact"] is None
    assert unassigned_obs["wait_minutes_exact"] == 4


