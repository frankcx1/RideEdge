"""NWS hourly forecast adapter: precipitation onset as a live signal. Keyless."""

import os
from datetime import datetime, timedelta

from farol.adapters.base import FeedError, FeedStatus, fetch_json
from farol.signals import Signal

NAME = "nws_hourly"
SOURCE = "nws:SEW gridpoint 124,69"
# Stable gridpoint for the Seattle operating area; override if the home area moves.
DEFAULT_HOURLY_URL = "https://api.weather.gov/gridpoints/SEW/124,69/forecast/hourly"
RAIN_THRESHOLD_PERCENT = 40
TTL_SECONDS = 30 * 60


def _hourly_url() -> str:
    return os.getenv("FAROL_NWS_HOURLY_URL", "").strip() or DEFAULT_HOURLY_URL


def parse(
    payload: dict, window_start: datetime, window_end: datetime, *, fetched_at: str
) -> list[Signal]:
    periods = payload.get("properties", {}).get("periods", [])
    runs: list[list[dict]] = []
    for period in periods:
        probability = (period.get("probabilityOfPrecipitation") or {}).get("value") or 0
        starts = datetime.fromisoformat(period["startTime"])
        ends = datetime.fromisoformat(period["endTime"])
        in_window = ends >= window_start and starts <= window_end
        if probability >= RAIN_THRESHOLD_PERCENT and in_window:
            if runs and runs[-1][-1]["endTime"] == period["startTime"]:
                runs[-1].append(period)
            else:
                runs.append([period])
    signals = []
    for run in runs:
        peak = max(
            (item.get("probabilityOfPrecipitation") or {}).get("value") or 0 for item in run
        )
        starts_at = run[0]["startTime"]
        onset = datetime.fromisoformat(starts_at)
        signals.append(
            Signal(
                id=f"nws-rain-{starts_at}",
                kind="precipitation",
                zone="all",
                starts_at=starts_at,
                ends_at=run[-1]["endTime"],
                magnitude=float(peak),
                basis="live",
                source=SOURCE,
                fetched_at=fetched_at,
                expires_at=(onset + timedelta(hours=6)).isoformat(),
                evidence_quality=0.85,
                details={
                    "title": f"Rain {peak}% from {onset.strftime('%I:%M %p').lstrip('0')}",
                    "probability_percent": peak,
                    "forecast_updated": payload.get("properties", {}).get("updateTime"),
                },
            )
        )
    return signals


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    try:
        payload, mode, fetched_at = fetch_json(
            _hourly_url(), cache_key="nws_hourly", ttl_seconds=TTL_SECONDS
        )
    except FeedError as error:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, str(error))
    signals = parse(payload, window_start, window_end, fetched_at=fetched_at)
    detail = "" if signals else f"no precipitation ≥{RAIN_THRESHOLD_PERCENT}% in window"
    return signals, FeedStatus(NAME, mode, SOURCE, fetched_at, len(signals), detail)
