"""SEA FIFO is a separate game from street heat.

Staging and arrival-bank facts are public folklore (Solo's Sea-Tac Insights
plus Eastside driver reports), not Uber's queue API. Do not mix this board
with Kirkland/Bellevue street ranking.
"""

from datetime import datetime, timedelta

from farol.adapters.base import FeedStatus
from farol.signals import Signal

NAME = "sea_fifo"
SOURCE = "farol:SEA FIFO module (Solo staging facts + doctrine)"
# Cell-phone / FIFO lot, not a street-hail pin.
STAGING_LABEL = "SEA staging lot, 3037 S 160th St"
PICKUP_LABEL = "Garage level 3, stalls 1–34"
AFTERNOON_BANK = (11, 15)  # heaviest midday arrivals ~11:00–15:00
EVENING_BANK = ((17, 30), (23, 0))  # transcon & West Coast evening arrival bank ~17:30–23:00
SLOW_MONTHS = {1, 2}


def parse(window_start: datetime, window_end: datetime, *, fetched_at: str) -> list[Signal]:
    tz = window_start.tzinfo
    day = datetime(window_start.year, window_start.month, window_start.day, tzinfo=tz)
    last = datetime(window_end.year, window_end.month, window_end.day, tzinfo=tz)
    signals: list[Signal] = []
    while day <= last:
        start = day.replace(hour=AFTERNOON_BANK[0], minute=0, second=0, microsecond=0)
        end = day.replace(hour=AFTERNOON_BANK[1], minute=0, second=0, microsecond=0)
        if not (end < window_start or start > window_end):
            slow = day.month in SLOW_MONTHS
            magnitude = 4.0 if slow else 9.0
            title = (
                "SEA FIFO afternoon arrival bank (Jan–Feb typically thin)"
                if slow
                else "SEA FIFO afternoon arrival bank (heaviest ~11:00–15:00)"
            )
            signals.append(
                Signal(
                    id=f"sea-fifo-afternoon-{day.date().isoformat()}",
                    kind="airport_arrivals",
                    zone="sea_airport",
                    starts_at=start.isoformat(),
                    ends_at=end.isoformat(),
                    magnitude=magnitude,
                    basis="assumed",
                    source=SOURCE,
                    fetched_at=fetched_at,
                    expires_at=end.isoformat(),
                    evidence_quality=0.55 if not slow else 0.4,
                    details={
                        "title": title,
                        "staging": STAGING_LABEL,
                        "pickup": PICKUP_LABEL,
                        "game": "fifo",
                        "notes": (
                            "Queue vs street is a different decision than Eastside bars. "
                            "Do not leave Kirkland for a purple airport tile without an arrival bank."
                        ),
                    },
                )
            )
        eve_start = day.replace(
            hour=EVENING_BANK[0][0], minute=EVENING_BANK[0][1], second=0, microsecond=0
        )
        eve_end = day.replace(
            hour=EVENING_BANK[1][0], minute=EVENING_BANK[1][1], second=0, microsecond=0
        )
        if not (eve_end < window_start or eve_start > window_end):
            slow = day.month in SLOW_MONTHS
            eve_mag = 4.5 if slow else 9.5
            eve_title = (
                "SEA FIFO evening transcon & West Coast arrival bank (Jan–Feb thin)"
                if slow
                else "SEA FIFO evening transcon & West Coast arrival bank (~5:30 PM–11:00 PM)"
            )
            signals.append(
                Signal(
                    id=f"sea-fifo-evening-{day.date().isoformat()}",
                    kind="airport_arrivals",
                    zone="sea_airport",
                    starts_at=eve_start.isoformat(),
                    ends_at=eve_end.isoformat(),
                    magnitude=eve_mag,
                    basis="assumed",
                    source=SOURCE,
                    fetched_at=fetched_at,
                    expires_at=eve_end.isoformat(),
                    evidence_quality=0.6 if not slow else 0.45,
                    details={
                        "title": eve_title,
                        "staging": STAGING_LABEL,
                        "pickup": PICKUP_LABEL,
                        "game": "fifo",
                        "notes": (
                            "Evening transcontinental and West Coast return wave at Sea-Tac. "
                            "High proportion of Eastside (Bellevue/Kirkland/Redmond) and Downtown hotel fares."
                        ),
                    },
                )
            )
        day += timedelta(days=1)
    return signals


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    fetched_at = window_start.isoformat()
    signals = parse(window_start, window_end, fetched_at=fetched_at)
    return signals, FeedStatus(
        NAME,
        "static",
        SOURCE,
        fetched_at,
        len(signals),
        "SEA FIFO module; not mixed with street ranking",
    )
