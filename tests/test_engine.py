import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from farol.engine import Candidate, rank_candidates, select_shift
from farol.episodes import ClosedEpisode, PresenceSample, close_reason, interval_is_observable
from farol.ingest import observed_shift, read_wa_trip_receipts
from farol.replay import run_replay
from farol.simulator import run


def candidate(zone: str, *, reposition_minutes: float = 0, reposition_miles: float = 0):
    return Candidate(zone, .5, 20, 5, reposition_minutes, reposition_miles, 5, .4, "elicited", 2)


class EngineTests(unittest.TestCase):
    def test_reposition_cost_can_make_staying_better(self):
        candidates = [candidate("here"), candidate("hotspot", reposition_minutes=12, reposition_miles=6)]
        self.assertEqual(rank_candidates(candidates, "here", 30, .50)[0].zone, "here")

    def test_vehicle_cost_is_deducted_and_audited(self):
        score = rank_candidates([candidate("here")], "here", 0, .50)[0]
        self.assertEqual(score.expected_net_fare_if_ride, 17.50)
        self.assertEqual(score.expected_vehicle_cost, 1.25)
        self.assertEqual(score.inputs["vehicle_cost_per_mile"], .50)
        self.assertEqual(score.inputs["prior_pseudo_count"], 2)

    def test_homeward_progress_credits_unavoidable_return_trip(self):
        moving_home = Candidate(
            "home", .5, 20, 5, 20, 12, 5, .4, "elicited", 2, 20, 12
        )
        score = rank_candidates([moving_home], "away", 30, .50)[0]
        self.assertEqual(score.homeward_credit, score.reposition_cost)

    def test_invalid_probability_is_rejected(self):
        with self.assertRaises(ValueError):
            Candidate("bad", 1.1, 20, 5, 0, 0, 5, .4, "prior")

    def test_shift_can_be_skipped_after_vehicle_cost(self):
        result = select_shift(52, 20, 190, 25, .50)
        self.assertEqual(result["action"], "SKIP")
        self.assertEqual(result["expected_net"], 42)

    def test_ignored_advice_only_updates_zone_ledger(self):
        episode = ClosedEpisode("d1", "here", "there", True, False, False, 0, "expired")
        self.assertEqual(
            episode.ledger_updates(),
            {"zone": True, "advice": False, "exploration": False},
        )

    def test_unobservable_silence_updates_nothing(self):
        episode = ClosedEpisode("d2", "here", "here", False, True, False, 0, "expired")
        self.assertFalse(any(episode.ledger_updates().values()))

    def test_presence_gap_makes_interval_unobservable(self):
        start = datetime(2026, 8, 7, 20, 0, tzinfo=UTC)
        samples = [PresenceSample(start, True), PresenceSample(start + timedelta(minutes=3), True)]
        self.assertFalse(interval_is_observable(samples))

    def test_episode_closes_on_precedence_and_timeout(self):
        start = datetime(2026, 8, 7, 20, 0, tzinfo=UTC)
        self.assertEqual(close_reason(start, start + timedelta(minutes=1), accepted_ping=True), "accepted_ping")
        self.assertEqual(close_reason(start, start + timedelta(minutes=20)), "expired")
        self.assertIsNone(close_reason(start, start + timedelta(minutes=19)))

    def test_replay_compares_all_four_policies_without_claiming_evidence(self):
        result = run(Path("fixtures/friday_replay.json"))
        self.assertEqual(result["data_status"], "placeholder")
        self.assertIsNotNone(result["evidence_warning"])
        self.assertEqual(set(result["policy_comparison"]), {"farol", "stay", "hotspot", "driver"})
        self.assertEqual(len(result["decisions"]), 2)
        self.assertEqual(result["policy_comparison"]["driver"]["observed_outcomes"], 0)

    def test_wa_export_ingest_reduces_addresses_to_zones(self):
        contents = """report preamble,,,,,,
Request Timestamp,"Pickup Address (street, city, state)","Dropoff Address (street, city, state)",Duration (minutes),Mileage,Your earnings,Your earnings.Tip
"Friday, August 7, 2026T1:59:55 PM Pacific Daylight Time","Bellevue, WA, US","Seattle, WA, US",10,2.5,$12,$2
"""
        with TemporaryDirectory() as folder:
            path = Path(folder) / "export.csv"
            path.write_text(contents, encoding="utf-8")
            result = observed_shift(read_wa_trip_receipts(path), "2026-08-07", .50)
        self.assertEqual(result["summary"]["trips"], 1)
        self.assertEqual(result["summary"]["net_after_paid_mile_cost_lower_bound"], 10.75)
        self.assertEqual(result["trips"][0]["pickup_zone"], "bellevue_core")
        self.assertNotIn("address", result["trips"][0])

    def test_actual_replay_keeps_inferred_actions_ungradeable(self):
        result = run_replay(
            Path("fixtures/friday_observed.json"), Path("fixtures/friday_model_v1.json")
        )
        self.assertEqual(result["decision_episode_count"], 10)
        self.assertEqual(result["debrief"]["model_evaluation"]["gradeable_advice_episodes"], 0)
        self.assertEqual(
            result["longest_gap"]["interval_observability"],
            "retrospective_driver_report",
        )
        self.assertFalse(result["longest_gap"]["driver_annotation"]["learning_eligible"])
        self.assertGreater(result["longest_gap"]["observed_gap_minutes"], 135)


if __name__ == "__main__":
    unittest.main()
