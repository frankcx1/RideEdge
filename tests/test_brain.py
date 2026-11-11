import json
import os
import unittest
from unittest.mock import patch

from farol.brain import apply, parse_narration
from farol.dashboard import FIXTURES
from farol.tonight import tonight_brief

BRAIN_SAMPLE = FIXTURES / "feeds" / "grok_brain_sample.json"
CAPITOL_HILL_ID = "capitol_hill-2026-08-14T23:45:00-07:00"


class BrainParseTests(unittest.TestCase):
    def test_narration_json_is_extracted(self):
        payload = json.loads(BRAIN_SAMPLE.read_text(encoding="utf-8"))
        narration = parse_narration(payload)
        self.assertIn("SKIP", narration["shift_rationale"])
        self.assertTrue(narration["now_move"])
        self.assertIn(CAPITOL_HILL_ID, narration["opportunity_notes"])


class BrainApplyTests(unittest.TestCase):
    def test_mock_brief_does_not_call_grok(self):
        with patch("farol.brain.complete") as complete:
            brief = tonight_brief()
        complete.assert_not_called()
        self.assertEqual(brief["brain"]["mode"], "fixture")
        self.assertIsNone(brief["narration"])

    def test_live_brain_attaches_notes_without_changing_scores(self):
        payload = json.loads(BRAIN_SAMPLE.read_text(encoding="utf-8"))
        engine = tonight_brief()
        scores = {item["id"]: item["score"] for item in engine["opportunities"]}
        rates = {item["id"]: item["expected_net_per_hour"] for item in engine["opportunities"]}
        live = dict(engine)
        live["mock_feeds"] = False
        with (
            patch.dict(
                os.environ,
                {"XAI_API_KEY": "test-key", "FAROL_BRAIN": "grok", "FAROL_GROK_BLOCK": "1"},
            ),
            patch("farol.brain.complete", return_value=(payload, "live", "2026-08-14T20:00:00-07:00")),
        ):
            result = apply(live)
        self.assertEqual(result["brain"]["mode"], "live")
        self.assertEqual(result["brain"]["provider"], "grok")
        self.assertEqual(result["shift_decision"]["explanation"], engine["shift_decision"]["explanation"])
        self.assertEqual(result["narration"]["shift_rationale"], engine["shift_decision"]["explanation"])
        self.assertEqual(
            {item["id"]: item["score"] for item in result["opportunities"]}, scores
        )
        self.assertEqual(
            {item["id"]: item["expected_net_per_hour"] for item in result["opportunities"]},
            rates,
        )
        capitol = next(item for item in result["opportunities"] if item["id"] == CAPITOL_HILL_ID)
        self.assertIn("Engine score", capitol["note"])

    def test_missing_key_warns_and_keeps_engine_explanation(self):
        live = dict(tonight_brief())
        live["mock_feeds"] = False
        original = live["shift_decision"]["explanation"]
        with patch.dict(os.environ, {"FAROL_BRAIN": "grok", "XAI_API_KEY": ""}, clear=False):
            os.environ.pop("XAI_API_KEY", None)
            result = apply(live)
        self.assertEqual(result["brain"]["mode"], "needs_key")
        self.assertEqual(result["shift_decision"]["explanation"], original)
        self.assertTrue(any("XAI_API_KEY" in warning for warning in result["warnings"]))

    def test_live_brain_returns_engine_immediately_while_warming(self):
        live = dict(tonight_brief())
        live["mock_feeds"] = False
        original = live["shift_decision"]["explanation"]
        with (
            patch.dict(
                os.environ,
                {"XAI_API_KEY": "test-key", "FAROL_BRAIN": "grok", "FAROL_GROK_BLOCK": ""},
            ),
            patch("farol.brain.read_cache", return_value=None),
            patch("farol.brain._kick_brain") as kick,
        ):
            result = apply(live)
        self.assertEqual(result["brain"]["mode"], "warming")
        self.assertIsNone(result["narration"])
        self.assertEqual(result["shift_decision"]["explanation"], original)
        kick.assert_called_once()


if __name__ == "__main__":
    unittest.main()
