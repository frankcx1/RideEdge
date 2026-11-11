import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from farol.collect import enabled, interval_seconds, refresh_once, status


class CollectorTests(unittest.TestCase):
    def test_disabled_under_pytest(self):
        self.assertFalse(enabled())

    def test_shift_hours_poll_faster_than_daytime(self):
        pacific = timezone(timedelta(hours=-7))
        friday_evening = datetime(2026, 8, 14, 20, 0, tzinfo=pacific)
        saturday_noon = datetime(2026, 8, 15, 12, 0, tzinfo=pacific)
        thursday_airport = datetime(2026, 8, 13, 6, 0, tzinfo=pacific)
        self.assertEqual(interval_seconds(friday_evening), 15 * 60)
        self.assertEqual(interval_seconds(saturday_noon), 60 * 60)
        self.assertEqual(interval_seconds(thursday_airport), 15 * 60)

    def test_refresh_skips_grok_and_records_status(self):
        from farol.adapters.base import FeedStatus

        fake = type(
            "A",
            (),
            {
                "NAME": "nws_hourly",
                "SOURCE": "test",
                "fetch": staticmethod(
                    lambda start, end: ([], FeedStatus("nws_hourly", "cache", "test", None, 0))
                ),
            },
        )
        grok = type(
            "B",
            (),
            {
                "NAME": "grok_research",
                "SOURCE": "test",
                "fetch": staticmethod(lambda start, end: (_ for _ in ()).throw(AssertionError("grok"))),
            },
        )
        aero = type(
            "C",
            (),
            {
                "NAME": "flightaware_sea",
                "SOURCE": "test",
                "fetch": staticmethod(lambda start, end: (_ for _ in ()).throw(AssertionError("fa"))),
            },
        )
        with (
            patch("farol.collect.ADAPTERS", [fake, grok, aero]),
            patch("farol.collect.write_snapshot") as snapshot,
            patch(
                "farol.adapters.routes.fetch",
                return_value=([], FeedStatus("google_routes_traffic", "cache", "test", None, 0)),
            ),
        ):
            feeds = refresh_once(datetime.fromisoformat("2026-08-14T20:00:00-07:00"))
        names = [item["adapter"] for item in feeds]
        self.assertIn("nws_hourly", names)
        self.assertIn("google_routes_traffic", names)
        self.assertNotIn("grok_research", names)
        self.assertNotIn("flightaware_sea", names)
        self.assertIsNotNone(status()["last_run_at"])
        snapshot.assert_called_once()
        self.assertEqual(snapshot.call_args.args[1], feeds)
