"""Calendar correctness: recurrence, revisions, uncertainty, and local-only reads."""
import json
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta
from io import BytesIO
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from farol import community_events as events
from farol.api import app
from farol.awareness import build_view
from farol.changes import diff
from farol.event_collect import Fetcher, checked_url, collection_lock, run
from farol.event_sources import (
    ParseError,
    date_span,
    festal_detail,
    festal_index,
    location,
    market_events,
    occurrence,
    trumba_events,
    visit_detail,
)
from farol.tonight import ScoringSnapshot, _confidence, _signal_value, score_window

NOW = datetime(2026, 9, 19, 11, tzinfo=events.PACIFIC)
FIRST, LAST = NOW.date(), date(2026, 10, 2)


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("FAROL_EVENTS_DIR", str(tmp_path))
    return tmp_path


def event(source="seattle_center", key="festival:2026-09-19", **extra):
    row = occurrence(source, key, "Neighborhood Festival", FIRST,
                     "https://www.seattlecenter.com/example", venue="Seattle Center",
                     hours=(time(12), time(21)), category="festival")
    row.update(extra)
    return row


def save(rows, folder, source="seattle_center", now=NOW, **kwargs):
    return events.store_source(source, rows, now=now, first=FIRST, last=LAST, folder=folder, **kwargs)


def test_repeat_crawl_changes_hours_without_duplicate_or_false_revision(folder):
    original = event()
    assert save([original], folder)["added"] == 1
    assert save([original], folder, now=NOW + timedelta(hours=1))["changed"] == 0
    updated = dict(original, ends_at="2026-09-19T20:00:00-07:00")
    assert save([updated], folder, now=NOW + timedelta(hours=2))["changed"] == 1
    rows = events.records(FIRST, LAST, folder=folder)
    assert len(rows) == 1 and rows[0]["ends_at"] == updated["ends_at"]
    with events.connect(folder) as conn:
        assert conn.execute("SELECT COUNT(*) FROM revisions").fetchone()[0] == 2


def test_refresh_receipt_is_not_a_changed_event_but_new_hours_are(folder):
    save([event()], folder)
    before = {"signals": [asdict(row) for row in events.event_signals(NOW, NOW + timedelta(hours=12), now=NOW)]}
    save([event()], folder, now=NOW + timedelta(minutes=30))
    refreshed = {"signals": [asdict(row) for row in events.event_signals(NOW, NOW + timedelta(hours=12), now=NOW)]}
    assert diff(before, refreshed, NOW) == []
    save([event(ends_at="2026-09-19T20:00:00-07:00")], folder, now=NOW + timedelta(hours=1))
    changed = {"signals": [asdict(row) for row in events.event_signals(NOW, NOW + timedelta(hours=12), now=NOW)]}
    assert [row["kind"] for row in diff(refreshed, changed, NOW)] == ["changed"]


def test_stale_secondary_source_cannot_supply_unconfirmed_hours(folder):
    save([event("visit_seattle", starts_at=None, ends_at=None)], folder, source="visit_seattle")
    save([event()], folder, now=NOW - timedelta(days=2))
    row = events.catalog(now=NOW, folder=folder)["events"][0]
    assert row["source_id"] == "visit_seattle"
    assert row["starts_at"] is None and row["ends_at"] is None


def test_rescheduled_source_identity_moves_occurrence_and_keeps_history(folder):
    original = event("neighborhoods", "city-123")
    save([original], folder, source="neighborhoods")
    moved = dict(original, local_date="2026-09-20", starts_at="2026-09-20T12:00:00-07:00",
                 ends_at="2026-09-20T21:00:00-07:00")
    save([moved], folder, source="neighborhoods", now=NOW + timedelta(hours=1))
    assert events.records(FIRST, FIRST, folder=folder) == []
    assert len(events.records(FIRST, LAST, folder=folder)) == 1


def test_cancellation_is_stored_but_not_shown_as_active_signal(folder):
    save([event()], folder)
    save([event(status="canceled")], folder, now=NOW + timedelta(hours=1))
    assert events.catalog(now=NOW, folder=folder)["events"][0]["status"] == "canceled"
    assert events.event_signals(NOW, NOW + timedelta(hours=12), now=NOW, folder=folder) == []


def test_source_outage_preserves_receipt_age_and_existing_listing(folder):
    save([event()], folder)
    save([], folder, state="error", detail="HTTP 503", now=NOW + timedelta(hours=2))
    view = events.catalog(now=NOW + timedelta(hours=2), folder=folder)
    assert view["events"][0]["last_checked"] == NOW.astimezone(events.UTC).isoformat()
    assert view["events"][0]["freshness"] == "source refresh failed"
    assert not view["events"][0]["missing_since"]
    assert view["sources"][1]["state"] == "error"


def test_disappearing_event_is_unconfirmed_never_inferred_canceled(folder):
    save([event()], folder)
    save([], folder, now=NOW + timedelta(hours=1))
    row = events.catalog(now=NOW + timedelta(hours=1), folder=folder)["events"][0]
    assert row["status"] == "scheduled"
    assert row["freshness"] == "not seen on latest check"


def test_stale_calendar_is_not_labelled_current(folder):
    save([event()], folder)
    state = events.source_status(now=NOW + timedelta(hours=37), folder=folder)
    assert next(r for r in state if r["source_id"] == "seattle_center")["state"] == "stale"


def test_sources_merge_keep_primary_hours_and_conflict_receipts(folder):
    save([event(title="The Italian Festival")], folder)
    other = event("visit_seattle", "second", title="Festal: The Italian Festival",
                  ends_at="2026-09-19T22:00:00-07:00")
    save([other], folder, source="visit_seattle")
    rows = events.merged_events(FIRST, LAST, now=NOW, folder=folder)
    assert len(rows) == 1
    assert rows[0]["ends_at"].endswith("21:00:00-07:00")
    assert len(rows[0]["receipts"]) == 2
    assert rows[0]["conflicts"] == ["Sources disagree on ends at"]


def test_same_named_events_different_venues_or_sessions_stay_separate(folder):
    later = event(key="second-session", starts_at="2026-09-19T22:00:00-07:00", ends_at="2026-09-19T23:00:00-07:00")
    elsewhere = event(key="elsewhere", venue="Another Hall", venue_key="anotherhall")
    save([event(), later, elsewhere], folder)
    assert len(events.catalog(now=NOW, folder=folder)["events"]) == 3


def test_unknown_hours_are_null_in_catalog_and_explicit_in_awareness(folder):
    save([event(starts_at=None, ends_at=None)], folder)
    assert events.catalog(now=NOW, folder=folder)["events"][0]["ends_at"] is None
    signals = events.event_signals(NOW, NOW + timedelta(hours=6), now=NOW, folder=folder)
    view = build_view({"signals": [asdict(row) for row in signals]}, now=NOW)
    row = view["observations"][0]
    assert row["date_only"] and row["end_unknown"]
    assert row["timing_label"] == "Hours unconfirmed"
    assert row["state"] == "date confirmed; hours unknown"


def test_community_calendar_never_manufactures_pickup_score_or_confidence(folder):
    save([event()], folder)
    signals = events.event_signals(NOW, NOW + timedelta(hours=6), now=NOW, folder=folder)
    assert signals and _signal_value(replace(signals[0], magnitude=50000)) == 0
    assert _confidence(signals) == _confidence([])
    result = score_window(current=NOW, hours=6, vehicle_cost_per_mile=.45,
                          origin_zone="seattle_center", origin_lat=47.622, origin_lon=-122.354,
                          snapshot=ScoringSnapshot(signals, [], [], {}))
    assert not result["opportunities"]


def test_nearby_uses_venue_pin_and_omits_unmapped_events(folder):
    save([event(lat=47.5619, lon=-122.3868, location_precision="venue"),
          event(key="unknown", lat=None, lon=None, zone=None)], folder)
    rows = events.event_signals(NOW, NOW + timedelta(hours=6), now=NOW, folder=folder)
    snap = {"signals": [asdict(row) for row in rows]}
    nearby = build_view(snap, now=NOW, scope="nearby", latitude=47.5619, longitude=-122.3868, radius=.1)
    assert len(nearby["observations"]) == 1
    assert nearby["observations"][0]["distance_miles"] == 0
    assert "_position" not in json.dumps(nearby)
    assert len(build_view(snap, now=NOW, scope="metro")["observations"]) == 2


def test_event_and_source_links_are_required_to_be_http():
    with pytest.raises(ValueError):
        events.validate(event(source_url="javascript:alert(1)"))
    assert events.validate(event(organizer_url="javascript:alert(1)"))["organizer_url"] is None


def test_local_reads_and_api_never_start_crawler(folder, monkeypatch):
    today = datetime.now(events.PACIFIC).date()
    today_event = occurrence(
        "seattle_center",
        "festival:today",
        "Neighborhood Festival",
        today,
        "https://www.seattlecenter.com/example",
        venue="Seattle Center",
        hours=(time(12), time(21)),
        category="festival",
    )
    events.store_source(
        "seattle_center",
        [today_event],
        now=datetime.now(events.PACIFIC),
        first=today,
        last=today + timedelta(days=13),
        folder=folder,
    )
    monkeypatch.setattr(Fetcher, "__call__", lambda *args: pytest.fail("read triggered a crawl"))
    with TestClient(app) as client:
        response = client.get("/api/events")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json()["events"]
        assert client.get("/api/events?days=99").status_code == 400


def test_festival_daily_hours_do_not_bleed_into_next_day():
    item = {"title": "Sea Mar Fiestas Patrias", "first": FIRST, "last": date(2026, 9, 20),
            "url": "https://www.seattlecenter.com/festival", "evidence": "September 19-20, 2026"}
    html = "<p>Sea Mar Fiestas Patrias is September 19: 12pm-9pm &amp; September 20: 11am-6pm in the Armory.</p>"
    rows = festal_detail(item, html, FIRST, LAST)
    assert [row["ends_at"][11:16] for row in rows] == ["21:00", "18:00"]
    assert [row["starts_at"][11:16] for row in rows] == ["12:00", "11:00"]


def test_missing_second_day_hours_are_not_copied():
    item = {"title": "Sample Festival", "first": FIRST, "last": date(2026, 9, 20),
            "url": "https://www.seattlecenter.com/festival", "evidence": "September 19-20, 2026"}
    rows = festal_detail(item, "<p>Sample Festival is September 19: 12pm-9pm. Sunday hours pending.</p>", FIRST, LAST)
    assert rows[1]["starts_at"] is None and rows[1]["ends_at"] is None


def test_market_weekday_changes_at_season_boundary():
    html = """<main>Lake City THURSDAYS, 3 to 7 PM June 4 - Sept 24, 2026
    SATURDAYS, 10 AM TO 2 PM Oct 3 - Dec 19, 2026 Market Events</main>"""
    rows = market_events("lcfm", html, FIRST, date(2026, 10, 10))
    assert [(row["local_date"], row["starts_at"][11:16]) for row in rows] == [
        ("2026-09-24", "15:00"), ("2026-10-03", "10:00"), ("2026-10-10", "10:00")]


def test_year_round_market_tracks_pacific_dst():
    html = "<main>West Seattle SUNDAYS 10 AM - 2 PM Year-round Market Events</main>"
    rows = market_events("wsfm", html, date(2026, 10, 25), date(2026, 11, 1))
    assert rows[0]["starts_at"].endswith("-07:00")
    assert rows[1]["starts_at"].endswith("-08:00")


def test_market_map_uses_venue_pin_not_camera_center():
    html = '<main>West Seattle SUNDAYS 10 AM - 2 PM Year-round Market Events <a href="https://www.google.com/maps/@47.62,-122.3,12z/data=!3d47.5619!4d-122.3868">Directions</a></main>'
    row = market_events("wsfm", html, FIRST, LAST)[0]
    assert (row["lat"], row["lon"]) == (47.5619, -122.3868)


def test_farmers_market_season_without_year_requires_matching_weekday():
    html = "<main>Phinney FRIDAYS 3pm to 7pm June 5 - September 25 Market Events</main>"
    with pytest.raises(ParseError, match="year"):
        market_events("pfm", html, date(2027, 9, 19), date(2027, 10, 2))


@pytest.mark.parametrize("parser,args", [
    (festal_index, ("<h1>Temporarily unavailable</h1>", FIRST, LAST)),
    (market_events, ("wsfm", "<main>West Seattle error</main>", FIRST, LAST)),
    (trumba_events, ({"error": "unavailable"}, FIRST, LAST)),
])
def test_source_layout_failures_are_not_silent_empty_calendars(parser, args):
    with pytest.raises(ParseError):
        parser(*args)


def test_calendar_date_not_news_publication_date():
    html = """<script>{"datePublished":"2025-01-01"}</script><div class="container-event-detail">
    <h1>Tea Festival</h1><h4>September 26-27, 2026 | Seattle Center</h4>
    <p>Festival details.</p></div>"""
    rows = visit_detail("https://visitseattle.org/events/tea/", html, FIRST, LAST)
    assert [row["local_date"] for row in rows] == ["2026-09-26", "2026-09-27"]
    assert all(row["ends_at"] is None for row in rows)


def test_outside_seattle_and_permanent_ongoing_attractions_are_not_invented_events():
    for name, when, venue in [("Festival", "September 19, 2026", "Bellevue Downtown Park"),
                              ("Explore The Market", "Ongoing", "Pike Place Market")]:
        html = f'<div class="container-event-detail"><h1>{name}</h1><h4>{when} | {venue}</h4></div>'
        assert visit_detail("https://visitseattle.org/events/example/", html, FIRST, LAST) == []


def test_venue_location_wins_over_broad_neighborhood_tags():
    place = location("Kangaroo & Kiwi, Ballard", "Ballard, Fremont, Greenwood/Phinney Ridge")
    assert place["zone"] == "fremont_ballard"
    assert place["neighborhood"] == "Ballard"


def test_parser_handles_multi_month_range_without_guessing_year():
    assert date_span("October 31 - November 1, 2026") == (date(2026, 10, 31), date(2026, 11, 1))
    assert date_span("September 19-20") is None


def test_source_failure_does_not_prevent_other_sources_or_overwrite_weekly(folder, monkeypatch):
    from farol import event_sources
    def fake(source, *_):
        if source == "visit_seattle":
            raise RuntimeError("outage")
        return [event(source, key=source)], []
    monkeypatch.setattr(event_sources, "collect_source", fake)
    report = run(now=NOW, folder=folder, fetch=lambda _: "")
    assert report["state"] == "partial"
    assert len(events.records(FIRST, LAST, folder=folder)) == len(events.SOURCES) - 1
    assert not list((folder / "weekly").glob("*.json"))
    monkeypatch.setattr(event_sources, "collect_source", lambda source, *_: ([event(source, key=source)], []))
    run(now=NOW + timedelta(hours=1), folder=folder, fetch=lambda _: "")
    weekly = next((folder / "weekly").glob("*.json"))
    baseline = weekly.read_bytes()
    run(now=NOW + timedelta(hours=2), folder=folder, fetch=lambda _: "")
    assert weekly.read_bytes() == baseline


def test_os_lock_prevents_overlapping_collections(folder):
    with collection_lock(folder) as acquired:
        assert acquired
        assert run(now=NOW, folder=folder)["state"] == "already_running"


@pytest.mark.parametrize("url", ["http://visitseattle.org/", "https://127.0.0.1/", "https://visitseattle.org.evil.test/", "https://user:pass@visitseattle.org/", "https://visitseattle.org:9999/"])
def test_crawler_cannot_follow_arbitrary_or_private_urls(url):
    with pytest.raises(ValueError):
        checked_url(url)


def test_conditional_304_reuses_body_and_outage_does_not_masquerade_as_success(folder, monkeypatch):
    fetch = Fetcher(folder)
    url = "https://visitseattle.org/events/example/"
    calls = []
    def get(target, headers=None):
        calls.append((target, headers))
        if target.endswith("robots.txt"):
            return "User-agent: *\nAllow: /", {}
        if len(calls) == 2:
            return "<h1>Festival</h1>", {"ETag": "version-1"}
        raise HTTPError(target, 304, "Not modified", {}, BytesIO())
    monkeypatch.setattr(fetch, "_get", get)
    assert fetch(url) == fetch(url) == "<h1>Festival</h1>"
    assert calls[-1][1]["If-None-Match"] == "version-1"
    assert fetch.cache_hits == 1
    monkeypatch.setattr(fetch, "_get", lambda *_: (_ for _ in ()).throw(RuntimeError("unavailable")))
    with pytest.raises(RuntimeError):
        fetch(url)
