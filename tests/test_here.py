import unittest
from datetime import datetime
from unittest.mock import patch

from farol.here import advise, resolve


def _trip(start, end, pickup, drop, earn=12.0, miles=3.0):
    return {
        "requested_at": start,
        "ended_at": end,
        "pickup_zone": pickup,
        "dropoff_zone": drop,
        "duration_minutes": 12,
        "paid_miles": miles,
        "earnings": earn,
        "tip": 0,
    }


class ResolveTests(unittest.TestCase):
    def test_lime_and_85th_are_rose_hill(self):
        self.assertEqual(resolve("I'm at The Lime")["zone"], "kirkland_rose_hill")
        self.assertEqual(resolve("85th and 122nd Kirkland")["zone"], "kirkland_rose_hill")

    def test_downtown_kirkland_is_waterfront(self):
        self.assertEqual(resolve("downtown kirkland")["zone"], "kirkland_waterfront")

    def test_example_public_origin_is_totem_lake_not_waterfront(self):
        place = resolve("Home")
        self.assertEqual(place["zone"], "totem_lake")
        self.assertNotEqual(place["matched"], "kirkland")

    def test_totem_lake_405(self):
        self.assertEqual(resolve("405 and 124th")["zone"], "totem_lake")

    def test_inventory_p1_places_resolve(self):
        self.assertEqual(resolve("Kirkland Performance Center")["zone"], "kirkland_waterfront")
        self.assertEqual(resolve("Meydenbauer")["zone"], "bellevue_core")
        self.assertEqual(resolve("Village Theatre")["zone"], "issaquah")

    def test_husky_stadium_is_uw_district(self):
        self.assertEqual(resolve("Husky Stadium")["zone"], "uw_district")
        self.assertEqual(resolve("U-District")["zone"], "uw_district")
        self.assertEqual(resolve("Montlake")["zone"], "uw_district")

    def test_sea_is_airport_board(self):
        place = resolve("SEA")
        self.assertEqual(place["zone"], "sea_airport")
        self.assertFalse(place["street_board"])

    def test_lat_lon_near_lime(self):
        place = resolve("47.6794, -122.1813")
        self.assertEqual(place["zone"], "kirkland_rose_hill")

    def test_unknown_place_errors(self):
        with self.assertRaises(ValueError):
            resolve("Timbuktu")


class AdviseTests(unittest.TestCase):
    def test_wait_when_history_is_here(self):
        trips = [
            _trip(
                "2026-08-14T20:10:00-07:00",
                "2026-08-14T20:25:00-07:00",
                "kirkland_rose_hill",
                "kirkland_rose_hill",
                28,
                2,
            ),
            _trip(
                "2026-08-07T20:15:00-07:00",
                "2026-08-07T20:30:00-07:00",
                "kirkland_rose_hill",
                "kirkland_rose_hill",
                26,
                2,
            ),
        ]
        result = advise(
            "The Lime",
            now=datetime.fromisoformat("2026-08-21T20:05:00-07:00"),
            trips=trips,
        )
        self.assertEqual(result["place"]["zone"], "kirkland_rose_hill")
        self.assertEqual(result["action"], "WAIT")
        self.assertIn("WAIT", result["spoken"])
        self.assertIn("Do not chase Uber purple", result["spoken"])

    def test_airport_does_not_use_street_wait(self):
        result = advise(
            "SEA",
            now=datetime.fromisoformat("2026-08-20T07:00:00-07:00"),
            trips=[],
        )
        self.assertEqual(result["action"], "WATCH")
        self.assertIn("FIFO", result["spoken"])
        self.assertIn("airport pickup queue", result["spoken"].lower())
        self.assertNotIn("latitude", result["place"])

    def test_parked_pin_reduces_to_rose_hill_and_lists_fixture_nearby(self):
        result = advise(
            "47.6794, -122.1813",
            now=datetime.fromisoformat("2026-08-14T20:05:00-07:00"),
            trips=[],
        )
        self.assertEqual(result["place"]["zone"], "kirkland_rose_hill")
        self.assertTrue(result["nearby"])
        self.assertNotIn("sea_airport", {item["zone"] for item in result["nearby"]})
        self.assertTrue(result["nearby"][0].get("plain"))
        self.assertIn(result["nearby"][0]["plain"].split(".")[0], result["spoken"])
        self.assertIn("Google Routes uses that pin", result["warnings"][0])
        self.assertIn("not sent to Grok", result["warnings"][0])

    def test_here_does_not_pull_grok_feeds(self):
        with patch("farol.tonight.gather_signals", return_value=([], [])) as gather:
            advise(
                "The Lime",
                now=datetime.fromisoformat("2026-08-14T20:05:00-07:00"),
                trips=[],
            )
        self.assertTrue(gather.called)
        self.assertEqual(gather.call_args.kwargs.get("include_llm"), False)
        self.assertEqual(gather.call_args.kwargs.get("include_on_demand"), False)

    def test_sea_card_explains_count_examples_and_zero_drive(self):
        opportunity = {
            "id": "sea-1",
            "zone": "sea_airport",
            "action": "WATCH",
            "score": 8.5,
            "starts_at": "2026-09-06T22:50:00-07:00",
            "ends_at": "2026-09-06T23:40:00-07:00",
            "route": {"traffic_minutes": 0, "distance_miles": 0.2, "basis": "live"},
            "facts": [
                {
                    "text": "13 planes landing about 10:50pm–11:20pm",
                    "basis": "live",
                    "kind": "airport_arrivals",
                    "count": 13,
                    "per_hour": 22,
                    "page_full": True,
                    "flights": [
                        {"ident": "UAL684", "origin": "LAX"},
                        {"ident": "ASA930", "origin": "OGG"},
                        {"ident": "ACA541", "origin": "YYZ"},
                        {"ident": "DAL1551", "origin": "LAX"},
                        {"ident": "ASA101", "origin": "SFO"},
                    ],
                }
            ],
        }
        with patch(
            "farol.here.score_window",
            return_value={"opportunities": [opportunity], "feeds": []},
        ):
            result = advise(
                "SEA",
                now=datetime.fromisoformat("2026-09-06T22:55:00-07:00"),
                trips=[],
            )
        self.assertEqual(result["action_plain"], "Airport queue")
        self.assertIn("13 planes", result["spoken"])
        self.assertIn("already", result["spoken"].lower())
        self.assertIn("cannot see how many Uber cars", result["spoken"])
        self.assertIn("Examples:", result["nearby"][0]["detail"])
        self.assertIn("9 more", result["nearby"][0]["detail"])
        self.assertIn("two pages", result["nearby"][0]["detail"])
        self.assertNotRegex(result["nearby"][0]["plain"], r"\b0 min\b")

    def test_sea_here_requests_aeroapi_on_demand(self):
        with patch("farol.tonight.gather_signals", return_value=([], [])) as gather:
            advise(
                "SEA",
                now=datetime.fromisoformat("2026-08-14T11:05:00-07:00"),
                trips=[],
            )
        self.assertEqual(gather.call_args.kwargs.get("include_llm"), False)
        self.assertEqual(gather.call_args.kwargs.get("include_on_demand"), True)

    def test_seattle_zone_with_history_and_live_routes_in_sit_here(self):
        trips = [
            _trip(
                "2026-08-07T20:10:00-07:00",
                "2026-08-07T20:25:00-07:00",
                "capitol_hill",
                "seattle_core",
                32,
                3,
            ),
            _trip(
                "2026-08-14T20:15:00-07:00",
                "2026-08-14T20:30:00-07:00",
                "capitol_hill",
                "seattle_core",
                30,
                3,
            ),
        ]
        opp = {
            "id": "bellevue-1",
            "zone": "bellevue_core",
            "action": "WATCH",
            "score": 6.0,
            "starts_at": "2026-08-21T20:00:00-07:00",
            "ends_at": "2026-08-21T22:00:00-07:00",
            "route": {"traffic_minutes": 14.0, "distance_miles": 6.8, "basis": "live"},
            "facts": [{"text": "Downtown Bellevue", "basis": "scheduled", "kind": "closing_wave"}],
        }
        result = advise(
            "capitol_hill",
            now=datetime.fromisoformat("2026-08-21T20:05:00-07:00"),
            trips=trips,
            scored_window={"opportunities": [opp], "feeds": []},
        )
        self.assertEqual(result["place"]["zone"], "capitol_hill")
        self.assertTrue(result["place"]["street_board"])
        self.assertEqual(result["action"], "WAIT")
        bellevue_slot0 = next(
            row
            for row in result["sit_here"]["ranked"]
            if row["zone"] == "bellevue_core" and row["hour"] == 20
        )
        self.assertEqual(bellevue_slot0["reposition_minutes"], 14.0)
        self.assertEqual(bellevue_slot0["route_basis"], "live")
