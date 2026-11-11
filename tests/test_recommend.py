import unittest
from datetime import datetime

from farol.adapters import sea_fifo
from farol.recommend import empty_miles_report, rank_next_hours
from farol.tonight import tonight_brief


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


class EmptyMilesTests(unittest.TestCase):
    def test_gap_and_centroid_deadhead_are_recorded(self):
        trips = [
            _trip(
                "2026-08-21T20:00:00-07:00",
                "2026-08-21T20:20:00-07:00",
                "bellevue_core",
                "seattle_core",
                20,
                8,
            ),
            _trip(
                "2026-08-21T21:00:00-07:00",
                "2026-08-21T21:15:00-07:00",
                "kirkland_waterfront",
                "kirkland_waterfront",
                10,
                2,
            ),
        ]
        report = empty_miles_report(trips)
        self.assertEqual(report["pairs"], 1)
        self.assertEqual(report["mean_unpaid_gap_minutes"], 40)
        self.assertGreater(report["mean_estimated_empty_miles"], 5)


class RankTests(unittest.TestCase):
    def test_staying_in_kirkland_beats_a_long_reposition_with_no_history(self):
        now = datetime.fromisoformat("2026-08-16T18:21:00-07:00")
        result = rank_next_hours([], now=now, origin_zone="kirkland_waterfront", hours=1)
        top = result["ranked"][0]
        self.assertEqual(top["zone"], "kirkland_waterfront")
        self.assertEqual(top["reposition_minutes"], 0)
        self.assertIn("Do not chase Uber purple", result["doctrine"])
        self.assertTrue(all(row["zone"] != "sea_airport" for row in result["ranked"]))

    def test_hour_zone_history_can_outrank_home_after_reposition(self):
        trips = [
            _trip(
                "2026-08-14T20:10:00-07:00",
                "2026-08-14T20:25:00-07:00",
                "bellevue_core",
                "bellevue_core",
                40,
                2,
            ),
            _trip(
                "2026-08-07T20:15:00-07:00",
                "2026-08-07T20:30:00-07:00",
                "bellevue_core",
                "bellevue_core",
                38,
                2,
            ),
        ]
        now = datetime.fromisoformat("2026-08-21T20:05:00-07:00")
        result = rank_next_hours(
            trips, now=now, origin_zone="kirkland_waterfront", hours=1, value_of_time_per_hour=22
        )
        bellevue = next(row for row in result["ranked"] if row["zone"] == "bellevue_core")
        home = next(row for row in result["ranked"] if row["zone"] == "kirkland_waterfront")
        self.assertGreater(bellevue["historical_mean_earnings"], home["historical_mean_earnings"])
        self.assertGreater(bellevue["score"], home["score"])
        self.assertFalse(bellevue["thin"])


class SeaFifoTests(unittest.TestCase):
    def test_afternoon_bank_is_emitted_and_jan_is_marked_thin(self):
        summer = sea_fifo.parse(
            datetime.fromisoformat("2026-08-14T10:00:00-07:00"),
            datetime.fromisoformat("2026-08-14T16:00:00-07:00"),
            fetched_at="t",
        )
        self.assertEqual(len(summer), 1)
        self.assertEqual(summer[0].zone, "sea_airport")
        self.assertIn("3037 S 160th", summer[0].details["staging"])
        self.assertEqual(summer[0].details["game"], "fifo")
        winter = sea_fifo.parse(
            datetime.fromisoformat("2026-01-15T10:00:00-07:00"),
            datetime.fromisoformat("2026-01-15T16:00:00-07:00"),
            fetched_at="t",
        )
        self.assertLess(winter[0].magnitude, summer[0].magnitude)


class BriefSitHereTests(unittest.TestCase):
    def test_fixture_brief_exposes_sit_here_board(self):
        brief = tonight_brief()
        self.assertIn("sit_here", brief)
        self.assertTrue(brief["sit_here"]["ranked"])
        self.assertTrue(all(row["zone"] != "sea_airport" for row in brief["sit_here"]["ranked"]))


if __name__ == "__main__":
    unittest.main()
