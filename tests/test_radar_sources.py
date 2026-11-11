"""Source availability is separate from retained radar decision participation."""
import copy
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import Response

from farol import api, collect, radar, radar_api
from farol.radar_contract import project
from farol.radar_sources import adapter_for, participation

NOW = datetime(2026, 10, 25, 2, 30, tzinfo=UTC)
ORIGIN = radar.origin("Bellevue")


def signal(key, source, **changes):
    return {"id": key, "source": source, "zone": "bellevue_core", "kind": "event_exit", "basis": "scheduled",
            "starts_at": NOW.isoformat(), "ends_at": (NOW+timedelta(hours=1)).isoformat(),
            "expires_at": (NOW+timedelta(hours=2)).isoformat(), "fetched_at": NOW.isoformat(),
            "details": {"venue": key, "title": key}, **changes}


def make_view():
    signals = [signal("current", "ticketmaster:events"),
               signal("future", "espn:schedule", starts_at=(NOW+timedelta(hours=1)).isoformat(),
                      ends_at=(NOW+timedelta(hours=2)).isoformat()),
               signal("old", "seatgeek:events", fetched_at=None),
               signal("rain", "nws:gridpoints", zone="all", kind="precipitation"),
               signal("airport", "flightaware:arrivals", zone="sea_airport", kind="airport_arrivals"),
               signal("unknown", "unlisted:fixture", kind="unknown")]
    return radar.build(ORIGIN, {"signals": signals}, {}, now=NOW)


def by_adapter(report, key):
    return next(row for row in report["sources"] if row["adapter"] == key)


@pytest.mark.parametrize(("source", "adapter"), [
    ("nws:SEW gridpoint 124,69", "nws_hourly"),
    ("nws:station KBFI live observation", "nws_live_observation"),
    ("wsdot:Traveler Information REST", "wsdot_traffic"),
    ("farol:SEA FIFO module (Solo staging facts + doctrine)", "sea_fifo"),
    ("port_of_seattle:seeded schedule file", "cruise_schedule"),
])
def test_current_adapter_sources_are_not_lost_under_historical_aliases(source, adapter):
    assert adapter_for(source) == adapter


def test_actual_now_context_future_plan_and_exclusions_have_distinct_meanings():
    view = make_view()
    saved = copy.deepcopy(view)
    report = participation(view, NOW)
    assert report["state"] == "reviewed"
    assert by_adapter(report, "ticketmaster_events")["now_opportunity_count"] == 1
    assert by_adapter(report, "nws_hourly")["now_context_count"] == 1
    future = by_adapter(report, "espn_seattle")
    assert future["now_opportunity_count"] == 0
    assert future["exclusions"][0]["code"] == "outside_window"
    assert future["plan_interval_count"] == 1
    assert by_adapter(report, "seatgeek_events")["exclusions"][0]["code"] == "source_timing"
    assert by_adapter(report, "flightaware_sea")["exclusions"][0]["code"] == "airport_context"
    assert by_adapter(report, "unmapped_sources")["exclusions"][0]["code"] == "unsupported_kind"
    assert view == saved
    assert "_candidate_audit" not in project(view, NOW)


def test_old_review_does_not_claim_current_now_support():
    report = participation(make_view(), NOW+timedelta(minutes=21))
    assert report["state"] == "stale"
    assert not any(row["now_opportunity_count"] for row in report["sources"])
    assert by_adapter(report, "ticketmaster_events")["plan_interval_count"] > 0  # retained outlook


def test_context_deduplication_is_explained_instead_of_silently_lost():
    signals = [signal("one", "wsdot:traffic", kind="highway_alert", zone="all"),
               signal("two", "wsdot:traffic", kind="highway_alert", zone="all")]
    view = radar.build(ORIGIN, {"signals": signals}, {}, now=NOW)
    row = by_adapter(participation(view, NOW), "wsdot_traffic")
    assert row["now_context_count"] == 1
    assert row["exclusions"][0]["id"] == "two"
    assert row["exclusions"][0]["code"] == "context_not_attached"


def test_route_provider_participation_is_separate_from_demand_evidence_and_expires():
    view = radar.build(ORIGIN, {"signals": [signal("current", "ticketmaster:events")]}, {}, now=NOW,
                       routes={"signal:current": {"minutes": 2, "miles": 1, "basis": "live traffic",
                                                  "source": "google:routes", "fetched_at": NOW.isoformat()}})
    row = by_adapter(participation(view, NOW), "google_routes_traffic")
    assert row["now_travel_count"] == 1
    assert row["now_opportunity_count"] == row["now_context_count"] == 0
    assert row["candidate_count"] == 1
    assert by_adapter(participation(view, NOW+timedelta(minutes=11)), "google_routes_traffic")["now_travel_count"] == 0


def test_besttime_rejections_preserve_identity_and_reason_without_inventing_observations():
    def venue(key, **changes):
        return {"requested": {"id": key, "name": key, "zone": "bellevue_core",
                              "address": "100 Fixture St", "city": "Bellevue"}, "identity_matched": True,
                "forecast": {"venue": {"venue_id": key, "venue_name": key, "venue_address": "100 Fixture St Bellevue"}},
                "live": {"venue_id": key, "identity_matched": True,
                         "available": True, "busyness": 0, "retrieved_at": NOW.isoformat()}, **changes}
    venues = [venue("unmatched", forecast={}), venue("quiet"),
              venue("closed", live={"venue_id": "closed", "identity_matched": True,
                                    "open_status": False, "retrieved_at": NOW.isoformat()}),
              venue("missing", live={}), venue("unknown", requested={"id": "unknown", "zone": "bad-area"})]
    view = radar.build(ORIGIN, {}, {"venues": venues}, now=NOW)
    records = by_adapter(participation(view, NOW), "besttime_busyness")["exclusions"]
    assert {r["code"] for r in records} == {"unmatched_venue", "below_activity_threshold", "closed_venue", "no_usable_activity", "unknown_area"}
    assert next(r for r in records if r["id"] == "missing")["fetched_at"] is None


def test_out_of_radius_and_early_arrival_are_inspectable_without_claiming_selection():
    events = [signal("early", "ticketmaster:events", starts_at=(NOW+timedelta(minutes=30)).isoformat()),
              signal("far", "ticketmaster:events", zone="fremont_ballard")]
    view = radar.build(ORIGIN, {"signals": events}, {}, now=NOW)
    row = by_adapter(participation(view, NOW), "ticketmaster_events")
    assert row["now_opportunity_count"] == 0
    statuses = {r["id"]: r["status"] for r in row["candidate_records"]}
    assert statuses["signal:early"] == "arrival_timing"
    assert statuses["signal:far"] in {"further_option", "outside_immediate_options"}


def test_inspection_does_not_read_inputs_start_jobs_or_extend_session():
    with patch.multiple(radar_api, _view=make_view(), _context=ORIGIN, _generation=4, _last_touch=17), \
            patch.object(radar_api.time, "monotonic", return_value=1000), \
            patch.object(radar_api, "read_inputs", side_effect=AssertionError("cache read")), \
            patch.object(radar_api, "run_once", side_effect=AssertionError("model/provider work")):
        report = radar_api.source_participation()
        assert report["snapshot_id"]
        assert radar_api._last_touch == 17
    old = {**make_view(), "context_generation": 3}
    with patch.multiple(radar_api, _view=old, _generation=4):
        assert radar_api.source_participation()["state"] == "no_decision"


def test_source_routes_attach_review_without_confusing_retained_source_snapshot():
    report = participation(make_view(), NOW)
    with patch("farol.collect.feed_health_view", return_value={"snapshot_id": "newer-source-cache", "feeds": []}), \
            patch("farol.collect.feed_detail_view", return_value={"snapshot_id": "newer-source-cache", "records": []}), \
            patch.object(radar_api, "source_participation", return_value=report):
        health = api.get_feeds_health(Response())
        detail = api.get_feed_detail("ticketmaster_events", Response())
    assert health["snapshot_id"] == detail["snapshot_id"] == "newer-source-cache"
    assert health["radar_participation"]["snapshot_id"] == report["snapshot_id"]
    assert detail["radar_participation"]["source"]["now_opportunity_count"] == 1
    assert "sources" not in detail["radar_participation"]


def test_besttime_report_does_not_relabel_stale_unmatched_reading_as_current_crowd(tmp_path):
    health = {"feeds": [{"adapter": "besttime_busyness", "label": "BestTime", "category": "venues"}]}
    retained = {"venues": [{"requested": {"id": "fixture", "name": "Fixture venue", "zone": "bellevue_core"},
                            "identity_matched": False,
                            "live": {"available": True, "busyness": 85, "retrieved_at": (NOW-timedelta(hours=2)).isoformat()}}]}
    with patch.object(collect, "feed_health_view", return_value=health), \
            patch("farol.adapters.base.cache_dir", return_value=tmp_path), \
            patch("farol.awareness.saved_besttime", return_value=retained):
        report = collect.feed_detail_view("besttime_busyness", NOW)
    record = report["records"][0]
    assert record["basis"] == "stale retained provider reading"
    assert record["live_busyness_pct"] == 85
    assert record["measurement_time"] is None
    assert not record["identity_matched"] and not record["live_usable_for_radar"]
    assert "own weekly peak" in record["detail"]
    assert "identity is unverified" in record["detail"]
