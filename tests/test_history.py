import csv
import json
from datetime import datetime
from unittest.mock import patch

import pytest

from farol.history import import_exports, merge_trips, summarize_history
from farol.ingest import _timestamp, parse_export
from farol.tonight import tonight_brief
from farol.trips import load_observed_trips


def export(path, *, earnings=20, tip=2, preamble=True):
    with path.open("w", encoding="utf-8", newline="") as handle:
        if preamble:
            handle.write("Washington receipt report\n")
        writer = csv.writer(handle)
        writer.writerow([
            "Request Timestamp", "Pickup Address (street, city, state)",
            "Dropoff Address (street, city, state)", "Duration (minutes)",
            "Mileage", "Your earnings", "Your earnings.Tip",
        ])
        writer.writerow([
            "Friday, September 11, 2026T11:45:00 PM Pacific Daylight Time",
            "Private Street, Kirkland, WA, US", "Other Street, Bellevue, WA, US",
            20, 5, earnings, tip,
        ])


def trip(at, end, earnings=50):
    start = datetime.fromisoformat(at)
    stop = datetime.fromisoformat(end)
    return {
        "requested_at": at, "ended_at": end, "pickup_zone": "kirkland_waterfront",
        "dropoff_zone": "bellevue_core", "duration_minutes": (stop-start).total_seconds()/60,
        "paid_miles": 5, "earnings": earnings, "tip": 5,
    }


def test_reimport_is_idempotent_and_updated_tip_replaces_trip(tmp_path):
    original, updated = tmp_path / "week.csv", tmp_path / "updated.csv"
    export(original)
    export(updated, earnings=25, tip=7)
    directory = tmp_path / "private"
    assert import_exports([original], directory)["added"] == 1
    assert import_exports([original], directory)["added"] == 0
    result = import_exports([updated], directory)
    assert result["revised"] == 1
    assert result["total_trips"] == 1
    saved = (directory / "receipts.json").read_text()
    assert "Private Street" not in saved and "Other Street" not in saved
    assert "source_file" not in saved
    assert json.loads(saved)["trips"][0]["earnings"] == 25
    assert json.loads(saved)["trips"][0]["tip"] == 7


def test_bad_batch_does_not_partially_replace_ledger(tmp_path):
    good, bad = tmp_path / "week.csv", tmp_path / "bad.csv"
    export(good)
    bad.write_text("not a receipt\n")
    directory = tmp_path / "private"
    import_exports([good], directory)
    before = (directory / "receipts.json").read_bytes()
    with pytest.raises(ValueError):
        import_exports([good, bad], directory)
    assert (directory / "receipts.json").read_bytes() == before


def test_preview_does_not_write_and_header_without_preamble_is_supported(tmp_path):
    path = tmp_path / "week.csv"
    export(path, preamble=False)
    directory = tmp_path / "private"
    assert import_exports([path], directory, preview=True)["total_trips"] == 1
    assert not directory.exists()


def test_winter_export_preserves_standard_time():
    stamp = _timestamp("Friday, January 09, 2026T8:45:24 PM Pacific Standard Time")
    assert stamp.isoformat() == "2026-01-09T20:45:24-08:00"


def test_legacy_csv_and_new_ledger_share_one_trip(tmp_path):
    path = tmp_path / "week.csv"
    export(path)
    updated = tmp_path / "outside" / "updated.csv"
    updated.parent.mkdir()
    export(updated, earnings=25, tip=7)
    import_exports([updated], tmp_path)
    with patch.dict("os.environ", {"FAROL_FIELD_DATA_DIR": str(tmp_path), "FAROL_USE_FIELD_TRIPS": "1"}):
        trips = load_observed_trips()
    assert len(trips) == 1
    assert trips[0]["earnings"] == 25
    assert trips[0]["id"] == merge_trips(parse_export(path))[0]["id"]


def test_friday_continues_after_midnight_but_next_week_is_separate():
    rows = [
        trip("2026-09-11T20:00:00-07:00", "2026-09-11T20:30:00-07:00", 80),
        trip("2026-09-11T23:00:00-07:00", "2026-09-11T23:30:00-07:00", 70),
        trip("2026-09-12T00:30:00-07:00", "2026-09-12T01:00:00-07:00", 60),
        trip("2026-09-18T20:00:00-07:00", "2026-09-18T20:30:00-07:00", 50),
    ]
    report = summarize_history(list(reversed(rows)))
    assert report["session_count"] == 2
    assert report["friday_sessions"] == 2
    friday = report["sessions"][1]
    assert friday["date"] == "2026-09-11"
    assert friday["gross_earnings"] == 210
    assert friday["receipt_span_minutes"] == 300
    assert friday["paid_mile_cost"] == 6.75
    assert friday["net_per_committed_hour"] is None


def test_time_floor_does_not_convert_signal_points_into_money():
    low = tonight_brief(value_of_time_per_hour=1)
    high = tonight_brief(value_of_time_per_hour=200)
    for brief in (low, high):
        assert brief["shift_decision"]["action"] == "CHECK WINDOW"
        assert brief["shift_decision"]["value_of_time_met"] is None
        assert brief["shift_decision"]["earnings_status"] == "uncalibrated"
        assert all(item["expected_net_per_hour"] is None for item in brief["opportunities"])
    assert low["shift_decision"]["signal_timing"] == "later"


def test_missing_feeds_do_not_establish_unprofitable_shift():
    with patch("farol.tonight.gather_signals", return_value=([], [])):
        brief = tonight_brief()
    assert brief["shift_decision"]["action"] == "NO CLEAR SIGNAL"
    assert brief["shift_decision"]["best_window"] is None
    assert brief["shift_decision"]["value_of_time_met"] is None


def test_all_missed_opportunities_cannot_be_recommended():
    brief = tonight_brief(now=datetime.fromisoformat("2026-08-16T12:00:00-07:00"))
    assert brief["shift_decision"]["action"] == "NO CLEAR SIGNAL"


def test_cancellation_counts_as_earnings_but_not_as_completed_ride_evidence():
    from farol.recommend import rank_next_hours

    canceled = trip("2026-09-11T20:00:00-07:00", "2026-09-11T20:00:00-07:00", 6.13)
    canceled["paid_miles"] = 0
    report = summarize_history([canceled])
    assert report["trips"] == 1
    assert report["completed_trip_count"] == 0
    assert report["sessions"][0]["gross_earnings"] == 6.13
    board = rank_next_hours(
        [canceled], now=datetime.fromisoformat(canceled["requested_at"]),
        origin_zone="kirkland_waterfront", hours=1,
    )
    assert all(item["sample_trips"] == 0 for item in board["ranked"])


def test_wamu_does_not_generate_its_own_stadium_penalty_but_nearby_stadium_does():
    from dataclasses import replace

    from farol.adapters import _doctrine_signals
    from farol.signals import Signal
    from farol.tonight import _event_pickup_fact

    wamu = Signal(
        id="wamu-concert", kind="event_exit", zone="sodo_stadiums",
        starts_at="2026-09-11T22:00:00-07:00", ends_at="2026-09-11T23:00:00-07:00",
        magnitude=8000, basis="scheduled", source="synthetic", fetched_at="2026-09-11T18:00:00-07:00",
        expires_at="2026-09-11T23:00:00-07:00", evidence_quality=0.7,
        details={"venue": "WAMU Theater at Lumen Field"},
    )
    assert _doctrine_signals([wamu]) == []
    assert "Theater exit" in _event_pickup_fact(wamu, [wamu])["text"]
    stadium = replace(wamu, id="lumen-game", details={"venue": "Lumen Field"})
    penalties = _doctrine_signals([wamu, stadium])
    assert len(penalties) == 1
    assert penalties[0].details["shadowed_signal"] == "lumen-game"
    assert "outer pickup area" in _event_pickup_fact(wamu, [wamu, stadium, *penalties])["text"]
    unknown = replace(wamu, id="unknown", details={})
    assert len(_doctrine_signals([unknown])) == 1


def test_shift_odometer_bookmarks_calibrate_session_and_deadhead(tmp_path):
    from farol.history import active_shift_log, end_shift_log, read_shift_logs, start_shift_log

    started = start_shift_log(
        41200.0,
        tmp_path,
        started_at="2026-09-11T19:45:00-07:00",
        note="Friday shift start",
    )
    assert active_shift_log(tmp_path)["shift_id"] == started["shift_id"]
    with pytest.raises(ValueError):
        start_shift_log(41205.0, tmp_path)
    ended = end_shift_log(
        41230.0,
        tmp_path,
        ended_at="2026-09-12T01:45:00-07:00",
        note="Back home",
    )
    assert active_shift_log(tmp_path) is None
    assert ended["total_miles"] == 30.0
    assert ended["committed_minutes"] == 360.0
    rows = [
        trip("2026-09-11T20:00:00-07:00", "2026-09-11T20:30:00-07:00", 80),
        trip("2026-09-11T23:00:00-07:00", "2026-09-11T23:30:00-07:00", 70),
        trip("2026-09-12T00:30:00-07:00", "2026-09-12T01:00:00-07:00", 60),
    ]
    report = summarize_history(rows, 0.45, shift_logs=read_shift_logs(tmp_path))
    assert report["earnings_status"] == "calibrated"
    assert report["calibrated_sessions"] == 1
    session = report["sessions"][0]
    assert session["total_miles"] == 30.0
    assert session["deadhead_miles"] == 15.0
    assert session["committed_minutes"] == 360.0
    assert session["net_per_committed_hour"] == round((210.0 - 30.0 * 0.45) / 6.0, 2)


def test_local_anchor_approval_custom_curb_and_persistent_navigation(tmp_path):
    from farol.dashboard import FIXTURES
    from farol.navigation import NavigationCommand, NavigationMailbox, NavigationPoint
    from farol.signals import load_anchors, save_anchor_override, save_custom_anchor

    updated = save_anchor_override(
        "the_lime_kirkland",
        approval_status="approved",
        safety_notes="Approved legal parking at Rose Hill Plaza.",
        local_dir=tmp_path,
    )
    assert updated.approval_status == "approved"
    custom = save_custom_anchor(
        zone="totem_lake",
        label="Kingsgate Park & Ride East Lot",
        latitude=47.717,
        longitude=-122.181,
        local_dir=tmp_path,
    )
    assert custom.id == "totem_lake-driver-curb"
    merged = {item.id: item for item in load_anchors(FIXTURES / "anchors.json", local_dir=tmp_path)}
    assert merged["the_lime_kirkland"].approval_status == "approved"
    assert merged["totem_lake-driver-curb"].approval_status == "approved"

    store_file = tmp_path / "nav.json"
    box1 = NavigationMailbox(store_path=store_file)
    cmd = NavigationCommand(
        command_id="cmd-1",
        created_at="2026-09-11T20:00:00+00:00",
        expires_at="2099-09-11T20:20:00+00:00",
        action="MOVE",
        destination=NavigationPoint("Rose Hill Plaza", 47.6794, -122.1813),
        waypoints=(),
        source_mode="live",
        driver_confirmation_required=True,
        demo_only=False,
    )
    box1.publish(cmd)
    box2 = NavigationMailbox(store_path=store_file)
    restored = box2.current()
    assert restored is not None
    assert restored.command_id == "cmd-1"
    assert "47.679400,-122.181300" in restored.public()["maps_url"]
