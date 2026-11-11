import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from farol.api import app
from farol.dashboard import brief_view


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_brief_is_explicitly_not_live_advice(self):
        brief = brief_view(.45)
        self.assertFalse(brief["live_advice"])
        self.assertEqual(brief["shift_decision"]["action"], "NOT SCORED")
        self.assertIn("modeled", brief["evidence_label"].lower())

    def test_cost_selector_uses_supported_scenario(self):
        brief = brief_view(.46)
        self.assertEqual(brief["vehicle_cost_per_mile"], .45)

    def test_every_explanation_number_comes_from_scores(self):
        brief = brief_view(.45)
        recommendation = brief["recommendation"]
        runner_up = brief["runner_up"]
        explanation = brief["explanation"]
        self.assertIn(f"${recommendation['expected_dollars_per_hour']:.2f}", explanation)
        self.assertIn(f"${recommendation['reposition_cost']:.2f}", explanation)
        self.assertIn(f"${runner_up['expected_dollars_per_hour']:.2f}", explanation)
        self.assertEqual(
            brief["audit"]["recommendation_inputs"], recommendation["inputs"]
        )

    def test_stadium_report_is_not_learning_eligible(self):
        brief = brief_view(.45)
        self.assertEqual(brief["stadium_finding"]["offer_count"], 0)
        self.assertFalse(brief["stadium_finding"]["learning_eligible"])

    def test_local_api_serves_health_brief_and_dashboard(self):
        health = self.client.get("/api/health")
        brief = self.client.get("/api/brief?vehicle_cost=0.45")
        home = self.client.get("/")
        developer = self.client.get("/developer")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()["mock_feeds"])
        self.assertIn("grok_configured", health.json())
        self.assertEqual(health.json()["grok_model"], "grok-4.6")
        self.assertEqual(health.json()["brain"], "qwen")
        self.assertFalse(health.json()["narrator"]["cloud_ai_enabled"])
        self.assertIn("collector", health.json())
        self.assertFalse(health.json()["collector"]["running"])
        self.assertEqual(brief.json()["mode"], "FRIDAY REPLAY")
        self.assertIn("Should I drive?", home.text)
        self.assertIn("Airport queue", home.text)
        self.assertIn("id=\"here-sea\"", home.text)
        js = self.client.get("/tonight.js")
        self.assertEqual(js.status_code, 200)
        self.assertIn("here-sea", js.text)
        self.assertNotIn("Farol Friday Replay", home.text)
        self.assertIn("RideEdge Developer Tools", developer.text)
        self.assertIn("/api/replay/friday", developer.text)

    def test_api_rejects_nonpositive_vehicle_cost(self):
        response = self.client.get("/api/brief?vehicle_cost=0")
        self.assertEqual(response.status_code, 400)

    def test_api_navigates_decision_timeline(self):
        first = self.client.get("/api/brief?vehicle_cost=0.45&decision=0")
        last = self.client.get("/api/brief?vehicle_cost=0.45&decision=9")
        self.assertEqual(first.json()["selected_decision_index"], 0)
        self.assertEqual(last.json()["selected_decision_index"], 9)
        self.assertEqual(len(first.json()["timeline"]), 10)
        self.assertNotEqual(first.json()["decision"]["at"], last.json()["decision"]["at"])

    def test_api_rejects_out_of_range_decision(self):
        response = self.client.get("/api/brief?decision=10")
        self.assertEqual(response.status_code, 400)

    def test_navigation_mailbox_requires_pairing_and_returns_demo_route(self):
        published = self.client.post("/api/navigation/demo?decision=9&vehicle_cost=0.45")
        self.assertEqual(published.status_code, 200)
        self.assertTrue(published.json()["demo_only"])
        self.assertTrue(published.json()["driver_confirmation_required"])
        self.assertEqual(published.json()["destination"]["label"], "DEMO Kirkland Bar Strip")
        with patch.dict("os.environ", {"FAROL_CAR_TOKEN": "test-secret"}):
            denied = self.client.get("/api/navigation/current")
            allowed = self.client.get(
                "/api/navigation/current", headers={"X-Farol-Car-Token": "test-secret"}
            )
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["command_id"], published.json()["command_id"])


if __name__ == "__main__":
    unittest.main()
