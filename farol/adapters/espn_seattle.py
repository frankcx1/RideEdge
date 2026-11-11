"""ESPN public scoreboard adapter: Seattle home exits. Keyless.

Covers Seahawks, Sounders, Storm, and Washington Huskies (Husky Stadium).
Venue match is a substring so 'Alaska Airlines Field at Husky Stadium' still hits.
"""

from datetime import datetime, timedelta

from farol.adapters.base import FeedError, FeedStatus, fetch_json
from farol.signals import Signal
from farol.zones import canonical_zone

NAME = "espn_seattle"
SOURCE = "espn:site.api.espn.com"
TTL_SECONDS = 6 * 60 * 60

LEAGUES = (
    {
        "sport": "nfl",
        "url": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        "home_venue": "Lumen Field",
        "zone": "sodo_stadiums",
        "duration": timedelta(hours=3, minutes=15),
        "exit_wave": timedelta(hours=1),
        "attendance": 68740,
        "home_name": "Seahawks",
    },
    {
        "sport": "mls",
        "url": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard",
        "home_venue": "Lumen Field",
        "zone": "sodo_stadiums",
        "duration": timedelta(hours=2, minutes=10),
        "exit_wave": timedelta(minutes=50),
        "attendance": 32000,
        "home_name": "Sounders",
    },
    {
        "sport": "wnba",
        "url": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
        "home_venue": "Climate Pledge Arena",
        "zone": "seattle_center",
        "duration": timedelta(hours=2, minutes=10),
        "exit_wave": timedelta(minutes=45),
        "attendance": 18000,
        "home_name": "Storm",
    },
    {
        "sport": "ncaaf",
        "url": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
        "home_venue": "Husky Stadium",
        "zone": "uw_district",
        "duration": timedelta(hours=3, minutes=30),
        "exit_wave": timedelta(hours=1),
        "attendance": 70000,
        "home_name": "Huskies",
    },
)


def _dates(window_start: datetime, window_end: datetime) -> list[str]:
    # These scoreboards reject YYYYMMDD-YYYYMMDD with HTTP 400. Fetch days
    # individually so an evening window crossing midnight still works.
    day = window_start.date()
    dates = []
    while day <= window_end.date():
        dates.append(day.strftime("%Y%m%d"))
        day += timedelta(days=1)
    return dates


def parse(
    payload: dict,
    window_start: datetime,
    window_end: datetime,
    *,
    fetched_at: str,
    league: dict,
) -> list[Signal]:
    signals = []
    for event in payload.get("events") or []:
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        game = competitions[0]
        venue = (game.get("venue") or {}).get("fullName") or ""
        if league["home_venue"].lower() not in venue.lower():
            continue
        home = next(
            (
                competitor
                for competitor in game.get("competitors") or []
                if competitor.get("homeAway") == "home"
            ),
            None,
        )
        if home is None or league["home_name"] not in (home.get("team") or {}).get(
            "displayName", ""
        ):
            continue
        kickoff = datetime.fromisoformat(event["date"])
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=window_start.tzinfo)
        exit_start = kickoff.astimezone(window_start.tzinfo) + league["duration"]
        exit_end = exit_start + league["exit_wave"]
        if exit_end < window_start or exit_start > window_end:
            continue
        away = next(
            (
                competitor.get("team", {}).get("displayName", "opponent")
                for competitor in game.get("competitors") or []
                if competitor.get("homeAway") == "away"
            ),
            "opponent",
        )
        zone = canonical_zone(league["zone"])
        signals.append(
            Signal(
                id=f"espn-{league['sport']}-{event.get('id', exit_start.isoformat())}",
                kind="event_exit",
                zone=zone,
                starts_at=exit_start.isoformat(),
                ends_at=exit_end.isoformat(),
                magnitude=float(league["attendance"]),
                basis="scheduled",
                source=SOURCE,
                fetched_at=fetched_at,
                expires_at=exit_end.isoformat(),
                evidence_quality=0.78,
                details={
                    "title": f"{league['home_name']} vs {away} exit at {venue}",
                    "kickoff": kickoff.isoformat(),
                    "attendance_basis": "assumed typical home draw",
                    "exit_timing_basis": (
                        f"assumed {league['duration']} game + {league['exit_wave']} exit wave"
                    ),
                },
            )
        )
    return signals


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    all_signals: list[Signal] = []
    modes: list[str] = []
    fetched_at = ""
    errors: list[str] = []
    for league, dates in ((league, day) for league in LEAGUES for day in _dates(window_start, window_end)):
        url = f"{league['url']}?dates={dates}&limit=50"
        try:
            payload, mode, fetched_at = fetch_json(
                url,
                cache_key=f"espn_{league['sport']}_{dates}",
                ttl_seconds=TTL_SECONDS,
            )
        except FeedError as error:
            errors.append(f"{league['sport']}: {error}")
            continue
        modes.append(mode)
        if isinstance(payload, dict):
            all_signals.extend(
                parse(
                    payload,
                    window_start,
                    window_end,
                    fetched_at=fetched_at,
                    league=league,
                )
            )
    if not modes and errors:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, "; ".join(errors))
    mode = "stale_cache" if "stale_cache" in modes else ("cache" if set(modes) == {"cache"} else "live")
    detail = "" if all_signals else "no Seattle home-game exits in window"
    if errors:
        detail = (detail + "; " if detail else "") + "; ".join(errors)
    # A league may return an adjacent-day game in both scoreboard responses.
    all_signals = list({signal.id: signal for signal in all_signals}.values())
    return all_signals, FeedStatus(NAME, mode, SOURCE, fetched_at or None, len(all_signals), detail)
