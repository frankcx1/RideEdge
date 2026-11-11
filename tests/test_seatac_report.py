import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from farol import seatac_report as report
from farol.adapters import base, flightaware
from farol.usage import current_run

NOW = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)


def row(ident="TEST1", at=NOW + timedelta(minutes=10), **extra):
    return {"ident": ident, "scheduled_in": at.isoformat(), "origin": {"code": "KLAX"}, **extra}


def hour(payload, index=0, mode="live", fetched=NOW):
    return report.normalize_hour(
        index,
        NOW + timedelta(hours=index),
        NOW + timedelta(hours=index + 1),
        payload,
        mode,
        fetched.isoformat(),
        set(),
        flightaware.LONG_HAUL_ORIGINS,
        flightaware._origin_code,
    )


def saved(hours):
    return {"report_schema_version": 1, "fetched_at": NOW.isoformat(), "hours": hours}


def test_windows_use_elapsed_time_and_distinguish_both_one_am_hours():
    windows = list(report.windows(NOW))
    assert len(windows) == 6 and windows[-1][2] == NOW + timedelta(hours=6)
    assert all(end - start == timedelta(hours=1) for _, start, end in windows)
    assert report.clock(windows[2][1]) == "1:00 AM PDT"
    assert report.clock(windows[3][1]) == "1:00 AM PST"
    spring = list(report.windows(datetime(2027, 3, 14, 9, 0, tzinfo=UTC)))
    assert all(end - start == timedelta(hours=1) for _, start, end in spring)
    assert "3:00 AM PDT" == report.clock(spring[1][1])


def test_partial_first_hour_is_exact_and_never_expanded_to_five_minutes():
    start = NOW + timedelta(minutes=59, seconds=30)
    windows = list(report.windows(start))
    assert windows[0][2] - windows[0][1] == timedelta(seconds=30)
    assert windows[0][2] == windows[1][1]


def test_time_provenance_prefers_actual_and_distinguishes_gate_from_landing():
    at, basis, field = report.flight_time(
        row(
            actual_in=(NOW + timedelta(minutes=12)).isoformat(),
            estimated_on=(NOW + timedelta(minutes=9)).isoformat(),
        )
    )
    assert (basis, field) == ("actual_gate", "actual_in")
    assert at == NOW + timedelta(minutes=12)
    assert (
        report.flight_time(row(estimated_on=(NOW + timedelta(minutes=8)).isoformat()))[1]
        == "estimated_landing"
    )


def test_count_only_identified_valid_unique_non_cancelled_flights_inside_half_open_window():
    payload = {
        "scheduled_arrivals": [
            row(fa_flight_id="one"),
            row(ident="CODESHARE", fa_flight_id="one"),
            row("BOUNDARY", NOW + timedelta(hours=1)),
            row("OLD", NOW - timedelta(minutes=1)),
            row("CANCEL", cancelled=True),
            row("UPS111"),
            {"ident": "NOTIME"},
            row(ident=""),
            None,
        ]
    }
    result = hour(payload)
    assert result["sampled_flights"] == 1
    assert result["returned_records"] == 9
    assert result["excluded_records"] == {
        "malformed": 1,
        "cancelled": 1,
        "cargo": 1,
        "unknown_time": 1,
        "out_of_window": 2,
        "duplicate": 1,
        "unknown_identity": 1,
    }
    assert result["timing_basis_counts"] == {"scheduled_gate": 1}


def test_missing_page_is_unknown_not_zero_and_stale_cache_cannot_win_peak():
    stale = hour({"scheduled_arrivals": [row(str(i)) for i in range(15)]}, mode="stale_cache")
    good = hour(
        {"scheduled_arrivals": [row("NEXT", NOW + timedelta(hours=1, minutes=10))]}, index=1
    )
    missing = hour(None, index=2, mode="error")
    result = report.project(saved([stale, good, missing]), NOW)
    assert result["state"] == "partial"
    assert result["best_hour_starts_at"] == good["starts_at"]
    assert result["hours"][2]["sampled_flights"] is None
    assert not result["hours"][0]["usable"]


def test_extrapolation_is_labeled_and_does_not_shrink_a_large_sample():
    result = hour(
        {
            "scheduled_arrivals": [row(str(i), NOW + timedelta(minutes=i)) for i in range(15)],
            "links": {"next": "opaque"},
        }
    )
    assert result["page_full"] and result["extrapolated"]
    assert result["estimated_planes"] == 48
    assert "Assumes uniform" in result["estimate_method"]
    large = hour(
        {"scheduled_arrivals": [row(str(i)) for i in range(60)], "links": {"next": "opaque"}}
    )
    assert large["estimated_planes"] >= large["sampled_flights"] == 60


def test_empty_pages_have_no_peak_and_future_or_expired_receipts_are_unusable():
    empty = hour({"scheduled_arrivals": []})
    assert report.project(saved([empty]), NOW)["best_hour_starts_at"] is None
    assert report.project(saved([empty]), NOW + timedelta(minutes=30))["expired"]
    future = hour({"scheduled_arrivals": [row()]}, fetched=NOW + timedelta(minutes=6))
    assert not report.project(saved([future]), NOW)["hours"][0]["usable"]


def test_projection_keeps_original_receipts_and_does_not_mutate_cache():
    original = saved([hour({"scheduled_arrivals": [row()]})])
    projected = report.project(original, NOW + timedelta(minutes=4))
    assert projected["hours"][0]["fetched_at"] == NOW.isoformat()
    assert "usable" not in original["hours"][0]
    legacy = {**original}
    legacy.pop("report_schema_version")
    assert report.project(legacy, NOW)["expired"]


def test_report_reads_do_not_fetch_and_concurrent_refresh_does_not_duplicate_calls():
    with (
        patch.object(base, "read_cache", return_value=None),
        patch.object(flightaware, "fetch_json") as fetch,
    ):
        assert flightaware.seatac_6h_forecast(NOW)["state"] == "not_pulled_yet"
        with flightaware._forecast_lock:
            assert flightaware.seatac_6h_forecast(NOW, pull=True)["refreshing"]
        fetch.assert_not_called()


def test_refresh_uses_six_single_page_requests_and_records_transport_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("FAROL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(flightaware, "_api_key", lambda: "fixture-only")
    urls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"scheduled_arrivals": []}).encode()

    def network(request, **kwargs):
        urls.append(request.full_url)
        return Response()

    monkeypatch.setattr(base, "urlopen", network)
    parent = {}
    token = current_run.set(parent)
    try:
        result = flightaware.seatac_6h_forecast(pull=True)
        assert len(urls) == 6
        assert all(parse_qs(urlsplit(url).query)["max_pages"] == ["1"] for url in urls)
        assert result["provider_usage"]["http_attempts"] == 6
        assert result["provider_usage"]["billed_cost"] is None
        assert report.stamp(result["server_time"]) >= max(report.stamp(h["fetched_at"]) for h in result["hours"])
        assert parent["aeroapi.flightaware.com"]["http_attempts"] == 6
        flightaware.seatac_6h_forecast(datetime.now(UTC))
        assert len(urls) == 6
    finally:
        current_run.reset(token)


def test_source_reports_expose_dedicated_forecast_without_network(tmp_path, monkeypatch):
    from farol.collect import feed_detail_view, feed_health_view

    monkeypatch.setenv("FAROL_CACHE_DIR", str(tmp_path))
    payload = report.project(saved([hour({"scheduled_arrivals": [row()]})]), NOW)
    base.write_cache("flightaware_ksea_6h_forecast", payload)
    with patch.object(base, "urlopen", side_effect=AssertionError("Report read attempted network")):
        health = feed_health_view(NOW)
        entry = next(f for f in health["feeds"] if f["adapter"] == "flightaware_sea")
        assert entry["signal_count"] == 1
        assert entry["count_unit"] == "retained flight records"
        assert entry["healthy"]
        detail = feed_detail_view("flightaware_sea", NOW)
        assert detail["records"][0]["flights"][0]["time_field"] == "scheduled_in"
        assert detail["records"][0]["sampled_flights"] == 1


def test_shared_phone_fixture_has_consistent_sample_counts_and_provenance():
    from pathlib import Path

    payload = json.loads((Path(__file__).parents[1]/"fixtures/contracts/seatac-v1.json").read_text(encoding="utf-8"))
    assert payload["synthetic"] is True
    assert len(payload["hours"]) == 6
    for h in payload["hours"]:
        if h["sampled_flights"] is not None:
            assert h["sampled_flights"] == len(h["flights"]) == sum(h["timing_basis_counts"].values())
        for f in h["flights"]:
            assert report.stamp(h["starts_at"]) <= report.stamp(f["arrival_at"]) < report.stamp(h["ends_at"])
