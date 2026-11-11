from collections.abc import Iterable
from dataclasses import asdict, dataclass
from math import sqrt


@dataclass(frozen=True)
class Candidate:
    zone: str
    p_ride_15m: float
    expected_gross_earnings: float
    expected_trip_miles: float
    reposition_minutes: float
    reposition_miles: float
    expected_wait_minutes: float
    confidence: float
    basis: str
    prior_pseudo_count: float = 0
    homeward_minutes_saved: float = 0
    homeward_miles_saved: float = 0

    def __post_init__(self) -> None:
        if not 0 <= self.p_ride_15m <= 1:
            raise ValueError("p_ride_15m must be between 0 and 1")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        numeric = (
            self.expected_gross_earnings,
            self.expected_trip_miles,
            self.reposition_minutes,
            self.reposition_miles,
            self.expected_wait_minutes,
            self.prior_pseudo_count,
            self.homeward_minutes_saved,
            self.homeward_miles_saved,
        )
        if any(value < 0 for value in numeric):
            raise ValueError("candidate costs, times, miles, and pseudo-counts cannot be negative")
        if not self.basis.strip():
            raise ValueError("candidate basis is required for auditability")


@dataclass(frozen=True)
class Score:
    zone: str
    action: str
    expected_episode_net: float
    expected_dollars_per_hour: float
    expected_gross_earnings: float
    expected_net_fare_if_ride: float
    expected_vehicle_cost: float
    reposition_cost: float
    wait_cost: float
    homeward_credit: float
    confidence: float
    basis: str
    inputs: dict

    def audit(self) -> dict:
        return asdict(self)


def score_candidate(
    candidate: Candidate,
    current_zone: str,
    value_of_time_per_hour: float,
    vehicle_cost_per_mile: float,
    horizon_minutes: float = 15,
) -> Score:
    """Score one horizon and retain every input used to display a number."""
    if value_of_time_per_hour < 0 or vehicle_cost_per_mile < 0:
        raise ValueError("time and vehicle costs cannot be negative")
    if horizon_minutes <= 0:
        raise ValueError("horizon_minutes must be positive")

    dollars_per_minute = value_of_time_per_hour / 60
    trip_vehicle_cost = candidate.expected_trip_miles * vehicle_cost_per_mile
    net_fare_if_ride = candidate.expected_gross_earnings - trip_vehicle_cost
    reposition_vehicle_cost = candidate.reposition_miles * vehicle_cost_per_mile
    reposition_time_cost = candidate.reposition_minutes * dollars_per_minute
    reposition_cost = reposition_vehicle_cost + reposition_time_cost
    wait_cost = candidate.expected_wait_minutes * dollars_per_minute
    homeward_credit = (
        candidate.homeward_minutes_saved * dollars_per_minute
        + candidate.homeward_miles_saved * vehicle_cost_per_mile
    )
    expected_vehicle_cost = reposition_vehicle_cost + candidate.p_ride_15m * trip_vehicle_cost
    episode_net = (
        candidate.p_ride_15m * net_fare_if_ride
        - reposition_cost
        - wait_cost
        + homeward_credit
    )

    inputs = asdict(candidate) | {
        "current_zone": current_zone,
        "value_of_time_per_hour": value_of_time_per_hour,
        "vehicle_cost_per_mile": vehicle_cost_per_mile,
        "horizon_minutes": horizon_minutes,
    }
    return Score(
        zone=candidate.zone,
        action="STAY" if candidate.zone == current_zone else "MOVE",
        expected_episode_net=round(episode_net, 2),
        expected_dollars_per_hour=round(episode_net * 60 / horizon_minutes, 2),
        expected_gross_earnings=round(candidate.expected_gross_earnings, 2),
        expected_net_fare_if_ride=round(net_fare_if_ride, 2),
        expected_vehicle_cost=round(expected_vehicle_cost, 2),
        reposition_cost=round(reposition_cost, 2),
        wait_cost=round(wait_cost, 2),
        homeward_credit=round(homeward_credit, 2),
        confidence=round(candidate.confidence, 3),
        basis=candidate.basis,
        inputs=inputs,
    )


def rank_candidates(
    candidates: Iterable[Candidate],
    current_zone: str,
    value_of_time_per_hour: float,
    vehicle_cost_per_mile: float,
    horizon_minutes: float = 15,
) -> list[Score]:
    scores = [
        score_candidate(
            candidate,
            current_zone,
            value_of_time_per_hour,
            vehicle_cost_per_mile,
            horizon_minutes,
        )
        for candidate in candidates
    ]
    if not scores:
        raise ValueError("at least one candidate is required")
    return sorted(scores, key=lambda score: score.expected_episode_net, reverse=True)


def beta_confidence(a: float, b: float) -> float:
    """Transparent confidence proxy: 1 minus twice posterior stddev."""
    if a <= 0 or b <= 0:
        raise ValueError("beta parameters must be positive")
    variance = (a * b) / (((a + b) ** 2) * (a + b + 1))
    return max(0.0, min(1.0, 1 - 2 * sqrt(variance)))


def select_shift(
    expected_gross: float,
    expected_miles: float,
    committed_minutes: float,
    value_of_time_per_hour: float,
    vehicle_cost_per_mile: float,
) -> dict:
    if committed_minutes <= 0:
        raise ValueError("committed_minutes must be positive")
    expected_vehicle_cost = expected_miles * vehicle_cost_per_mile
    expected_net = expected_gross - expected_vehicle_cost
    hourly = expected_net * 60 / committed_minutes
    return {
        "action": "DRIVE" if hourly >= value_of_time_per_hour else "SKIP",
        "expected_gross": round(expected_gross, 2),
        "expected_vehicle_cost": round(expected_vehicle_cost, 2),
        "expected_net": round(expected_net, 2),
        "committed_minutes": committed_minutes,
        "expected_return_per_hour": round(hourly, 2),
        "value_of_time_per_hour": value_of_time_per_hour,
        "vehicle_cost_per_mile": vehicle_cost_per_mile,
    }
