"""NHL API adapter: Kraken home-game exit waves at Climate Pledge Arena. Keyless."""

from datetime import UTC, datetime, timedelta

from farol.adapters.base import FeedError, FeedStatus, fetch_json
from farol.signals import Signal

NAME = "nhl_schedule"
SOURCE = "nhl:api-web.nhle.com"
TEAM = "SEA"
ZONE = "seattle_center"
GAME_DURATION = timedelta(hours=2, minutes=30)
EXIT_WAVE = timedelta(minutes=45)
ASSUMED_ATTENDANCE = 17000
TTL_SECONDS = 6 * 60 * 60


def season_code(window_start: datetime) -> str:
    year = window_start.year
    return f"{year}{year + 1}" if window_start.month >= 7 else f"{year - 1}{year}"


def _schedule_url(window_start: datetime) -> str:
    return f"https://api-web.nhle.com/v1/club-schedule-season/{TEAM}/{season_code(window_start)}"


def parse(
    payload: dict, window_start: datetime, window_end: datetime, *, fetched_at: str
) -> list[Signal]:
    signals = []
    for game in payload.get("games", []):
        if game.get("homeTeam", {}).get("abbrev") != TEAM:
            continue
        start = datetime.fromisoformat(game["startTimeUTC"]).astimezone(UTC)
        exit_start = start + GAME_DURATION
        exit_end = exit_start + EXIT_WAVE
        if exit_end < window_start or exit_start > window_end:
            continue
        away = game.get("awayTeam", {}).get("abbrev", "?")
        signals.append(
            Signal(
                id=f"nhl-{game['id']}",
                kind="event_exit",
                zone=ZONE,
                starts_at=exit_start.isoformat(),
                ends_at=exit_end.isoformat(),
                magnitude=float(ASSUMED_ATTENDANCE),
                basis="scheduled",
                source=SOURCE,
                fetched_at=fetched_at,
                expires_at=exit_end.isoformat(),
                evidence_quality=0.75,
                details={
                    "title": f"Kraken vs {away} exit at Climate Pledge Arena",
                    "puck_drop": start.isoformat(),
                    "attendance_basis": "assumed typical draw",
                    "exit_timing_basis": "assumed 2h30m game + 45m exit wave",
                },
            )
        )
    return signals


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    try:
        payload, mode, fetched_at = fetch_json(
            _schedule_url(window_start),
            cache_key=f"nhl_{season_code(window_start)}",
            ttl_seconds=TTL_SECONDS,
        )
    except FeedError as error:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, str(error))
    signals = parse(payload, window_start, window_end, fetched_at=fetched_at)
    detail = "" if signals else "no Kraken home-game exits in window"
    return signals, FeedStatus(NAME, mode, SOURCE, fetched_at, len(signals), detail)
