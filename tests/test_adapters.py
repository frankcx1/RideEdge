import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from farol.adapters import (
    base,
    eastside,
    espn_seattle,
    gather_signals,
    grok_research,
    grok_watch,
    mlb,
    nhl,
    nws,
    onebusaway,
    flightaware,
    openclaw,
    places,
    routes,
    seattle_events,
    seatgeek,
    ticketmaster,
    venues,
    wsdot,
)
from farol.adapters.base import FeedError, fetch_json
from farol.dashboard import FIXTURES
from farol.signals import FixtureSignalAdapter, Signal

FEEDS = FIXTURES / "feeds"
FETCHED = "2026-08-20T19:00:00+00:00"


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _load(name: str):
    return json.loads((FEEDS / name).read_text(encoding="utf-8"))


def _signal(**overrides) -> Signal:
    values = {
        "id": "test-signal",
        "kind": "event_exit",
        "zone": "sodo_stadiums",
        "starts_at": "2026-08-21T21:55:00+00:00",
        "ends_at": "2026-08-21T22:55:00+00:00",
        "magnitude": 30000.0,
        "basis": "scheduled",
        "source": "test",
        "fetched_at": FETCHED,
        "expires_at": "2026-08-22T00:00:00+00:00",
        "evidence_quality": 0.75,
        "details": {"title": "Test signal"},
    }
    values.update(overrides)
    return Signal(**values)


class NwsParseTests(unittest.TestCase):
    def test_dry_forecast_produces_no_signals(self):
        payload = _load("nws_hourly_sample.json")
        first = payload["properties"]["periods"][0]["startTime"]
        signals = nws.parse(
            payload, _at(first), _at(first) + timedelta(hours=12), fetched_at=FETCHED
        )
        self.assertEqual(signals, [])

    def test_consecutive_wet_hours_merge_into_one_signal_with_peak(self):
        def period(hour: int, probability: int) -> dict:
            starts = _at("2026-08-21T00:00:00-07:00") + timedelta(hours=hour)
            return {
                "startTime": starts.isoformat(),
                "endTime": (starts + timedelta(hours=1)).isoformat(),
                "probabilityOfPrecipitation": {"value": probability},
            }

        payload = {
            "properties": {
                "updateTime": FETCHED,
                "periods": [period(20, 10), period(21, 45), period(22, 70), period(23, 55)],
            }
        }
        signals = nws.parse(
            payload,
            _at("2026-08-21T20:00:00-07:00"),
            _at("2026-08-22T02:00:00-07:00"),
            fetched_at=FETCHED,
        )
        self.assertEqual(len(signals), 1)
        rain = signals[0]
        self.assertEqual(rain.kind, "precipitation")
        self.assertEqual(rain.basis, "live")
        self.assertEqual(rain.magnitude, 70)
        self.assertEqual(rain.starts_at, "2026-08-21T21:00:00-07:00")
        self.assertEqual(rain.ends_at, "2026-08-22T00:00:00-07:00")

    def test_wet_hours_outside_window_are_ignored(self):
        payload = {
            "properties": {
                "updateTime": FETCHED,
                "periods": [
                    {
                        "startTime": "2026-08-22T09:00:00-07:00",
                        "endTime": "2026-08-22T10:00:00-07:00",
                        "probabilityOfPrecipitation": {"value": 80},
                    }
                ],
            }
        }
        signals = nws.parse(
            payload,
            _at("2026-08-21T20:00:00-07:00"),
            _at("2026-08-22T02:00:00-07:00"),
            fetched_at=FETCHED,
        )
        self.assertEqual(signals, [])


class MlbParseTests(unittest.TestCase):
    def test_friday_home_game_becomes_sodo_exit_signal(self):
        payload = _load("mlb_schedule_sample.json")
        signals = mlb.parse(
            payload,
            _at("2026-08-21T18:00:00-07:00"),
            _at("2026-08-22T01:00:00-07:00"),
            fetched_at=FETCHED,
        )
        self.assertEqual(len(signals), 1)
        exit_wave = signals[0]
        self.assertEqual(exit_wave.kind, "event_exit")
        self.assertEqual(exit_wave.zone, "sodo_stadiums")
        self.assertEqual(exit_wave.basis, "scheduled")
        # 02:10Z first pitch + 2h45m assumed game
        self.assertEqual(_at(exit_wave.starts_at), _at("2026-08-22T04:55:00+00:00"))
        self.assertIn("assumed", exit_wave.details["attendance_basis"])

    def test_away_games_produce_no_signals(self):
        payload = _load("mlb_schedule_sample.json")
        signals = mlb.parse(
            payload,
            _at("2026-08-20T10:00:00-07:00"),
            _at("2026-08-20T23:00:00-07:00"),
            fetched_at=FETCHED,
        )
        self.assertEqual(signals, [])


class NhlParseTests(unittest.TestCase):
    def test_home_opener_becomes_seattle_center_exit_signal(self):
        payload = _load("nhl_schedule_sample.json")
        signals = nhl.parse(
            payload,
            _at("2026-09-19T17:00:00-07:00"),
            _at("2026-09-19T23:00:00-07:00"),
            fetched_at=FETCHED,
        )
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].zone, "seattle_center")
        # 01:00Z puck drop + 2h30m assumed game
        self.assertEqual(_at(signals[0].starts_at), _at("2026-09-20T03:30:00+00:00"))

    def test_season_code_rolls_over_in_july(self):
        self.assertEqual(nhl.season_code(_at("2026-08-20T00:00:00-07:00")), "20262027")
        self.assertEqual(nhl.season_code(_at("2026-03-01T00:00:00-08:00")), "20252026")


class SeattleEventsParseTests(unittest.TestCase):
    def test_permit_day_becomes_all_day_signal_in_mapped_zone(self):
        payload = _load("seattle_events_sample.json")
        signals = seattle_events.parse(
            payload,
            _at("2025-08-09T10:00:00-07:00"),
            _at("2025-08-09T23:00:00-07:00"),
            fetched_at=FETCHED,
        )
        self.assertEqual(len(signals), 1)
        block_party = signals[0]
        self.assertEqual(block_party.kind, "special_event")
        self.assertEqual(block_party.zone, "belltown")
        self.assertEqual(block_party.magnitude, 275.0)
        self.assertEqual(block_party.basis, "scheduled")
        self.assertIn("no time of day", block_party.details["timing_basis"])

    def test_neighborhood_zone_mapping(self):
        self.assertEqual(seattle_events.zone_for_neighborhood("Capitol Hill"), "capitol_hill")
        self.assertEqual(
            seattle_events.zone_for_neighborhood("Fremont;Wallingford"), "fremont_ballard"
        )
        self.assertEqual(seattle_events.zone_for_neighborhood("Queen Anne"), "seattle_center")
        self.assertEqual(seattle_events.zone_for_neighborhood("Alki / Admiral"), "alki")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FetchJsonCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.dict(os.environ, {"FAROL_CACHE_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_live_then_cache_then_stale_fallback(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request.full_url)
            return _FakeResponse({"value": len(calls)})

        with patch.object(base, "urlopen", fake_urlopen):
            payload, mode, _ = fetch_json("https://x.test/a", cache_key="t", ttl_seconds=3600)
            self.assertEqual((payload, mode, len(calls)), ({"value": 1}, "live", 1))
            payload, mode, _ = fetch_json("https://x.test/a", cache_key="t", ttl_seconds=3600)
            self.assertEqual((payload, mode, len(calls)), ({"value": 1}, "cache", 1))
            payload, mode, _ = fetch_json("https://x.test/a", cache_key="t", ttl_seconds=0)
            self.assertEqual((payload, mode, len(calls)), ({"value": 2}, "live", 2))

        def broken_urlopen(request, timeout):
            raise TimeoutError("network down")

        with patch.object(base, "urlopen", broken_urlopen):
            payload, mode, _ = fetch_json("https://x.test/a", cache_key="t", ttl_seconds=0)
            self.assertEqual((payload, mode), ({"value": 2}, "stale_cache"))
            with self.assertRaises(FeedError):
                fetch_json("https://x.test/b", cache_key="never_cached", ttl_seconds=0)


class GatherSignalsTests(unittest.TestCase):
    def test_mock_mode_serves_the_fixture_pipeline(self):
        start = _at("2026-08-14T20:00:00-07:00")
        end = start + timedelta(hours=6)
        with patch.dict(os.environ, {"MOCK_FEEDS": "1"}):
            signals, feeds = gather_signals(start, end)
        expected = FixtureSignalAdapter(FIXTURES / "tonight_signals.json").fetch(start, end)
        self.assertEqual(signals, expected)
        self.assertEqual(len(feeds), 1)
        self.assertEqual(feeds[0]["mode"], "fixture")

    def test_live_mode_isolates_a_failing_adapter_and_adds_doctrine(self):
        exit_signal = _signal()

        ok = SimpleNamespace(
            NAME="ok_feed",
            SOURCE="test:ok",
            fetch=lambda start, end: (
                [exit_signal],
                base.FeedStatus("ok_feed", "live", "test:ok", FETCHED, 1),
            ),
        )

        def boom(start, end):
            raise RuntimeError("adapter exploded")

        broken = SimpleNamespace(NAME="broken_feed", SOURCE="test:broken", fetch=boom)
        start = _at("2026-08-21T18:00:00-07:00")
        with (
            patch.dict(os.environ, {"MOCK_FEEDS": "0"}),
            patch("farol.adapters.ADAPTERS", [ok, broken]),
        ):
            signals, feeds = gather_signals(start, start + timedelta(hours=6))
        self.assertIn(exit_signal, signals)
        doctrine = [item for item in signals if item.kind == "doctrine_penalty"]
        self.assertEqual(len(doctrine), 1)
        self.assertEqual(doctrine[0].zone, "sodo_stadiums")
        by_adapter = {feed["adapter"]: feed for feed in feeds}
        self.assertEqual(by_adapter["broken_feed"]["mode"], "error")
        self.assertEqual(by_adapter["ok_feed"]["mode"], "live")

    def test_on_demand_adapter_is_idle_until_requested(self):
        called = []

        def fa_fetch(start, end, demand=False):
            called.append(demand)
            mode = "live" if demand else "static"
            return [], base.FeedStatus("flightaware_sea", mode, "test:fa", FETCHED, 0)

        fa = SimpleNamespace(NAME="flightaware_sea", SOURCE="test:fa", fetch=fa_fetch)
        start = _at("2026-08-14T11:00:00-07:00")
        with (
            patch.dict(os.environ, {"MOCK_FEEDS": "0"}),
            patch("farol.adapters.ADAPTERS", [fa]),
            patch("farol.adapters.ON_DEMAND_ADAPTERS", frozenset({"flightaware_sea"})),
        ):
            _, idle = gather_signals(start, start + timedelta(hours=4))
            _, live = gather_signals(
                start, start + timedelta(hours=4), include_on_demand=True
            )
        self.assertEqual(called, [False, True])
        self.assertEqual(idle[0]["mode"], "static")
        self.assertEqual(live[0]["mode"], "live")


class LiveBriefIntegrationTests(unittest.TestCase):
    def test_live_brief_uses_assumed_routes_and_reports_unanchored_zones(self):
        from farol.tonight import tonight_brief

        exit_signal = _signal()
        orphan = _signal(id="orphan", zone="issaquah", kind="special_event", magnitude=10000.0)
        feeds = [
            {
                "adapter": "ok_feed",
                "mode": "live",
                "source": "test:ok",
                "fetched_at": FETCHED,
                "signal_count": 2,
                "detail": "",
            }
        ]
        empty_routes = (
            {},
            base.FeedStatus("google_routes_traffic", "needs_key", "env:GOOGLE_MAPS_API_KEY", None, 0),
        )
        with (
            patch.dict(os.environ, {"MOCK_FEEDS": "0"}),
            patch("farol.tonight.gather_signals", return_value=([exit_signal, orphan], feeds)),
            patch("farol.adapters.routes.matrix", return_value=empty_routes),
        ):
            brief = tonight_brief(now=_at("2026-08-21T14:00:00-07:00"), hours=10)
        self.assertEqual(brief["mode"], "TONIGHT BRIEF · LIVE FEEDS")
        self.assertEqual(brief["feeds"][0], feeds[0])
        self.assertEqual(brief["feeds"][-1]["adapter"], "google_routes_traffic")
        self.assertEqual(brief["unanchored_zones"], ["issaquah"])
        self.assertEqual(len(brief["opportunities"]), 1)
        sodo = brief["opportunities"][0]
        self.assertEqual(sodo["zone"], "sodo_stadiums")
        self.assertEqual(sodo["route"]["basis"], "assumed")
        self.assertGreater(sodo["route"]["distance_miles"], 5)
        self.assertFalse(sodo["navigation_available"])


class ZoneRegistryTests(unittest.TestCase):
    def test_historical_kirkland_alias_maps_to_waterfront(self):
        from farol.zones import canonical_zone

        self.assertEqual(canonical_zone("kirkland_bar_strip"), "kirkland_waterfront")
        self.assertEqual(canonical_zone("SEA"), "sea_airport")
        self.assertEqual(canonical_zone("husky_stadium"), "uw_district")
        self.assertEqual(canonical_zone("capitol_hill"), "capitol_hill")


class VenueHoursTests(unittest.TestCase):
    def test_the_lime_harvest_covers_two_am_last_call(self):
        signals = venues.parse(
            _at("2026-08-14T20:00:00-07:00"),
            _at("2026-08-15T02:30:00-07:00"),
            fetched_at=FETCHED,
        )
        lime = next(item for item in signals if "the_lime" in item.id)
        self.assertEqual(lime.zone, "kirkland_rose_hill")
        self.assertEqual(lime.kind, "closing_wave")
        self.assertIn("The Lime", lime.details["title"])
        self.assertEqual(_at(lime.starts_at), _at("2026-08-15T01:15:00-07:00"))
        self.assertEqual(_at(lime.ends_at), _at("2026-08-15T02:30:00-07:00"))

    def test_eastside_last_call_catalog_covers_closer_zones(self):
        catalog = venues.load_venues()
        zones = {row["zone"] for row in catalog}
        self.assertGreaterEqual(len(catalog), 15)
        self.assertTrue(all(row.get("place_id") for row in catalog))
        self.assertTrue(
            {
                "kirkland_rose_hill",
                "kirkland_waterfront",
                "bellevue_core",
                "redmond_downtown",
                "woodinville_wine",
                "totem_lake",
            }.issubset(zones)
        )
        signals = venues.parse(
            _at("2026-08-14T20:00:00-07:00"),
            _at("2026-08-15T02:30:00-07:00"),
            fetched_at=FETCHED,
        )
        waterfront = [item for item in signals if item.zone == "kirkland_waterfront"]
        self.assertTrue(waterfront)
        self.assertTrue(any("Central Tavern" in item.details["title"] for item in waterfront))


class GooglePlacesHoursTests(unittest.TestCase):
    def test_google_periods_map_onto_friday_last_call(self):
        payload = _load("places_details_sample.json")
        closes = places.close_map_from_hours(payload)
        self.assertEqual(closes["fri"], "02:00")
        self.assertEqual(closes["sun"], "02:00")
        self.assertEqual(closes["sat"], "02:00")
        venue = {
            "id": "the_lime_kirkland",
            "name": "The Lime",
            "zone": "kirkland_rose_hill",
            "place_id": payload["id"],
            "harvest_minutes_before": 45,
            "harvest_minutes_after": 30,
            "magnitude": 6,
        }
        overlaid = places.overlay_venues([venue], {payload["id"]: payload})
        signals = venues.parse(
            _at("2026-08-14T20:00:00-07:00"),
            _at("2026-08-15T02:30:00-07:00"),
            fetched_at=FETCHED,
            venues=overlaid,
        )
        lime = signals[0]
        self.assertEqual(lime.source, places.SOURCE)
        self.assertEqual(lime.zone, "kirkland_rose_hill")
        self.assertEqual(_at(lime.starts_at), _at("2026-08-15T01:15:00-07:00"))

    def test_missing_maps_key_is_needs_key_without_network(self):
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}, clear=False):
            os.environ.pop("GOOGLE_MAPS_API_KEY", None)
            signals, status = places.fetch(
                _at("2026-08-14T20:00:00-07:00"),
                _at("2026-08-15T02:00:00-07:00"),
            )
        self.assertEqual(signals, [])
        self.assertEqual(status.mode, "needs_key")


class GoogleRoutesMatrixTests(unittest.TestCase):
    def test_parse_matrix_maps_duration_and_miles(self):
        payload = _load("routes_matrix_sample.json")
        anchors = [
            SimpleNamespace(id="bellevue_candidate_1", latitude=47.615, longitude=-122.201),
            SimpleNamespace(id="the_lime_kirkland", latitude=47.6794, longitude=-122.1813),
        ]
        parsed = routes.parse_matrix(
            payload,
            origin_zone="kirkland_rose_hill",
            anchors=anchors,
            vehicle_cost_per_mile=0.45,
            fetched_at=FETCHED,
        )
        bellevue = parsed["bellevue_candidate_1"]
        self.assertEqual(bellevue.basis, "live")
        self.assertEqual(bellevue.traffic_minutes, 15.0)
        self.assertEqual(bellevue.distance_miles, 6.0)
        self.assertEqual(parsed["the_lime_kirkland"].traffic_minutes, 6.0)

    def test_missing_maps_key_is_needs_key_without_network(self):
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}, clear=False):
            os.environ.pop("GOOGLE_MAPS_API_KEY", None)
            legs, status = routes.matrix(
                "kirkland_home",
                47.61,
                -122.33,
                [],
                0.45,
                FETCHED,
            )
        self.assertEqual(legs, {})
        self.assertEqual(status.mode, "needs_key")


class OpenClawDropTests(unittest.TestCase):
    def test_valid_drop_file_is_accepted_and_junk_is_ignored(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        payload = {
            "generated_at": FETCHED,
            "source": "openclaw",
            "signals": [
                {
                    "id": "openclaw-union-1",
                    "kind": "supply",
                    "zone": "all",
                    "starts_at": "2026-08-14T20:00:00-07:00",
                    "ends_at": "2026-08-15T02:00:00-07:00",
                    "magnitude": 0,
                    "basis": "assumed",
                    "source": "https://www.driversunionwa.org/",
                    "fetched_at": FETCHED,
                    "expires_at": "2026-08-15T02:00:00-07:00",
                    "evidence_quality": 0.4,
                    "details": {"title": "Union saturation note", "notes": "quoted"},
                },
                {"id": "bad", "kind": "not_a_kind"},
            ],
        }
        with TemporaryDirectory() as folder:
            path = Path(folder) / "openclaw.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            signals = openclaw.parse_file(
                path,
                _at("2026-08-14T20:00:00-07:00"),
                _at("2026-08-15T02:00:00-07:00"),
            )
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].kind, "driver_intel")
        self.assertIn("driversunionwa", signals[0].source)


class EastsideDoctrineTests(unittest.TestCase):
    def test_friday_evening_emits_the_close_cascade(self):
        signals = eastside.parse(
            _at("2026-08-14T20:00:00-07:00"),
            _at("2026-08-15T02:00:00-07:00"),
            fetched_at=FETCHED,
        )
        zones = {item.zone for item in signals}
        self.assertEqual(
            zones,
            {"redmond_downtown", "bellevue_core", "woodinville_wine", "kirkland_waterfront"},
        )
        self.assertTrue(all(item.kind == "closing_wave" for item in signals))
        self.assertTrue(all(item.basis == "assumed" for item in signals))

    def test_tuesday_morning_emits_sea_arrival_window(self):
        signals = eastside.parse(
            _at("2026-08-11T05:00:00-07:00"),
            _at("2026-08-11T10:00:00-07:00"),
            fetched_at=FETCHED,
        )
        airports = [item for item in signals if item.kind == "airport_arrivals"]
        self.assertEqual(len(airports), 1)
        self.assertEqual(airports[0].zone, "sea_airport")

    def test_wednesday_morning_has_no_airport_doctrine(self):
        signals = eastside.parse(
            _at("2026-08-12T05:00:00-07:00"),
            _at("2026-08-12T10:00:00-07:00"),
            fetched_at=FETCHED,
        )
        self.assertFalse(any(item.kind == "airport_arrivals" for item in signals))


class EspnParseTests(unittest.TestCase):
    def test_home_seahawks_game_becomes_sodo_exit(self):
        payload = _load("espn_nfl_sample.json")
        league = espn_seattle.LEAGUES[0]
        signals = espn_seattle.parse(
            payload,
            _at("2026-08-14T18:00:00-07:00"),
            _at("2026-08-15T01:00:00-07:00"),
            fetched_at=FETCHED,
            league=league,
        )
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].zone, "sodo_stadiums")
        self.assertEqual(signals[0].kind, "event_exit")
        self.assertIn("Broncos", signals[0].details["title"])

    def test_huskies_home_apple_cup_is_uw_district_exit(self):
        payload = _load("espn_ncaaf_sample.json")
        league = next(item for item in espn_seattle.LEAGUES if item["sport"] == "ncaaf")
        signals = espn_seattle.parse(
            payload,
            _at("2026-09-06T16:00:00-07:00"),
            _at("2026-09-06T18:00:00-07:00"),
            fetched_at=FETCHED,
            league=league,
        )
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].zone, "uw_district")
        self.assertEqual(signals[0].kind, "event_exit")
        self.assertIn("Cougars", signals[0].details["title"])
        self.assertIn("Husky Stadium", signals[0].details["title"])

    def test_huskies_away_at_martin_stadium_is_ignored(self):
        payload = _load("espn_ncaaf_sample.json")
        league = next(item for item in espn_seattle.LEAGUES if item["sport"] == "ncaaf")
        # Same kickoff, but parse still requires Husky Stadium as home venue.
        signals = espn_seattle.parse(
            {
                "events": [
                    event
                    for event in payload["events"]
                    if "Martin" in ((event["competitions"][0].get("venue") or {}).get("fullName") or "")
                ]
            },
            _at("2026-09-06T16:00:00-07:00"),
            _at("2026-09-06T18:00:00-07:00"),
            fetched_at=FETCHED,
            league=league,
        )
        self.assertEqual(signals, [])

    def test_away_games_are_ignored(self):
        payload = _load("espn_nfl_sample.json")
        league = espn_seattle.LEAGUES[0]
        # Window covering only the Levi's Stadium kickoff.
        signals = espn_seattle.parse(
            payload,
            _at("2026-08-14T16:00:00-07:00"),
            _at("2026-08-14T18:30:00-07:00"),
            fetched_at=FETCHED,
            league=league,
        )
        self.assertEqual(signals, [])


class TicketmasterParseTests(unittest.TestCase):
    def test_concerts_map_and_sports_plus_unknown_venues_are_skipped(self):
        payload = _load("ticketmaster_sample.json")
        signals, skipped = ticketmaster.parse(
            payload,
            _at("2026-08-14T20:00:00-07:00"),
            _at("2026-08-15T02:00:00-07:00"),
            fetched_at=FETCHED,
        )
        zones = {item.zone for item in signals}
        titles = {item.details["title"] for item in signals}
        self.assertEqual(zones, {"seattle_center", "marymoor"})
        self.assertTrue(any("Phoebe Bridgers" in title for title in titles))
        self.assertTrue(any("Marymoor" in title for title in titles))
        self.assertFalse(any("Huskies" in title for title in titles))
        self.assertFalse(any("Tacoma" in title for title in titles))
        self.assertFalse(any("Ballpark Tour" in title for title in titles))
        self.assertEqual(skipped, 2)
        self.assertTrue(all(item.kind == "event_exit" for item in signals))
        self.assertTrue(all(item.basis == "scheduled" for item in signals))

    def test_arena_tours_and_access_passes_are_skipped(self):
        payload = {
            "_embedded": {
                "events": [
                    {
                        "id": "tour1",
                        "name": "All Access Pass – Climate Pledge Arena Tours",
                        "dates": {"start": {"dateTime": "2026-08-15T03:00:00Z"}},
                        "classifications": [{"segment": {"name": "Miscellaneous"}}],
                        "_embedded": {
                            "venues": [{"id": "KovZ917Ahkk", "name": "Climate Pledge Arena"}]
                        },
                    },
                    {
                        "id": "access1",
                        "name": "WAMU Theater Amplified Access: Role Model (Not an Event Ticket)",
                        "dates": {"start": {"dateTime": "2026-08-15T04:00:00Z"}},
                        "classifications": [{"segment": {"name": "Music"}}],
                        "_embedded": {"venues": [{"name": "WAMU Theater"}]},
                    },
                ]
            }
        }
        signals, skipped = ticketmaster.parse(
            payload,
            _at("2026-08-14T20:00:00-07:00"),
            _at("2026-08-15T02:00:00-07:00"),
            fetched_at=FETCHED,
        )
        self.assertEqual(signals, [])
        self.assertEqual(skipped, 2)

    def test_marymoor_split_listings_collapse_to_one_exit(self):
        payload = {
            "_embedded": {
                "events": [
                    {
                        "id": "mm1",
                        "name": "CMF Presents: Base Camp Featuring Squeeze",
                        "dates": {"start": {"dateTime": "2026-08-15T00:00:00Z"}},
                        "classifications": [{"segment": {"name": "Music"}}],
                        "_embedded": {"venues": [{"id": "KovZpZA1JAkA", "name": "Marymoor Park"}]},
                    },
                    {
                        "id": "mm2",
                        "name": "SQUEEZE - TRIED, TESTED AND TRIXIES w/ Adam Ant",
                        "dates": {"start": {"dateTime": "2026-08-15T01:30:00Z"}},
                        "classifications": [{"segment": {"name": "Music"}}],
                        "_embedded": {
                            "venues": [{"id": "KovZpa3qwe", "name": "Marymoor Live - Presented By Toyota"}]
                        },
                    },
                ]
            }
        }
        signals, skipped = ticketmaster.parse(
            payload,
            _at("2026-08-14T20:00:00-07:00"),
            _at("2026-08-15T04:00:00-07:00"),
            fetched_at=FETCHED,
        )
        self.assertEqual(len(signals), 1)
        self.assertEqual(skipped, 1)
        self.assertIn("SQUEEZE", signals[0].details["title"])

    def test_fetch_merges_priority_venues_and_dma(self):
        payload = _load("ticketmaster_sample.json")
        with (
            patch.dict(os.environ, {"TICKETMASTER_API_KEY": "test-key"}),
            patch(
                "farol.adapters.ticketmaster.fetch_json",
                side_effect=[
                    (payload, "live", FETCHED),
                    ({"_embedded": {"events": []}, "page": {"totalElements": 0}}, "live", FETCHED),
                    ({"_embedded": {"events": []}, "page": {"totalElements": 0}}, "live", FETCHED),
                    ({"_embedded": {"events": []}, "page": {"totalElements": 0}}, "live", FETCHED),
                    ({"_embedded": {"events": []}, "page": {"totalElements": 0}}, "live", FETCHED),
                ],
            ),
        ):
            signals, status = ticketmaster.fetch(
                _at("2026-08-14T20:00:00-07:00"),
                _at("2026-08-15T02:00:00-07:00"),
            )
        self.assertEqual(status.mode, "live")
        self.assertIn("venues0=", status.detail)
        self.assertTrue(any("Phoebe Bridgers" in item.details["title"] for item in signals))

    def test_missing_key_is_needs_key_without_network(self):
        with patch.dict(os.environ, {"TICKETMASTER_API_KEY": ""}, clear=False):
            os.environ.pop("TICKETMASTER_API_KEY", None)
            signals, status = ticketmaster.fetch(
                _at("2026-08-14T20:00:00-07:00"),
                _at("2026-08-15T02:00:00-07:00"),
            )
        self.assertEqual(signals, [])
        self.assertEqual(status.mode, "needs_key")


class SeatGeekParseTests(unittest.TestCase):
    def test_concerts_map_and_sports_and_tours_are_skipped(self):
        payload = _load("seatgeek_sample.json")
        signals, skipped = seatgeek.parse(
            payload,
            _at("2026-08-14T20:00:00-07:00"),
            _at("2026-08-15T02:00:00-07:00"),
            fetched_at=FETCHED,
        )
        self.assertEqual(len(signals), 1)
        self.assertEqual(skipped, 2)
        self.assertEqual(signals[0].zone, "seattle_center")
        self.assertIn("Phoebe Bridgers", signals[0].details["title"])
        self.assertEqual(signals[0].details["listing_count"], 42)
        self.assertTrue(all(item.kind == "event_exit" for item in signals))

    def test_missing_key_is_needs_key_without_network(self):
        with patch.dict(os.environ, {"SEATGEEK_CLIENT_ID": ""}, clear=False):
            os.environ.pop("SEATGEEK_CLIENT_ID", None)
            signals, status = seatgeek.fetch(
                _at("2026-08-14T20:00:00-07:00"),
                _at("2026-08-15T02:00:00-07:00"),
            )
        self.assertEqual(signals, [])
        self.assertEqual(status.mode, "needs_key")


class WsdotParseTests(unittest.TestCase):
    def test_keeps_405_kirkland_ramps_and_drops_moses_lake_i90(self):
        payload = _load("wsdot_alerts_sample.json")
        signals = wsdot.parse_alerts(
            payload,
            _at("2026-08-14T20:00:00-07:00"),
            _at("2026-08-15T02:00:00-07:00"),
            fetched_at=FETCHED,
        )
        roads = {item.details["road"] for item in signals}
        self.assertEqual(roads, {"I-405"})
        self.assertTrue(any(item.zone == "kirkland_rose_hill" for item in signals))
        self.assertTrue(all(item.kind == "highway_alert" for item in signals))
        self.assertTrue(all(item.basis == "live" for item in signals))

    def test_travel_delay_only_when_current_exceeds_average(self):
        payload = _load("wsdot_times_sample.json")
        signals = wsdot.parse_times(
            payload,
            _at("2026-08-14T20:00:00-07:00"),
            _at("2026-08-15T02:00:00-07:00"),
            fetched_at=FETCHED,
        )
        routes = {item.details["route"] for item in signals}
        self.assertEqual(routes, {"Seattle-Bellevue via 520"})
        self.assertEqual({item.zone for item in signals}, {"seattle_center", "bellevue_core"})
        self.assertTrue(all(item.kind == "travel_delay" for item in signals))

    def test_missing_key_is_needs_key_without_network(self):
        with patch.dict(os.environ, {"WSDOT_API_KEY": ""}, clear=False):
            os.environ.pop("WSDOT_API_KEY", None)
            signals, status = wsdot.fetch(
                _at("2026-08-14T20:00:00-07:00"),
                _at("2026-08-15T02:00:00-07:00"),
            )
        self.assertEqual(signals, [])
        self.assertEqual(status.mode, "needs_key")


class OneBusAwayParseTests(unittest.TestCase):
    def test_link_bus_bridge_hits_stadium_zones_and_skips_crowding(self):
        payload = _load("onebusaway_st40_sample.json")
        start = datetime.fromtimestamp(1788699600000 / 1000).astimezone()
        end = start + timedelta(hours=8)
        signals = onebusaway.parse(payload, start, end, fetched_at=FETCHED)
        titles = {item.details["title"] for item in signals}
        self.assertTrue(any("Bus bridge" in title or "suspended" in title.lower() for title in titles))
        self.assertFalse(any("Plan ahead" in title for title in titles))
        self.assertEqual({item.zone for item in signals},
                         {"sodo_stadiums", "seattle_center", "uw_district", "capitol_hill"})
        self.assertTrue(all(item.kind == "transit_disruption" for item in signals))
        self.assertTrue(any(item.details.get("severe") for item in signals))

    def test_track_delay_is_a_mild_disruption(self):
        payload = _load("onebusaway_st40_sample.json")
        start = datetime.fromtimestamp(1788933600000 / 1000).astimezone()
        end = start + timedelta(hours=6)
        signals = onebusaway.parse(payload, start, end, fetched_at=FETCHED)
        self.assertTrue(signals)
        self.assertTrue(all(item.details.get("severe") is False for item in signals))
        self.assertTrue(any("delayed" in item.details["title"].lower() for item in signals))

    def test_missing_key_is_needs_key_without_network(self):
        with patch.dict(os.environ, {"ONEBUSAWAY_API_KEY": ""}, clear=False):
            os.environ.pop("ONEBUSAWAY_API_KEY", None)
            signals, status = onebusaway.fetch(
                _at("2026-08-14T20:00:00-07:00"),
                _at("2026-08-15T02:00:00-07:00"),
            )
        self.assertEqual(signals, [])
        self.assertEqual(status.mode, "needs_key")


class FlightAwareParseTests(unittest.TestCase):
    def test_counts_ksea_arrivals_in_window_as_fifo_board(self):
        payload = _load("flightaware_ksea_sample.json")
        signals = flightaware.parse(
            payload,
            _at("2026-08-14T11:00:00-07:00"),
            _at("2026-08-14T15:00:00-07:00"),
            fetched_at=FETCHED,
        )
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].zone, "sea_airport")
        self.assertEqual(signals[0].kind, "airport_arrivals")
        self.assertEqual(signals[0].basis, "live")
        self.assertEqual(signals[0].details["count"], 3)
        self.assertFalse(signals[0].details["page_full"])
        self.assertGreater(signals[0].details["per_hour"], 10)
        self.assertIn("per hour", signals[0].details["title"])
        idents = {row["ident"] for row in signals[0].details["flights"]}
        self.assertIn("ASA599", idents)

    def test_fifteen_spread_out_is_page_full_not_a_dump(self):
        start = _at("2026-08-14T11:00:00-07:00")
        arrivals = []
        for index in range(15):
            when = start + timedelta(minutes=12 * index)
            arrivals.append(
                {
                    "ident": f"TST{index:03d}",
                    "origin": {"code": "KLAX"},
                    "estimated_in": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "scheduled_in": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "actual_in": None,
                }
            )
        signals = flightaware.parse(
            {"arrivals": arrivals},
            start,
            start + timedelta(hours=4),
            fetched_at=FETCHED,
        )
        self.assertEqual(signals[0].details["count"], 15)
        self.assertTrue(signals[0].details["page_full"])
        self.assertLess(signals[0].details["per_hour"], 9)
        self.assertIn("spread out", signals[0].details["title"])
        self.assertEqual(signals[0].magnitude, 4.0)

    def test_fifteen_stacked_in_forty_minutes_is_busy(self):
        start = _at("2026-08-14T11:00:00-07:00")
        arrivals = []
        for index in range(15):
            when = start + timedelta(minutes=3 * index)
            arrivals.append(
                {
                    "ident": f"STK{index:03d}",
                    "origin": {"code": "KLAX"},
                    "estimated_in": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "scheduled_in": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "actual_in": None,
                }
            )
        signals = flightaware.parse(
            {"arrivals": arrivals},
            start,
            start + timedelta(hours=2),
            fetched_at=FETCHED,
        )
        self.assertTrue(signals[0].details["page_full"])
        self.assertGreater(signals[0].details["per_hour"], 20)
        self.assertIn("stacked", signals[0].details["title"])
        self.assertGreaterEqual(signals[0].magnitude, 10)

    def test_two_page_pull_is_not_full_at_twenty_flights(self):
        start = _at("2026-08-14T11:00:00-07:00")
        arrivals = []
        for index in range(20):
            when = start + timedelta(minutes=3 * index)
            arrivals.append(
                {
                    "ident": f"P2{index:03d}",
                    "origin": {"code": "KLAX"},
                    "estimated_in": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "scheduled_in": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "actual_in": None,
                }
            )
        signals = flightaware.parse(
            {"arrivals": arrivals},
            start,
            start + timedelta(hours=2),
            fetched_at=FETCHED,
            page_limit=2,
        )
        self.assertEqual(signals[0].details["count"], 20)
        self.assertFalse(signals[0].details["page_full"])
        self.assertGreater(signals[0].details["per_hour"], 18)

    def test_idle_without_demand_does_not_hit_network_even_in_bank(self):
        with (
            patch.dict(os.environ, {"FLIGHTAWARE_API_KEY": "test-key"}),
            patch.object(flightaware, "fetch_json", side_effect=AssertionError("no poll")),
        ):
            signals, status = flightaware.fetch(
                _at("2026-08-14T11:00:00-07:00"),
                _at("2026-08-14T15:00:00-07:00"),
            )
        self.assertEqual(signals, [])
        self.assertEqual(status.mode, "static")
        self.assertIn("on-demand", status.detail)
        self.assertIn("in SEA arrival bank", status.detail)

    def test_demand_fetches_even_outside_banks(self):
        payload = _load("flightaware_ksea_sample.json")
        with (
            patch.dict(os.environ, {"FLIGHTAWARE_API_KEY": "test-key"}),
            patch.object(
                flightaware, "fetch_json", return_value=(payload, "live", FETCHED)
            ) as mocked,
        ):
            signals, status = flightaware.fetch(
                _at("2026-08-14T20:00:00-07:00"),
                _at("2026-08-15T02:00:00-07:00"),
                demand=True,
            )
        mocked.assert_called_once()
        called_url = mocked.call_args[0][0]
        self.assertIn("max_pages=2", called_url)
        self.assertEqual(mocked.call_args.kwargs["cache_key"], "flightaware_ksea_arrivals_p2")
        self.assertEqual(signals, [])
        self.assertEqual(status.mode, "live")
        self.assertIn("on-demand", status.detail)

    def test_demand_looks_back_thirty_minutes_for_taxiing(self):
        payload = _load("flightaware_ksea_sample.json")
        with (
            patch.dict(os.environ, {"FLIGHTAWARE_API_KEY": "test-key"}),
            patch.object(
                flightaware, "fetch_json", return_value=(payload, "live", FETCHED)
            ),
        ):
            # Sample estimated_in is 11:16–11:30 local; window starts at 11:35.
            signals, status = flightaware.fetch(
                _at("2026-08-14T11:35:00-07:00"),
                _at("2026-08-14T14:00:00-07:00"),
                demand=True,
            )
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].details["count"], 3)
        self.assertEqual(status.mode, "live")

    def test_demand_in_bank_parses_fifo_signal(self):
        payload = _load("flightaware_ksea_sample.json")
        with (
            patch.dict(os.environ, {"FLIGHTAWARE_API_KEY": "test-key"}),
            patch.object(
                flightaware, "fetch_json", return_value=(payload, "live", FETCHED)
            ),
        ):
            signals, status = flightaware.fetch(
                _at("2026-08-14T11:00:00-07:00"),
                _at("2026-08-14T15:00:00-07:00"),
                demand=True,
            )
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].zone, "sea_airport")
        self.assertEqual(status.mode, "live")

    def test_missing_key_is_needs_key_without_network(self):
        with patch.dict(os.environ, {"FLIGHTAWARE_API_KEY": ""}, clear=False):
            os.environ.pop("FLIGHTAWARE_API_KEY", None)
            signals, status = flightaware.fetch(
                _at("2026-08-14T11:00:00-07:00"),
                _at("2026-08-14T15:00:00-07:00"),
            )
        self.assertEqual(signals, [])
        self.assertEqual(status.mode, "needs_key")


class GrokResearchTests(unittest.TestCase):
    def setUp(self):
        # Historical cloud-adapter behavior remains covered only with explicit opt-in.
        self.cloud_policy = patch.dict(os.environ, {"FAROL_BRAIN": "grok"})
        self.cloud_policy.start()
        self.addCleanup(self.cloud_policy.stop)

    def test_parse_keeps_verified_kinds_and_drops_unknown(self):
        payload = _load("grok_research_sample.json")
        signals = grok_research.parse(
            payload,
            _at("2026-08-14T18:00:00-07:00"),
            _at("2026-08-15T00:00:00-07:00"),
            fetched_at=FETCHED,
        )
        kinds = {item.kind for item in signals}
        zones = {item.zone for item in signals}
        self.assertEqual(kinds, {"event_exit", "special_event"})
        self.assertEqual(zones, {"marymoor", "bellevue_core"})
        self.assertTrue(all(item.id.startswith("grok-") for item in signals))

    def test_cache_key_is_stable_within_the_ttl(self):
        start = _at("2026-08-14T20:00:00-07:00")
        with patch.dict(os.environ, {"FAROL_GROK_TTL_SECONDS": "1200"}):
            first = grok_research._cache_key(start, start + timedelta(hours=6))
            later = grok_research._cache_key(
                start + timedelta(seconds=90), start + timedelta(hours=6, seconds=90)
            )
            next_bucket = grok_research._cache_key(
                start + timedelta(minutes=21), start + timedelta(hours=6, minutes=21)
            )
            watch_first = grok_watch._cache_key(start, start + timedelta(hours=6))
            watch_later = grok_watch._cache_key(
                start + timedelta(seconds=90), start + timedelta(hours=6, seconds=90)
            )
        self.assertEqual(first, later)
        self.assertNotEqual(first, next_bucket)
        self.assertEqual(watch_first, watch_later)
        self.assertTrue(first.startswith("grok_"))
        self.assertTrue(watch_first.startswith("grok_watch_"))

    def test_missing_key_is_needs_key_without_network(self):
        with patch.dict(os.environ, {"XAI_API_KEY": ""}, clear=False):
            os.environ.pop("XAI_API_KEY", None)
            signals, status = grok_research.fetch(
                _at("2026-08-14T20:00:00-07:00"),
                _at("2026-08-15T02:00:00-07:00"),
            )
        self.assertEqual(signals, [])
        self.assertEqual(status.mode, "needs_key")

    def test_cold_cache_warms_in_the_background(self):
        kicked = []

        def fake_kick(start, end, cache_key):
            kicked.append(cache_key)

        with (
            patch.dict(os.environ, {"XAI_API_KEY": "test-key"}),
            patch.object(grok_research, "read_cache", return_value=None),
            patch.object(grok_research, "_kick_refresh", side_effect=fake_kick),
        ):
            signals, status = grok_research.fetch(
                _at("2026-08-14T20:00:00-07:00"),
                _at("2026-08-15T02:00:00-07:00"),
            )
        self.assertEqual(signals, [])
        self.assertEqual(status.mode, "warming")
        self.assertEqual(len(kicked), 1)


class EnvLoaderTests(unittest.TestCase):
    def test_existing_environment_wins(self):
        from farol.env import load_env

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text("MOCK_FEEDS=0\nFAROL_TEST_ENV=from-file\n", encoding="utf-8")
            with patch.dict(os.environ, {"MOCK_FEEDS": "1"}, clear=False):
                load_env(path)
                self.assertEqual(os.environ["MOCK_FEEDS"], "1")
                self.assertEqual(os.environ.get("FAROL_TEST_ENV"), "from-file")
            os.environ.pop("FAROL_TEST_ENV", None)

    def test_empty_values_do_not_override_defaults(self):
        from farol.env import load_env

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text("FAROL_NWS_HOURLY_URL=\nFAROL_EMPTY_SET=ok\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("FAROL_NWS_HOURLY_URL", None)
                os.environ.pop("FAROL_EMPTY_SET", None)
                load_env(path)
                self.assertNotIn("FAROL_NWS_HOURLY_URL", os.environ)
                self.assertEqual(os.environ.get("FAROL_EMPTY_SET"), "ok")
            os.environ.pop("FAROL_EMPTY_SET", None)


if __name__ == "__main__":
    unittest.main()
