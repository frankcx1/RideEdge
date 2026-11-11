"""Port of Seattle cruise schedule adapter.

The Port publishes the season schedule only as a PDF, so this adapter reads a
locally seeded JSON copy (fixtures/cruise_schedule_2026.json) and treats it as
`scheduled` basis with the seed date as its source timestamp. Reseed once per
season or when the Port revises the schedule.
"""

import json
from datetime import datetime, timedelta

from farol.adapters.base import FeedStatus
from farol.dashboard import FIXTURES
from farol.signals import Signal

NAME = "cruise_schedule"
SOURCE = "port_of_seattle:seeded schedule file"
SCHEDULE_PATH = FIXTURES / "cruise_schedule_2026.json"

TERMINAL_ZONES = {
    "Pier 66": "belltown",
    "Terminal 91": "interbay",
}
# Disembark pressure is a morning phenomenon at both terminals.
DISEMBARK_START_HOUR = 7
DISEMBARK_END_HOUR = 10


def parse(
    payload: dict, window_start: datetime, window_end: datetime, *, fetched_at: str
) -> list[Signal]:
    tz = window_start.tzinfo
    signals = []
    for call in payload.get("ship_calls", []):
        day = datetime.fromisoformat(call["date"]).replace(tzinfo=tz)
        starts = day + timedelta(hours=DISEMBARK_START_HOUR)
        ends = day + timedelta(hours=DISEMBARK_END_HOUR)
        if ends < window_start or starts > window_end:
            continue
        terminal = call.get("terminal", "Pier 66")
        signals.append(
            Signal(
                id=f"cruise-{call['date']}-{call.get('ship', 'ship').replace(' ', '-')}",
                kind="cruise_disembark",
                zone=TERMINAL_ZONES.get(terminal, "waterfront"),
                starts_at=starts.isoformat(),
                ends_at=ends.isoformat(),
                magnitude=float(call.get("passengers", 2500)),
                basis="scheduled",
                source=SOURCE,
                fetched_at=fetched_at,
                expires_at=ends.isoformat(),
                evidence_quality=0.7,
                details={
                    "title": f"{call.get('ship', 'Cruise ship')} disembark at {terminal}",
                    "passenger_basis": call.get("passenger_basis", "schedule estimate"),
                    "timing_basis": "assumed 7-10 AM disembark window",
                },
            )
        )
    return signals


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    if not SCHEDULE_PATH.exists():
        return [], FeedStatus(NAME, "static", SOURCE, None, 0, "schedule file missing")
    payload = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    seeded_at = payload.get("seeded_at")
    if not payload.get("ship_calls"):
        detail = "schedule file not yet seeded from the Port's published PDF"
        return [], FeedStatus(NAME, "static", SOURCE, seeded_at, 0, detail)
    signals = parse(payload, window_start, window_end, fetched_at=seeded_at or "")
    detail = "" if signals else "no ship calls in window"
    return signals, FeedStatus(NAME, "static", SOURCE, seeded_at, len(signals), detail)
