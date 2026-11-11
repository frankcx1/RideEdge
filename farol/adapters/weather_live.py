"""NWS live station observation adapter: active rain & cold walk-refusal spikes.

Forecast probability (>=40% in nws.py) does not distinguish mist from an active
downpour or a cold 40F windy evening when diners and bar patrons refuse to walk
six blocks or wait at an exposed bus stop. Queries KBFI (Seattle Boeing Field)
latest observation (keyless api.weather.gov).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from farol.adapters.base import FeedError, FeedStatus, fetch_json
from farol.evidence import parse_time
from farol.signals import Signal

NAME = "nws_live_observation"
SOURCE = "nws:station KBFI live observation"
DEFAULT_OBS_URL = "https://api.weather.gov/stations/KBFI/observations/latest"
TTL_SECONDS = 15 * 60


def _obs_url() -> str:
    return os.getenv("FAROL_NWS_OBS_URL", "").strip() or DEFAULT_OBS_URL


def _c_to_f(celsius: float | None) -> float | None:
    if celsius is None:
        return None
    return round(celsius * 9.0 / 5.0 + 32.0, 1)


def parse(
    payload: dict,
    window_start: datetime,
    window_end: datetime,
    *,
    fetched_at: str,
) -> list[Signal]:
    if not isinstance(payload, dict):
        return []
    props = payload.get("properties") or {}
    desc = str(props.get("textDescription") or "").strip()
    desc_lower = desc.lower()
    temp_c = (props.get("temperature") or {}).get("value")
    chill_c = (props.get("windChill") or {}).get("value")
    wind_kmh = (props.get("windSpeed") or {}).get("value")
    precip_m = (props.get("precipitationLastHour") or {}).get("value")

    temp_f = _c_to_f(float(temp_c)) if isinstance(temp_c, (int, float)) else None
    chill_f = _c_to_f(float(chill_c)) if isinstance(chill_c, (int, float)) else None
    wind_mph = round(float(wind_kmh) * 0.621371, 1) if isinstance(wind_kmh, (int, float)) else 0.0
    precip_mm = round(float(precip_m) * 1000.0, 2) if isinstance(precip_m, (int, float)) else 0.0

    active_rain = precip_mm > 0.1 or any(
        w in desc_lower for w in ("rain", "shower", "downpour", "drizzle", "snow", "storm")
    )
    raw_obs_ts = props.get("timestamp")
    obs_dt = parse_time(raw_obs_ts) if raw_obs_ts else parse_time(fetched_at)
    if obs_dt is None or obs_dt.tzinfo is None or window_start.tzinfo is None:
        return []
    local_obs = obs_dt.astimezone(window_start.tzinfo)
    # R12: Reject stale weather observations (> 90 minutes older than window_start or after window_end)
    if local_obs < window_start - timedelta(minutes=90) or local_obs > window_end:
        return []
    is_evening_or_night = local_obs.hour >= 17 or local_obs.hour < 4
    effective_f = chill_f if chill_f is not None else temp_f
    cold_walk_refusal = (
        is_evening_or_night
        and effective_f is not None
        and (effective_f <= 43.0 or (effective_f <= 47.0 and wind_mph >= 12.0))
    )

    if not active_rain and not cold_walk_refusal:
        return []

    starts = max(window_start, obs_dt.astimezone(window_start.tzinfo))
    ends = min(window_end, obs_dt.astimezone(window_start.tzinfo) + timedelta(hours=2))
    if ends <= starts:
        return []

    if active_rain:
        mag = 75.0 if precip_mm >= 1.5 or "heavy" in desc_lower else 55.0
        temp_str = f", {temp_f:.0f}°F" if temp_f is not None else ""
        title = f"Active {desc or 'Rain'} right now ({precip_mm:.1f} mm/hr{temp_str}) — short-ride walk refusal spike"
    else:
        mag = 45.0
        title = (
            f"Chilly evening walk-refusal weather ({effective_f:.0f}°F feels-like, "
            f"{wind_mph:.0f} mph wind) — diners & bar exits favor rideshare over walking"
        )

    return [
        Signal(
            id=f"nws-live-obs-{window_start.strftime('%Y%m%d%H')}",
            kind="precipitation",
            zone="all",
            starts_at=starts.isoformat(),
            ends_at=ends.isoformat(),
            magnitude=mag,
            basis="live",
            source=SOURCE,
            fetched_at=fetched_at,
            expires_at=ends.isoformat(),
            evidence_quality=0.88,
            details={
                "title": title,
                "description": (
                    f"KBFI live station: {desc or 'Observed'}, temp {temp_f}°F, "
                    f"wind {wind_mph} mph, precip {precip_mm} mm/hr."
                ),
                "temperature_f": temp_f,
                "wind_mph": wind_mph,
                "precip_mm_last_hour": precip_mm,
                "active_rain": active_rain,
                "cold_walk_refusal": cold_walk_refusal,
            },
        )
    ]


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    try:
        payload, mode, fetched_at = fetch_json(
            _obs_url(), cache_key="nws_kbfi_latest", ttl_seconds=TTL_SECONDS
        )
    except FeedError as error:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, str(error)[:240])
    signals = parse(payload, window_start, window_end, fetched_at=fetched_at)
    detail = "active rain/cold walk-refusal spike" if signals else "clear/mild walking conditions at KBFI"
    return signals, FeedStatus(NAME, mode, SOURCE, fetched_at, len(signals), detail)
