from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise


@dataclass(frozen=True)
class PresenceSample:
    ts: datetime
    observable: bool


@dataclass(frozen=True)
class ClosedEpisode:
    decision_id: str
    actual_zone: str
    recommended_zone: str
    observable: bool
    compliant: bool
    exploration: bool
    reward_net: float
    close_reason: str

    def ledger_updates(self) -> dict:
        return {
            "zone": self.observable,
            "advice": self.observable and self.compliant and not self.exploration,
            "exploration": self.observable and self.compliant and self.exploration,
        }


def interval_is_observable(samples: list[PresenceSample], max_gap_minutes: float = 2.5) -> bool:
    """An interval is learnable only when all samples are good and sampling has no gap."""
    if not samples or not all(sample.observable for sample in samples):
        return False
    ordered = sorted(samples, key=lambda sample: sample.ts)
    return all(
        elapsed_minutes(left.ts, right.ts) <= max_gap_minutes
        for left, right in pairwise(ordered)
    )


def close_reason(
    started_at: datetime,
    now: datetime,
    *,
    accepted_ping: bool = False,
    exited_recommended_zone: bool = False,
    new_plan: bool = False,
) -> str | None:
    if accepted_ping:
        return "accepted_ping"
    if exited_recommended_zone:
        return "exited_recommended_zone"
    if new_plan:
        return "new_plan"
    if elapsed_minutes(started_at, now) >= 20:
        return "expired"
    return None


def elapsed_minutes(started_at: datetime, ended_at: datetime) -> float:
    return (ended_at - started_at).total_seconds() / 60
