import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from farol.adapters import grok_watch
from farol.dashboard import FIXTURES
from farol.ingest import _zone, parse_export
from farol.tonight import tonight_brief
from farol.trips import personal_insights
from farol.zones import canonical_zone

FETCHED = "2026-08-20T19:00:00+00:00"


class CityMappingTests(unittest.TestCase):
    def test_city_token_beats_redmond_woodinville_road_name(self):
        self.assertEqual(
            _zone("18888 Redmond-Woodinville Rd NE, Woodinville, WA, US"),
            "woodinville_wine",
        )

    def test_cottage_lake_and_bellevue_short_addresses(self):
        self.assertEqual(_zone("Cottage Lake, WA, US"), "cottage_lake")
        self.assertEqual(_zone("Bellevue, WA, US"), "bellevue_core")
        self.assertEqual(canonical_zone("woodinville"), "woodinville_wine")


class PersonalInsightsTests(unittest.TestCase):
    def test_empty_ledger(self):
        result = personal_insights([])
        self.assertEqual(result["trips"], 0)
        self.assertEqual(result["status"], "empty")

    def test_eastside_vs_seattle_buckets(self):
        trips = [
            {
                "requested_at": "2026-08-21T20:45:00-07:00",
                "ended_at": "2026-08-21T21:00:00-07:00",
                "pickup_zone": "woodinville_wine",
                "dropoff_zone": "kirkland_waterfront",
                "duration_minutes": 15,
                "paid_miles": 7.5,
                "earnings": 17.3,
                "tip": 0,
                "seattle_miles": 0,
                "washington_miles": 7.5,
            },
            {
                "requested_at": "2026-08-21T23:05:00-07:00",
                "ended_at": "2026-08-21T23:15:00-07:00",
                "pickup_zone": "capitol_hill",
                "dropoff_zone": "seattle_core",
                "duration_minutes": 8,
                "paid_miles": 2.3,
                "earnings": 11.6,
                "tip": 2,
                "seattle_miles": 2.3,
                "washington_miles": 0,
            },
        ]
        result = personal_insights(trips)
        self.assertEqual(result["trips"], 2)
        self.assertEqual(result["status"], "thin")
        self.assertEqual(result["by_pickup_cluster"]["eastside"]["trips"], 1)
        self.assertEqual(result["by_pickup_cluster"]["seattle"]["trips"], 1)
        self.assertEqual(result["wa_miles_only"]["trips"], 1)
        self.assertEqual(result["has_seattle_miles"]["trips"], 1)


class WatchParseTests(unittest.TestCase):
    def test_watch_notes_become_intel_signals(self):
        from datetime import datetime, timedelta

        payload = json.loads((FIXTURES / "feeds" / "grok_watch_sample.json").read_text(encoding="utf-8"))
        start = datetime.fromisoformat("2026-08-21T18:00:00-07:00")
        signals = grok_watch.parse(payload, start, start + timedelta(hours=8), fetched_at=FETCHED)
        titles = {item.details["title"] for item in signals}
        self.assertTrue(any("empty miles" in title.lower() for title in titles))
        self.assertTrue(any(item.kind == "driver_intel" for item in signals))
        self.assertTrue(all("uber.com/earnings" not in item.source for item in signals))


class BriefContextTests(unittest.TestCase):
    def test_fixture_brief_includes_rate_card_and_empty_personal_under_pytest(self):
        brief = tonight_brief()
        self.assertEqual(brief["rate_card"]["year"], 2026)
        self.assertEqual(brief["rate_card"]["seattle"]["per_mile"], 1.63)
        self.assertEqual(brief["personal"]["trips"], 0)
        self.assertEqual(brief["watch"], [])


class ParseExportTests(unittest.TestCase):
    def test_synthetic_receipt_round_trips_without_addresses(self):
        contents = """report preamble,,,,,,
Request Timestamp,"Pickup Address (street, city, state)","Dropoff Address (street, city, state)",Duration (minutes),Mileage,Your earnings,Your earnings.Tip,City of Seattle - Distance,Washington State - Distance
"Friday, August 21, 2026T8:45:24 PM Pacific Daylight Time","Main St, Woodinville, WA, US","Cottage Lake, WA, US",10,2.5,$12,$2,0,2.5
"""
        with TemporaryDirectory() as folder:
            path = Path(folder) / "export.csv"
            path.write_text(contents, encoding="utf-8")
            trips = parse_export(path)
        self.assertEqual(len(trips), 1)
        self.assertEqual(trips[0]["pickup_zone"], "woodinville_wine")
        self.assertEqual(trips[0]["dropoff_zone"], "cottage_lake")
        self.assertEqual(trips[0]["tip"], 2.0)
        self.assertEqual(trips[0]["washington_miles"], 2.5)
        self.assertNotIn("address", json.dumps(trips[0]))


if __name__ == "__main__":
    unittest.main()
