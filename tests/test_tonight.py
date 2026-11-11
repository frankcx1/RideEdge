import unittest
from dataclasses import replace
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from farol.api import app
from farol.dashboard import FIXTURES
from farol.signals import FixtureSignalAdapter, load_anchors
from farol.tonight import tonight_brief

SIGNALS_PATH = FIXTURES / "tonight_signals.json"
CAPITOL_HILL_ID = "capitol_hill-2026-08-14T23:45:00-07:00"
SEATTLE_CENTER_ID = "seattle_center-2026-08-14T21:00:00-07:00"
LIME_ID = "kirkland_rose_hill-2026-08-15T01:15:00-07:00"


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _approved_anchors(path):
    return [replace(anchor, approval_status="approved") for anchor in load_anchors(path)]


def _opportunity(brief: dict, opportunity_id: str) -> dict:
    return next(item for item in brief["opportunities"] if item["id"] == opportunity_id)


class SignalWindowTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FixtureSignalAdapter(SIGNALS_PATH)

    def test_adapter_keeps_only_signals_overlapping_the_window(self):
        fetched = self.adapter.fetch(
            _at("2026-08-14T20:00:00-07:00"), _at("2026-08-14T21:00:00-07:00")
        )
        self.assertEqual(
            {signal.id for signal in fetched},
            {"event-climate-pledge-01", "doctrine-stadium-01"},
        )

    def test_adapter_returns_nothing_before_any_signal_starts(self):
        fetched = self.adapter.fetch(
            _at("2026-08-14T20:00:00-07:00"), _at("2026-08-14T20:15:00-07:00")
        )
        self.assertEqual(fetched, [])

    def test_brief_window_excludes_opportunities_past_the_horizon(self):
        brief = tonight_brief(hours=2)
        zones = {item["zone"] for item in brief["opportunities"]}
        self.assertIn("kirkland_waterfront", zones)
        self.assertIn("redmond_downtown", zones)
        self.assertIn("marymoor", zones)
        self.assertNotIn("capitol_hill", zones)
        self.assertEqual(
            brief["basis_counts"], {"scheduled": 4, "live": 1, "assumed": 1}
        )
        self.assertNotIn("kirkland_rose_hill", zones)


class TonightBriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brief = tonight_brief()

    def test_doctrine_penalty_overlaps_the_event_exit(self):
        stadium = _opportunity(self.brief, SEATTLE_CENTER_ID)
        # event value min(15000/1000, 20)=15 minus doctrine magnitude 18
        self.assertEqual(stadium["audit"]["signal_score"], -3.0)
        self.assertIn(
            "doctrine-stadium-01", [fact["signal_id"] for fact in stadium["facts"]]
        )
        self.assertEqual(stadium["action"], "AVOID")
        self.assertLess(stadium["score"], 0)

    def test_rain_adjustment_requires_window_overlap(self):
        stadium = _opportunity(self.brief, SEATTLE_CENTER_ID)
        capitol = _opportunity(self.brief, CAPITOL_HILL_ID)
        self.assertEqual(stadium["audit"]["weather_adjustment"], 0)
        self.assertEqual(capitol["audit"]["weather_adjustment"], 2.5)

    def test_default_window_basis_counts_cover_all_fixture_signals(self):
        self.assertEqual(
            self.brief["basis_counts"], {"scheduled": 7, "live": 1, "assumed": 1}
        )

    def test_ranked_ids_follow_descending_score(self):
        scores = {item["id"]: item["score"] for item in self.brief["opportunities"]}
        expected = sorted(scores, key=lambda item_id: scores[item_id], reverse=True)
        self.assertEqual(self.brief["ranked_opportunity_ids"], expected)

    def test_expected_rates_are_unavailable_until_calibrated(self):
        for item in self.brief["opportunities"]:
            self.assertEqual(item["expected_rate_basis"], "unavailable")
        self.assertTrue(any("uncalibrated" in warning for warning in self.brief["warnings"]))

    def test_fixture_shift_decision_checks_lime_last_call(self):
        decision = self.brief["shift_decision"]
        self.assertEqual(decision["action"], "CHECK WINDOW")
        self.assertEqual(decision["best_zone"], "kirkland_rose_hill")

    def test_fixture_brief_skips_the_cloud_brain(self):
        self.assertEqual(self.brief["brain"]["mode"], "fixture")
        self.assertIsNone(self.brief["narration"])

    def test_shift_decision_checks_window_when_best_is_far_off(self):
        brief = tonight_brief(value_of_time_per_hour=1)
        self.assertEqual(brief["shift_decision"]["action"], "CHECK WINDOW")
        self.assertEqual(brief["shift_decision"]["best_zone"], "kirkland_rose_hill")

    def test_shift_decision_checks_window_when_lime_is_imminent(self):
        brief = tonight_brief(
            now=_at("2026-08-15T01:10:00-07:00"), value_of_time_per_hour=1
        )
        self.assertEqual(brief["shift_decision"]["action"], "CHECK WINDOW")
        self.assertEqual(brief["shift_decision"]["best_zone"], "kirkland_rose_hill")


class OpportunityNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_navigation_rejects_demo_only_anchor(self):
        brief = tonight_brief()
        self.assertFalse(
            any(item["navigation_available"] for item in brief["opportunities"])
        )
        response = self.client.post(f"/api/navigation/opportunity/{CAPITOL_HILL_ID}")
        self.assertEqual(response.status_code, 400)
        self.assertIn("driver-approved", response.json()["detail"])

    def test_navigation_rejects_unknown_opportunity(self):
        response = self.client.post("/api/navigation/opportunity/nowhere-2026")
        self.assertEqual(response.status_code, 400)
        self.assertIn("not found", response.json()["detail"])

    def test_navigation_succeeds_with_test_only_approved_anchor(self):
        with patch("farol.tonight.load_anchors", side_effect=_approved_anchors):
            published = self.client.post(
                f"/api/navigation/opportunity/{LIME_ID}"
            )
        self.assertEqual(published.status_code, 200)
        payload = published.json()
        self.assertEqual(payload["action"], "MOVE")
        self.assertTrue(payload["driver_confirmation_required"])
        self.assertFalse(payload["demo_only"])
        self.assertEqual(payload["destination"]["label"], "The Lime last-call (Rose Hill) — approval required")
        with patch.dict("os.environ", {"FAROL_CAR_TOKEN": "test-secret"}):
            fetched = self.client.get(
                "/api/navigation/current", headers={"X-Farol-Car-Token": "test-secret"}
            )
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["command_id"], payload["command_id"])


if __name__ == "__main__":
    unittest.main()
