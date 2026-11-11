"""Published Redmond events stay in their actual day and local radius."""
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from farol import community_events as events
from farol.awareness import build_view
from farol.event_sources import ParseError
from farol.redmond_events import city_events, collect_redmond_source, park_events, redmond_location

FIRST, LAST = date(2026, 9, 19), date(2026, 10, 2)
NOW = datetime(2026, 9, 19, 12, tzinfo=events.PACIFIC)


def park(**updates):
    item = {":id": "row-ganesh", "event_name": "Community Event: Genesh Festival 2026 - Marymoor Park",
            "start_time": "2026-09-18T17:00:00.000", "end_time": "2026-09-19T17:13:00.000",
            "event_description_details": "<p>Join us September 18 -20th at Marymoor Park</p>",
            "location_name": "Marymoor Park", "location_city": "Redmond", "location_state": "WA",
            "location_address": "6046 West Lake Sammamish Parkway Northeast",
            "location": {"type": "Point", "coordinates": [-122.12658, 47.66261]},
            "url": "https://example.org/festival"}
    return dict(item, **updates)


def city_html(title="Community gathering", when="September 26, 2026, 12:00 PM - 5:00 PM",
              start="2026-09-26T12:00:00", city="Redmond", venue="Redmond Community Center at Marymoor Village"):
    return f'''<input name="chkCalendarID" value="22"><li>
    <h3><a href="/Calendar.aspx?EID=3536&amp;day=19">{title}</a></h3>
    <div class="date">{when}</div><div itemscope itemtype="http://schema.org/Event">
    <span itemprop="name">{title}</span><span itemprop="startDate">{start}</span>
    <span itemprop="location"><span itemprop="name">{venue}</span>
    <span itemprop="addressLocality">{city}</span><span itemprop="streetAddress">6505 176th Ave NE</span>
    </span></div></li>'''


def save(rows, folder, source="king_county_parks"):
    events.store_source(source, rows, now=NOW, first=FIRST, last=LAST, folder=folder)


def test_park_description_extends_conflicting_dates_without_inventing_hours():
    rows = park_events([park()], FIRST, LAST)
    assert [r["local_date"] for r in rows] == ["2026-09-19", "2026-09-20"]
    for row in rows:
        checked = events.validate(row)
        assert checked["schedule_warnings"]
        assert checked["starts_at"] is None and checked["ends_at"] is None
        assert checked["zone"] == "marymoor" and checked["city"] == "Redmond"
        assert checked["neighborhood"] == "Marymoor Park · Redmond"
        assert checked["location_precision"] == "venue"
        assert checked["lat"] == 47.66261 and checked["lon"] == -122.12658


@pytest.mark.parametrize("area,expected", [("redmond_downtown", True), ("marymoor", True),
                                           ("seattle_core", False), ("seattle_center", False)])
def test_redmond_event_only_appears_within_nearby_radius(tmp_path, area, expected):
    save(park_events([park()], FIRST, LAST), tmp_path)
    signals = events.event_signals(NOW, NOW + timedelta(days=7), now=NOW, folder=tmp_path)
    snap = {"signals": [asdict(row) for row in signals]}
    view = build_view(snap, now=NOW, scope="nearby", area=area, period="all")
    assert bool(view["observations"]) is expected
    if expected:
        assert {r["local_date"] for r in view["observations"]} == {"2026-09-19"}
        assert all(r["distance_miles"] <= 5 for r in view["observations"])
        assert view["observations"][0]["conflicts"]
        assert view["observations"][0]["location_label"] == "Marymoor Park · Redmond"
    assert len(build_view(snap, now=NOW, scope="metro", period="week")["observations"]) == 2


def test_gps_pin_filters_independently_of_selected_area_and_expired_day(tmp_path):
    save(park_events([park()], FIRST, LAST), tmp_path)
    signals = events.event_signals(NOW, NOW + timedelta(days=7), now=NOW, folder=tmp_path)
    snap = {"signals": [asdict(row) for row in signals]}
    local = build_view(snap, now=NOW, scope="nearby", area="seattle_core", radius=.1,
                       latitude=47.66261, longitude=-122.12658)
    assert len(local["observations"]) == 1
    assert not build_view(snap, now=NOW, scope="nearby", area="redmond_downtown",
                          latitude=47.6062, longitude=-122.3321)["observations"]
    sunday = build_view(snap, now=NOW + timedelta(days=1), scope="nearby", area="redmond_downtown")
    assert {r["local_date"] for r in sunday["observations"]} == {"2026-09-20"}
    assert not build_view(snap, now=NOW + timedelta(days=2), scope="metro", period="week")["observations"]


def test_two_daily_park_listings_keep_their_different_published_hours():
    rows = park_events([
        park(**{":id": "sat", "event_name": "Smoke on the Sound", "start_time": "2026-09-26T09:00:00",
                "end_time": "2026-09-26T20:00:00", "event_description_details": "September 26th and 27th 2026"}),
        park(**{":id": "sun", "event_name": "Smoke on the Sound", "start_time": "2026-09-27T11:00:00",
                "end_time": "2026-09-27T18:00:00", "event_description_details": "September 26th and 27th 2026"})], FIRST, LAST)
    assert len(rows) == 2
    assert rows[0]["ends_at"] == "2026-09-26T20:00:00-07:00"
    assert rows[1]["ends_at"] == "2026-09-27T18:00:00-07:00"


def test_other_county_venues_and_unlocated_events_do_not_become_redmond():
    assert not park_events([park(location_city="Carnation"), park(location_name="")], FIRST, LAST)
    assert not city_events(city_html(city="Bellevue"), FIRST, LAST)
    assert redmond_location("Event Location")["location_precision"] == "unknown"


def test_city_uses_event_date_not_calendar_link_day_and_distinguishes_marymoor_village():
    row = city_events(city_html(), FIRST, LAST)[0]
    assert row["local_date"] == "2026-09-26"  # Link day=19 is the selected calendar day.
    assert row["ends_at"] == "2026-09-26T17:00:00-07:00"
    assert row["zone"] == "redmond_downtown" and row["location_precision"] == "area"
    assert row["neighborhood"] == "Redmond"
    assert row["venue_key"] != "marymoorpark"


def test_city_missing_end_or_disagreeing_hours_are_not_guessed():
    missing = city_events(city_html(when="September 26, 2026, 12:00 PM"), FIRST, LAST)[0]
    assert missing["starts_at"] == "2026-09-26T12:00:00-07:00" and missing["ends_at"] is None
    conflict = city_events(city_html(start="2026-09-26T14:00:00"), FIRST, LAST)[0]
    assert conflict["schedule_warnings"] and conflict["starts_at"] is None


def test_explicit_cancellation_is_stored_but_not_active(tmp_path):
    rows = city_events(city_html(title="CANCELED: Community gathering"), FIRST, LAST)
    save(rows, tmp_path, "redmond_city")
    assert events.catalog(now=NOW, folder=tmp_path)["events"][0]["status"] == "canceled"
    assert not events.event_signals(NOW, NOW + timedelta(days=10), now=NOW, folder=tmp_path)


def test_bad_city_layout_fails_but_real_empty_calendar_is_allowed():
    with pytest.raises(ParseError):
        city_events("<h1>Service temporarily unavailable</h1>", FIRST, LAST)
    assert city_events('<input name="chkCalendarID" value="22">', FIRST, LAST) == []


def test_repeat_category_dedup_and_month_boundary_fetch_are_bounded():
    calls = []
    def fetch(url):
        calls.append(parse_qs(urlsplit(url).query))
        return city_html()
    rows, errors = collect_redmond_source("redmond_city", fetch, FIRST, LAST)
    assert not errors and len(rows) == 1 and len(calls) == 4
    assert {q["month"][0] for q in calls} == {"9", "10"}
    assert {q["CID"][0] for q in calls} == {"22", "39"}


def test_park_collection_looks_back_for_ongoing_events_and_includes_source_ids():
    calls = []
    def fetch(url):
        calls.append(parse_qs(urlsplit(url).query))
        return json.dumps([park()])
    rows, errors = collect_redmond_source("king_county_parks", fetch, FIRST, LAST)
    assert not errors and len(rows) == 2
    assert "2026-08-19" in calls[0]["$where"][0]
    assert calls[0]["$select"][0].startswith(":id,")


def test_coordinate_validation_respects_event_city_and_warning_history(tmp_path):
    row = park_events([park()], FIRST, LAST)[0]
    with pytest.raises(ValueError):
        events.validate(dict(row, lat=47.62, lon=-122.35))
    save([row], tmp_path)
    first = events.catalog(now=NOW, folder=tmp_path)["events"][0]
    assert first["conflicts"]
    changed = dict(row, schedule_warnings=[], starts_at="2026-09-19T11:00:00-07:00",
                   ends_at="2026-09-19T21:30:00-07:00")
    save([changed], tmp_path)
    assert not events.catalog(now=NOW, folder=tmp_path)["events"][0]["conflicts"]


def test_same_named_event_at_city_hall_in_different_cities_never_merges(tmp_path):
    redmond = city_events(city_html(title="Community Day", venue="City Hall"), FIRST, LAST)[0]
    save([redmond], tmp_path, "redmond_city")
    seattle = dict(redmond, source_id="neighborhoods", source_key="seattle-city-day", city="Seattle",
                   zone="seattle_core", lat=47.6062, lon=-122.3321,
                   source_url="https://www.seattle.gov/neighborhoods/event-calendar")
    save([seattle], tmp_path, "neighborhoods")
    assert {r["city"] for r in events.catalog(now=NOW, folder=tmp_path)["events"]} == {"Seattle", "Redmond"}
