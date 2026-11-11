import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from farol.engine import Candidate, rank_candidates

POLICIES = ("farol", "stay", "hotspot", "driver")


@dataclass
class PolicyTotals:
    gross: float = 0
    vehicle_cost: float = 0
    deadhead_miles: float = 0
    waiting_minutes: float = 0
    brier_total: float = 0
    decisions: int = 0
    observed_outcomes: int = 0

    def report(self, committed_minutes: float) -> dict:
        net = self.gross - self.vehicle_cost
        return {
            "net_dollars": round(net, 2),
            "net_dollars_per_committed_hour": round(net * 60 / committed_minutes, 2),
            "gross_dollars": round(self.gross, 2),
            "vehicle_cost": round(self.vehicle_cost, 2),
            "deadhead_miles": round(self.deadhead_miles, 2),
            "waiting_minutes": round(self.waiting_minutes, 1),
            "brier_score": round(self.brier_total / self.decisions, 4),
            "observed_outcomes": self.observed_outcomes,
            "modeled_outcomes": self.decisions - self.observed_outcomes,
        }


def _candidate(raw: dict) -> Candidate:
    return Candidate(**raw)


def _chosen_zone(policy: str, decision: dict, recommendation: str) -> str:
    if policy == "farol":
        return recommendation
    key = {"stay": "current_zone", "hotspot": "hotspot_zone", "driver": "driver_choice"}[policy]
    return decision[key]


def run(path: Path) -> dict:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if fixture.get("data_status") not in {"actual", "placeholder"}:
        raise ValueError("fixture data_status must be 'actual' or 'placeholder'")
    config = fixture["config"]
    decisions = []
    totals = {policy: PolicyTotals() for policy in POLICIES}

    for raw_decision in fixture["decisions"]:
        candidates = [_candidate(item) for item in raw_decision["candidates"]]
        by_zone = {candidate.zone: candidate for candidate in candidates}
        ranked = rank_candidates(
            candidates,
            raw_decision["current_zone"],
            config["value_of_time_per_hour"],
            config["vehicle_cost_per_mile"],
            config.get("horizon_minutes", 15),
        )
        recommendation = ranked[0].zone
        policy_actions = {}
        for policy in POLICIES:
            zone = _chosen_zone(policy, raw_decision, recommendation)
            if zone not in raw_decision["outcomes"] or zone not in by_zone:
                raise ValueError(f"decision {raw_decision['id']} lacks outcome/candidate for {zone}")
            outcome = raw_decision["outcomes"][zone]
            if outcome.get("basis") not in {"observed", "modeled", "placeholder"}:
                raise ValueError("outcome basis must be observed, modeled, or placeholder")
            if (
                fixture["data_status"] == "actual"
                and policy == "driver"
                and outcome["basis"] != "observed"
            ):
                raise ValueError("an actual replay's driver outcome must be observed")
            candidate = by_zone[zone]
            total = totals[policy]
            total.gross += outcome["gross_earnings"]
            total.deadhead_miles += outcome["deadhead_miles"]
            total.vehicle_cost += (
                outcome["deadhead_miles"] + outcome["paid_miles"]
            ) * config["vehicle_cost_per_mile"]
            total.waiting_minutes += outcome["waiting_minutes"]
            total.brier_total += (candidate.p_ride_15m - float(outcome["ride_received"])) ** 2
            total.decisions += 1
            total.observed_outcomes += outcome["basis"] == "observed"
            policy_actions[policy] = {"zone": zone, "outcome": outcome}

        decisions.append(
            {
                "decision_id": raw_decision["id"],
                "at": raw_decision["at"],
                "recommendation": ranked[0].audit(),
                "runner_up": ranked[1].audit() if len(ranked) > 1 else None,
                "all_scores": [score.audit() for score in ranked],
                "driver_complied": raw_decision["driver_choice"] == recommendation,
                "policy_actions": policy_actions,
            }
        )

    committed_minutes = fixture["shift"]["committed_minutes"]
    comparisons = {
        policy: total.report(committed_minutes) for policy, total in totals.items()
    }
    return {
        "fixture": fixture["name"],
        "data_status": fixture["data_status"],
        "evidence_warning": (
            None if fixture["data_status"] == "actual"
            else "Placeholder outcomes are plumbing tests, not evidence that Farol wins."
        ),
        "shift": fixture["shift"],
        "config": config,
        "decisions": decisions,
        "policy_comparison": comparisons,
        "debrief": {
            "primary_metric": "net_dollars_per_committed_hour",
            "farol_vs_driver_delta_per_hour": round(
                comparisons["farol"]["net_dollars_per_committed_hour"]
                - comparisons["driver"]["net_dollars_per_committed_hour"],
                2,
            ),
            "farol_vs_stay_delta_per_hour": round(
                comparisons["farol"]["net_dollars_per_committed_hour"]
                - comparisons["stay"]["net_dollars_per_committed_hour"],
                2,
            ),
            "farol_vs_hotspot_delta_per_hour": round(
                comparisons["farol"]["net_dollars_per_committed_hour"]
                - comparisons["hotspot"]["net_dollars_per_committed_hour"],
                2,
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a Farol scripted shift")
    parser.add_argument("fixture", nargs="?", type=Path, default=Path("fixtures/friday_replay.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.fixture)
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
