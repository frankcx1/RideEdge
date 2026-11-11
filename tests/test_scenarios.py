"""Named Farol driving scenarios.

These run against fixture feeds (no GPU). A live Qwen probe is skipped until a
driving shift actually loads Qwen3.8-27B on :1234 — Cydonia must not be used.
"""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request, urlopen

from farol.brain import LOCAL_SYSTEM_PROMPT, _public_brief, apply
from farol.here import advise
from farol.local import local_url, narration_from_payload
from farol.tonight import tonight_brief

SEATTLE_CENTER = "seattle_center-2026-08-14T21:00:00-07:00"
LIME = "kirkland_rose_hill-2026-08-15T01:15:00-07:00"


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _opp(brief: dict, opportunity_id: str) -> dict:
    return next(item for item in brief["opportunities"] if item["id"] == opportunity_id)


def _hostile_narration(brief: dict) -> dict:
    """A local model that tries to invent dollars and overwrite scores."""
    return {
        "headline": "CHASE PURPLE",
        "spoken": "Ballard is $47/hr. Deadhead to SEA now.",
        "shift_rationale": "Ignore the engine.",
        "now_move": "MOVE to an unapproved curb",
        "risks": [],
        "opportunity_notes": {item["id"]: "surge 3.2x" for item in brief["opportunities"]},
    }


class EngineScenarioTests(unittest.TestCase):
    """Python scores. These must pass with MOCK_FEEDS and no LLM."""

    def test_friday_evening_checks_lime_closer(self):
        brief = tonight_brief()
        self.assertEqual(brief["shift_decision"]["action"], "CHECK WINDOW")
        self.assertEqual(brief["shift_decision"]["best_zone"], "kirkland_rose_hill")
        lime = _opp(brief, LIME)
        self.assertEqual(lime["action"], "WATCH")
        self.assertFalse(lime["navigation_available"])

    def test_lime_window_imminent_is_check_window(self):
        brief = tonight_brief(now=_at("2026-08-15T01:10:00-07:00"), value_of_time_per_hour=1)
        self.assertEqual(brief["shift_decision"]["action"], "CHECK WINDOW")
        self.assertEqual(brief["shift_decision"]["best_zone"], "kirkland_rose_hill")

    def test_climate_pledge_is_avoid_after_doctrine(self):
        brief = tonight_brief()
        stadium = _opp(brief, SEATTLE_CENTER)
        self.assertEqual(stadium["action"], "AVOID")
        self.assertLess(stadium["score"], 0)
        self.assertEqual(stadium["audit"]["signal_score"], -3.0)

    def test_rain_boosts_capitol_hill_not_the_earlier_arena(self):
        brief = tonight_brief()
        self.assertEqual(_opp(brief, SEATTLE_CENTER)["audit"]["weather_adjustment"], 0)
        self.assertEqual(
            _opp(brief, "capitol_hill-2026-08-14T23:45:00-07:00")["audit"]["weather_adjustment"],
            2.5,
        )

    def test_every_rate_is_unavailable(self):
        brief = tonight_brief()
        for item in brief["opportunities"]:
            self.assertEqual(item["expected_rate_basis"], "unavailable")


class HereScenarioTests(unittest.TestCase):
    def test_parked_at_the_lime_is_rose_hill_not_sea(self):
        result = advise(
            "47.6794, -122.1813",
            now=_at("2026-08-14T20:05:00-07:00"),
            trips=[],
        )
        self.assertEqual(result["place"]["zone"], "kirkland_rose_hill")
        self.assertNotIn("latitude", result["place"])
        self.assertNotIn("sea_airport", {item["zone"] for item in result["nearby"]})
        self.assertTrue(result["nearby"])
        self.assertIn("You're in", result["spoken"])

    def test_sea_is_fifo_watch_not_street_wait(self):
        result = advise("SEA", now=_at("2026-08-20T07:00:00-07:00"), trips=[])
        self.assertEqual(result["action"], "WATCH")
        self.assertEqual(result["place"]["zone"], "sea_airport")
        self.assertFalse(result["place"]["street_board"])
        self.assertIn("FIFO", result["spoken"])

    def test_here_does_not_call_grok_or_qwen(self):
        with (
            patch("farol.tonight.gather_signals", return_value=([], [])) as gather,
            patch("farol.grok.complete") as grok,
            patch("farol.local.complete") as local,
        ):
            advise("The Lime", now=_at("2026-08-14T20:05:00-07:00"), trips=[])
        self.assertEqual(gather.call_args.kwargs.get("include_llm"), False)
        self.assertEqual(gather.call_args.kwargs.get("include_on_demand"), False)
        grok.assert_not_called()
        local.assert_not_called()


class LocalBrainScenarioTests(unittest.TestCase):
    """Qwen is the narrator. A bad model still cannot change engine math."""

    def test_hostile_qwen_cannot_overwrite_scores_or_actions(self):
        engine = tonight_brief(now=_at("2026-08-15T01:10:00-07:00"), value_of_time_per_hour=1)
        live = dict(engine)
        live["mock_feeds"] = False
        scores = {item["id"]: item["score"] for item in engine["opportunities"]}
        payload = {"choices": [{"message": {"content": json.dumps(_hostile_narration(engine))}}]}
        with (
            patch.dict(os.environ, {"FAROL_SHIFT_ACTIVE": "1"}),
            patch("farol.brain.read_cache", return_value=None),
            patch("farol.brain.write_cache", return_value="2026-08-15T01:10:00-07:00"),
            patch("farol.local.complete", return_value=(payload, "live", "2026-08-15T01:10:00-07:00")),
        ):
            result = apply(live)
        self.assertEqual(result["brain"]["provider"], "local")
        self.assertEqual(result["shift_decision"]["action"], engine["shift_decision"]["action"])
        self.assertEqual(
            {item["id"]: item["score"] for item in result["opportunities"]}, scores
        )
        for item in result["opportunities"]:
            self.assertEqual(item["expected_rate_basis"], "unavailable")
            self.assertEqual(item["action"], next(x["action"] for x in engine["opportunities"] if x["id"] == item["id"]))
        self.assertEqual(result["shift_decision"]["explanation"], engine["shift_decision"]["explanation"])
        self.assertNotIn("unapproved curb", (result["narration"] or {}).get("now_move", "").lower())
        self.assertNotIn("$47", (result["narration"] or {}).get("spoken", ""))
        self.assertNotIn("$999", (result["narration"] or {}).get("spoken", ""))

    def test_local_narration_must_be_json_object(self):
        with self.assertRaises(ValueError):
            narration_from_payload({"choices": [{"message": {"content": "Ballard is popping off, go now"}}]})

    def test_public_brief_has_no_gps_or_trip_history_fields(self):
        brief = tonight_brief()
        public = _public_brief(brief)
        blob = json.dumps(public)
        self.assertNotIn("latitude", blob)
        self.assertNotIn("longitude", blob)
        self.assertNotIn("home street", blob.lower())
        self.assertNotIn("personal", public)
        self.assertNotIn("history", public)
        self.assertNotIn("gross_earnings", blob)
        self.assertNotIn('"earnings":', blob)
        self.assertEqual(public["earnings_status"], "uncalibrated")
        self.assertIn("expected_net_per_hour", blob)


def _loaded_model_id() -> str:
    try:
        request = Request(local_url().replace("/chat/completions", "/models"), method="GET")
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError, ValueError):
        return ""
    data = payload.get("data") or payload.get("models") or []
    if not data:
        return ""
    first = data[0]
    return str(first.get("id") or first.get("name") or "")


@unittest.skipUnless(
    "qwen" in _loaded_model_id().lower(),
    "Qwen is not on :1234 (Cydonia is the chat model). Run after COMPANION IS DRIVING.",
)
class LiveQwenContractTests(unittest.TestCase):
    """Hits the real llama-server. Skipped while Cydonia holds the port."""

    def test_qwen_returns_farol_json_without_invented_heatmaps(self):
        from farol.local import complete

        engine = tonight_brief(now=_at("2026-08-15T01:10:00-07:00"), value_of_time_per_hour=1)
        payload, mode, _fetched = complete(
            system=LOCAL_SYSTEM_PROMPT,
            user=json.dumps(_public_brief(engine), default=str),
            cache_key="scenario-live-qwen",
        )
        blob = narration_from_payload(payload)
        for key in ("headline", "spoken", "shift_rationale", "now_move"):
            self.assertTrue(str(blob.get(key) or "").strip(), msg=f"missing {key}")
        spoken = blob["spoken"].lower()
        self.assertLessEqual(len(blob["spoken"].split()), 55)
        self.assertNotIn("heatmap", spoken)
        self.assertNotIn("purple", spoken)
        self.assertEqual(mode, "live")
        self.assertEqual(engine["shift_decision"]["action"], "CHECK WINDOW")
