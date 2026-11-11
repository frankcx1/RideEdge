"""MLB Stats API adapter: Mariners home-game exit waves at T-Mobile Park. Keyless."""

from datetime import UTC, datetime, timedelta

from farol.adapters.base import FeedError, FeedStatus, fetch_json
from farol.signals import Signal

NAME = "mlb_schedule"
SOURCE = "mlb:statsapi.mlb.com"
MARINERS_TEAM_ID = 136
HOME_VENUE = "T-Mobile Park"
ZONE = "sodo_stadiums"
# Exit wave assumptions, stated in the signal details rather than invented downstream.
GAME_DURATION = timedelta(hours=2, minutes=45)
EXIT_WAVE = timedelta(hours=1)
ASSUMED_ATTENDANCE = 30000
TTL_SECONDS = 6 * 60 * 60


def _schedule_url(window_start: datetime, window_end: datetime) -> str:
    start = window_start.date().isoformat()
    end = window_end.date().isoformat()
    return (
        "https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&teamId={MARINERS_TEAM_ID}&startDate={start}&endDate={end}&hydrate=venue"
    )


def parse(
    payload: dict, window_start: datetime, window_end: datetime, *, fetched_at: str
) -> list[Signal]:
    signals = []
    for date_entry in payload.get("dates", []):
        for game in date_entry.get("games", []):
            if game.get("venue", {}).get("name") != HOME_VENUE:
                continue
            if game["teams"]["home"]["team"]["id"] != MARINERS_TEAM_ID:
                continue
            first_pitch = datetime.fromisoformat(game["gameDate"]).astimezone(UTC)
            exit_start = first_pitch + GAME_DURATION
            exit_end = exit_start + EXIT_WAVE
            if exit_end < window_start or exit_start > window_end:
                continue
            away = game["teams"]["away"]["team"]["name"]
            signals.append(
                Signal(
                    id=f"mlb-{game['gamePk']}",
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
                        "title": f"Mariners vs {away} exit at {HOME_VENUE}",
                        "first_pitch": first_pitch.isoformat(),
                        "attendance_basis": "assumed typical draw",
                        "exit_timing_basis": "assumed 2h45m game + 1h exit wave",
                    },
                )
            )
    return signals


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    try:
        payload, mode, fetched_at = fetch_json(
            _schedule_url(window_start, window_end),
            cache_key=f"mlb_{window_start.date().isoformat()}",
            ttl_seconds=TTL_SECONDS,
        )
    except FeedError as error:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, str(error))
    signals = parse(payload, window_start, window_end, fetched_at=fetched_at)
    detail = "" if signals else "no Mariners home-game exits in window"
    return signals, FeedStatus(NAME, mode, SOURCE, fetched_at, len(signals), detail)
