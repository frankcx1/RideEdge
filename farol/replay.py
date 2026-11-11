import argparse
import json
from datetime import datetime
from itertools import pairwise
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from farol.engine import Candidate, rank_candidates


def _distance_miles(left: dict, right: dict) -> float:
    lat1, lon1, lat2, lon2 = map(
        radians, (left["lat"], left["lon"], right["lat"], right["lon"])
    )
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    haversine = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 3958.8 * 2 * asin(sqrt(haversine))


def decision_episodes(
    observed: dict, minimum_gap_minutes: float = 15, annotations: dict | None = None
) -> list[dict]:
    episodes = []
    trips = observed["trips"]
    for previous, following in pairwise(trips):
        gap = following["gap_since_previous_trip_minutes"] or 0
        if gap < minimum_gap_minutes:
            continue
        decision_id = f"gap-after-{previous['id']}"
        episode = {
                "decision_id": decision_id,
                "started_at": previous["ended_at"],
                "current_zone": previous["dropoff_zone"],
                "next_observed_pickup_zone": following["pickup_zone"],
                "driver_choice_basis": "inferred_from_next_pickup_not_confirmed",
                "interval_observability": "unknown",
                "observed_gap_minutes": gap,
                "next_trip": {
                    "pickup_zone": following["pickup_zone"],
                    "earnings": following["earnings"],
                    "paid_miles": following["paid_miles"],
                    "basis": "observed",
                },
            }
        if annotations and decision_id in annotations.get("decisions", {}):
            episode["driver_annotation"] = annotations["decisions"][decision_id]
            episode["interval_observability"] = "retrospective_driver_report"
        episodes.append(episode)
    return episodes


def _candidate(zone: str, current_zone: str, at: datetime, model: dict) -> Candidate:
    raw = dict(model["zones"][zone])
    raw.pop("lat")
    raw.pop("lon")
    raw["basis"] = "elicited_zone_prior"
    late = model.get("late_night_overrides", {})
    if late.get("starts_at_hour", 99) <= at.hour < late.get("ends_at_hour", -1):
        raw.update(late.get("zones", {}).get(zone, {}))

    if zone == current_zone:
        route_miles = route_minutes = 0.0
    else:
        route = model["route_model"]
        route_miles = _distance_miles(model["zones"][current_zone], model["zones"][zone])
        route_miles *= route["road_distance_factor"]
        route_minutes = route_miles / route["average_mph"] * 60
    homeward_miles_saved = homeward_minutes_saved = 0.0
    if at.hour >= model.get("homeward_credit_starts_at_hour", 99):
        home = model["zones"][model["home_zone"]]
        route = model["route_model"]
        current_home = _distance_miles(model["zones"][current_zone], home)
        target_home = _distance_miles(model["zones"][zone], home)
        homeward_miles_saved = max(0, current_home - target_home) * route["road_distance_factor"]
        homeward_minutes_saved = homeward_miles_saved / route["average_mph"] * 60
    raw.update(
        zone=zone,
        reposition_minutes=round(route_minutes, 2),
        reposition_miles=round(route_miles, 2),
        expected_wait_minutes=round((1 - raw["p_ride_15m"]) * model["horizon_minutes"], 2),
        homeward_miles_saved=round(homeward_miles_saved, 2),
        homeward_minutes_saved=round(homeward_minutes_saved, 2),
    )
    return Candidate(**raw)


def run_replay(observed_path: Path, model_path: Path) -> dict:
    observed = json.loads(observed_path.read_text(encoding="utf-8"))
    model = json.loads(model_path.read_text(encoding="utf-8"))
    annotations = None
    if model.get("annotations"):
        annotations = json.loads(
            model_path.with_name(model["annotations"]).read_text(encoding="utf-8")
        )
    episodes = decision_episodes(observed, annotations=annotations)
    scenarios = {}
    for cost in model["vehicle_cost_scenarios"]:
        scored_episodes = []
        for episode in episodes:
            if episode["current_zone"] not in model["zones"]:
                continue
            at = datetime.fromisoformat(episode["started_at"])
            candidates = [
                _candidate(zone, episode["current_zone"], at, model) for zone in model["zones"]
            ]
            ranked = rank_candidates(
                candidates,
                episode["current_zone"],
                model["value_of_time_per_hour"],
                cost,
                model["horizon_minutes"],
            )
            recommendation = ranked[0]
            inferred_driver_score = next(
                (score for score in ranked if score.zone == episode["next_observed_pickup_zone"]), None
            )
            scored_episodes.append(
                episode
                | {
                    "recommendation": recommendation.audit(),
                    "runner_up": ranked[1].audit(),
                    "inferred_driver_choice_score": (
                        inferred_driver_score.audit() if inferred_driver_score else None
                    ),
                    "inferred_driver_compliance": (
                        recommendation.zone == episode["next_observed_pickup_zone"]
                    ),
                    "advice_outcome_gradeable": (
                        recommendation.zone == episode["next_observed_pickup_zone"]
                    ),
                }
            )
        scenarios[f"{cost:.2f}"] = scored_episodes

    primary = scenarios[f"{model['vehicle_cost_scenarios'][1]:.2f}"]
    longest = max(episodes, key=lambda item: item["observed_gap_minutes"])
    return {
        "name": "Friday observed decision replay",
        "data_status": "mixed_observed_and_modeled",
        "warning": model["warning"],
        "observed_shift_summary": observed["summary"],
        "decision_episode_count": len(episodes),
        "scored_episode_count": len(primary),
        "longest_gap": longest,
        "cost_scenarios": scenarios,
        "debrief": {
            "observed": {
                "committed_window": observed["committed_window"],
                "trip_count": observed["summary"]["trips"],
                "earnings": observed["summary"]["earnings"],
                "paid_miles": observed["summary"]["paid_miles"],
            },
            "model_evaluation": {
                "inferred_compliant_episodes_at_primary_cost": sum(
                    x["inferred_driver_compliance"] for x in primary
                ),
                "gradeable_advice_episodes": 0,
                "why_not_gradeable": "The export shows the next pickup, not the driver's intent or continuous presence.",
                "counterfactual_policy_results": "not claimed; alternative-zone outcomes were not observed",
                "structural_finding": "Homeward moves need terminal-value credit before scoring the Kirkland closer.",
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay observed gaps through the Farol model")
    parser.add_argument("--observed", type=Path, default=Path("fixtures/friday_observed.json"))
    parser.add_argument("--model", type=Path, default=Path("fixtures/friday_model_v1.json"))
    parser.add_argument("--output", type=Path, default=Path("fixtures/friday_debrief.json"))
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(run_replay(args.observed, args.model), indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
