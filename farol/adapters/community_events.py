"""Read the scheduled local Seattle catalog; never start a crawl from a brief."""
from datetime import UTC, datetime

from farol.adapters.base import FeedStatus
from farol.community_events import event_signals, source_status

NAME = "seattle_community_events"
SOURCE = "community:local-calendar"


def fetch(window_start, window_end):
    now = datetime.now(UTC)
    sources = source_status(now=now)
    signals = event_signals(window_start, window_end, now=now)
    ready = [row for row in sources if row["state"] == "ready"]
    checked = max((row.get("last_success") or "" for row in sources), default="") or None
    mode = "cache" if len(ready) == len(sources) else "stale_cache" if checked else "warming"
    return signals, FeedStatus(NAME, mode, SOURCE, checked, len(signals),
                               f"{len(ready)}/{len(sources)} community calendars current; published schedules, ride demand unknown")
