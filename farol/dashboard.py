import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
SUPPORTED_COSTS = (0.35, 0.45, 0.55)


def friday_window_split(vehicle_cost: float = 0.45) -> list[dict]:
    observed = _load("friday_observed.json")
    cost = _nearest_cost(vehicle_cost)
    cutoff = datetime.fromisoformat("2026-08-07T20:30:00-07:00")
    committed_minutes = observed["committed_window"]["minutes"]
    windows = (
        ("AFTERNOON", 420.0, lambda at: at < cutoff),
        ("FRIDAY ANCHOR", committed_minutes - 420.0, lambda at: at >= cutoff),
    )
    result = []
    for label, minutes, includes in windows:
        trips = [
            trip for trip in observed["trips"]
            if includes(datetime.fromisoformat(trip["requested_at"]))
        ]
        earnings = sum(trip["earnings"] for trip in trips)
        paid_miles = sum(trip["paid_miles"] for trip in trips)
        net = earnings - paid_miles * cost
        result.append({
            "label": label,
            "committed_minutes": round(minutes, 2),
            "trips": len(trips),
            "earnings": round(earnings, 2),
            "paid_miles": round(paid_miles, 2),
            "net_lower_bound": round(net, 2),
            "net_per_committed_hour_lower_bound": round(net / (minutes / 60), 2),
        })
    return result


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _nearest_cost(requested: float) -> float:
    return min(SUPPORTED_COSTS, key=lambda value: abs(value - requested))


def _explanation(recommendation: dict, runner_up: dict) -> str:
    move = (
        f"Move to {recommendation['zone'].replace('_', ' ')}"
        if recommendation["action"] == "MOVE"
        else f"Stay in {recommendation['zone'].replace('_', ' ')}"
    )
    credit = recommendation.get("homeward_credit", 0)
    credit_text = f" Homeward progress credits ${credit:.2f}." if credit else ""
    return (
        f"{move}. Modeled return is ${recommendation['expected_dollars_per_hour']:.2f}/hr "
        f"at {recommendation['confidence'] * 100:.0f}% confidence, with "
        f"${recommendation['reposition_cost']:.2f} reposition cost.{credit_text} "
        f"Runner-up {runner_up['zone'].replace('_', ' ')} scores "
        f"${runner_up['expected_dollars_per_hour']:.2f}/hr."
    )


def brief_view(vehicle_cost: float = 0.45, decision_index: int | None = None) -> dict:
    replay = _load("friday_debrief.json")
    observed = _load("friday_observed.json")
    cost = _nearest_cost(vehicle_cost)
    episodes = replay["cost_scenarios"][f"{cost:.2f}"]
    closer_index = next(
        index for index, episode in enumerate(episodes)
        if episode["next_observed_pickup_zone"] == "kirkland_bar_strip"
    )
    if decision_index is None:
        decision_index = closer_index
    if not 0 <= decision_index < len(episodes):
        raise ValueError(f"decision_index must be between 0 and {len(episodes) - 1}")
    selected = episodes[decision_index]
    stadium = max(episodes, key=lambda episode: episode["observed_gap_minutes"])
    recommendation = selected["recommendation"]
    runner_up = selected["runner_up"]
    return {
        "mode": "FRIDAY REPLAY",
        "live_advice": False,
        "evidence_label": "Observed shift + modeled recommendation",
        "vehicle_cost_per_mile": cost,
        "supported_vehicle_costs": list(SUPPORTED_COSTS),
        "selected_decision_index": decision_index,
        "decision_count": len(episodes),
        "timeline": [
            {
                "index": index,
                "at": episode["started_at"],
                "current_zone": episode["current_zone"],
                "observed_gap_minutes": episode["observed_gap_minutes"],
                "recommendation_action": episode["recommendation"]["action"],
                "recommendation_zone": episode["recommendation"]["zone"],
                "annotated": "driver_annotation" in episode,
            }
            for index, episode in enumerate(episodes)
        ],
        "shift_decision": {
            "action": "NOT SCORED",
            "reason": "No pre-shift forecast was recorded before this historical shift.",
        },
        "recommendation": recommendation,
        "runner_up": runner_up,
        "explanation": _explanation(recommendation, runner_up),
        "decision": {
            "at": selected["started_at"],
            "current_zone": selected["current_zone"],
            "next_observed_pickup_zone": selected["next_observed_pickup_zone"],
            "observed_gap_minutes": selected["observed_gap_minutes"],
            "driver_choice_basis": selected["driver_choice_basis"],
            "gradeable": selected["advice_outcome_gradeable"],
            "annotation": selected.get("driver_annotation"),
        },
        "stadium_finding": {
            "wait_minutes": stadium["observed_gap_minutes"],
            "strategy": stadium.get("driver_annotation", {}).get("strategy"),
            "offer_count": stadium.get("driver_annotation", {}).get(
                "driver_reported_offer_count"
            ),
            "learning_eligible": stadium.get("driver_annotation", {}).get(
                "learning_eligible"
            ),
            "hypotheses": stadium.get("driver_annotation", {}).get(
                "hypotheses_to_test", []
            ),
        },
        "observed_summary": observed["summary"],
        "window_split": friday_window_split(cost),
        "committed_window": observed["committed_window"],
        "audit": {
            "recommendation_inputs": recommendation["inputs"],
            "model_warning": replay["warning"],
            "counterfactual_policy_results": replay["debrief"]["model_evaluation"][
                "counterfactual_policy_results"
            ],
        },
    }
