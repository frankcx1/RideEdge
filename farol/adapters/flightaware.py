"""FlightAware AeroAPI: live KSEA arrival density on the FIFO board.

Metered Personal tier. Collector and Tonight Brief never poll. SEA FIFO / HERE
at SEA spends on demand: two result sets (up to 30 flights) covering the next
90 minutes, scored as planes/hour — not "15 in three hours." Street ranking
never sees this zone.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta, timezone
from threading import Lock
from urllib.parse import urlencode

from farol.adapters.base import FeedError, FeedStatus, fetch_json
from farol.evidence import format_clock
from farol.signals import Signal

NAME = "flightaware_sea"
SOURCE = "flightaware:aeroapi airports/KSEA/flights/arrivals"
ARRIVALS_URL = "https://aeroapi.flightaware.com/aeroapi/airports/KSEA/flights/arrivals"
SCHEDULED_ARRIVALS_URL = "https://aeroapi.flightaware.com/aeroapi/airports/KSEA/flights/scheduled_arrivals"
TTL_SECONDS = 15 * 60
FORECAST_TTL_SECONDS = 30 * 60
LONG_HAUL_ORIGINS = frozenset({
    "FCO", "IST", "DUB", "MUC", "LHR", "CDG", "FRA", "AMS", "HEL", "ZRH",
    "ICN", "NRT", "HND", "TPE", "SIN", "MNL", "PVG", "PEK", "HKG", "DOH", "DXB",
    "JFK", "EWR", "BOS", "IAD", "DCA", "BWI", "MIA", "FLL", "MCO", "ATL", "CLT",
    "DFW", "IAH", "ORD", "DTW", "MSP", "PHL", "HNL", "OGG", "KOA", "LIH", "ANC",
})
MIN_FLIGHTS = 3
PAGE_SIZE = 15
DEMAND_PAGES = 2
LOOKBACK_MINUTES = 30
WAVE_AHEAD_MINUTES = 90


def _api_key() -> str:
    return os.getenv("FLIGHTAWARE_API_KEY", "").strip()


def _origin_code(flight: dict) -> str:
    origin = flight.get("origin") or {}
    code = (origin.get("code_iata") or origin.get("code")) if isinstance(origin, dict) else origin
    raw = str(code or "").strip().upper()
    if len(raw) == 4 and raw.startswith("K"):
        return raw[1:]
    return raw or "?"


def _in_window(stamp: datetime, start: datetime, end: datetime) -> bool:
    return start <= stamp <= end


def _parse_when(flight: dict) -> datetime | None:
    for field in ("estimated_in", "actual_in", "scheduled_in"):
        raw = flight.get(field)
        if not raw:
            continue
        try:
            stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        return stamp
    return None


def overlaps_sea_banks(window_start: datetime, window_end: datetime) -> bool:
    """True if the window includes afternoon 11–15 or morning 04:45–09:30 local."""
    cursor = window_start.replace(minute=0, second=0, microsecond=0)
    while cursor <= window_end:
        hour = cursor.hour
        minute = cursor.minute
        if 11 <= hour < 16:
            return True
        if hour == 4 and minute >= 45:
            return True
        if 5 <= hour < 10:
            return True
        cursor += timedelta(minutes=15)
        if cursor.hour == window_start.hour and cursor.date() > window_end.date():
            break
        if (cursor - window_start) > timedelta(hours=36):
            break
    return False


def _utc_iso(stamp: datetime) -> str:
    return stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _per_hour(count: int, first: datetime, last: datetime) -> float:
    span_minutes = max((last - first).total_seconds() / 60.0, 1.0)
    return round(count / (span_minutes / 60.0), 1)


def _magnitude(per_hour: float, page_full: bool) -> float:
    if per_hour >= 24:
        mag = 12.0
    elif per_hour >= 18:
        mag = 10.0
    elif per_hour >= 14:
        mag = 8.0
    elif per_hour >= 9:
        mag = 6.0
    else:
        mag = 4.0
    if page_full and per_hour >= 18:
        mag = min(12.0, mag + 1)
    return mag


def _pace_title(count: int, first: datetime, last: datetime, per_hour: float, page_full: bool) -> str:
    clocks = f"{format_clock(first)}–{format_clock(last)}"
    title = f"{count} planes landing {clocks} (~{per_hour:.0f} per hour)"
    if page_full and per_hour >= 14:
        return title + " — snapshot full, inbound is stacked"
    if page_full:
        return title + " — snapshot full, but they're spread out (not a dump)"
    return title


def parse(
    payload: dict,
    window_start: datetime,
    window_end: datetime,
    *,
    fetched_at: str,
    page_limit: int = 1,
) -> list[Signal]:
    arrivals = payload.get("arrivals") or []
    in_window = []
    for flight in arrivals:
        if not isinstance(flight, dict):
            continue
        when = _parse_when(flight)
        if when is None:
            continue
        local = when.astimezone(window_start.tzinfo)
        if _in_window(local, window_start, window_end):
            in_window.append((local, str(flight.get("ident") or "?"), _origin_code(flight)))
    if len(in_window) < MIN_FLIGHTS:
        return []
    in_window.sort(key=lambda item: item[0])
    first = in_window[0][0]
    last = in_window[-1][0]
    count = len(in_window)
    cap = PAGE_SIZE * max(1, page_limit)
    has_more = bool((payload.get("links") or {}).get("next"))
    page_full = len(arrivals) >= cap or has_more
    per_hour = _per_hour(count, first, last)
    span_minutes = int(round(max((last - first).total_seconds() / 60.0, 1.0)))
    flights = [
        {"at": when.isoformat(), "ident": ident, "origin": origin}
        for when, ident, origin in in_window
    ]
    title = _pace_title(count, first, last, per_hour, page_full)
    return [
        Signal(
            id=f"fa-sea-{first.strftime('%Y%m%d%H%M')}",
            kind="airport_arrivals",
            zone="sea_airport",
            starts_at=first.isoformat(),
            ends_at=(last + timedelta(minutes=20)).isoformat(),
            magnitude=_magnitude(per_hour, page_full),
            basis="live",
            source=SOURCE,
            fetched_at=fetched_at,
            expires_at=(last + timedelta(minutes=20)).isoformat(),
            evidence_quality=0.8,
            details={
                "title": title,
                "count": count,
                "per_hour": per_hour,
                "span_minutes": span_minutes,
                "page_full": page_full,
                "page_size": PAGE_SIZE,
                "pages": max(1, page_limit),
                "flights": flights,
                "game": "fifo",
                "notes": (
                    "Airport pickup queue only. Farol cannot see how many Uber cars "
                    "are already in line. On-demand pull is two pages (up to 30 planes) "
                    "in the next 90 minutes, scored as planes/hour."
                ),
            },
        )
    ]


def fetch(
    window_start: datetime,
    window_end: datetime,
    *,
    demand: bool = False,
) -> tuple[list[Signal], FeedStatus]:
    key = _api_key()
    if not key:
        return [], FeedStatus(
            NAME,
            "needs_key",
            "env:FLIGHTAWARE_API_KEY",
            None,
            0,
            "set FLIGHTAWARE_API_KEY — AeroAPI KSEA arrivals",
        )
    if not demand:
        bank = (
            "in SEA arrival bank; "
            if overlaps_sea_banks(window_start, window_end)
            else "outside SEA arrival banks; "
        )
        return [], FeedStatus(
            NAME,
            "static",
            SOURCE,
            None,
            0,
            f"{bank}AeroAPI on-demand — HERE at SEA to fetch",
        )
    parse_start = window_start - timedelta(minutes=LOOKBACK_MINUTES)
    parse_end = min(window_end, window_start + timedelta(minutes=WAVE_AHEAD_MINUTES))
    query = urlencode(
        {
            "max_pages": DEMAND_PAGES,
            "start": _utc_iso(parse_start),
            "end": _utc_iso(parse_end),
        }
    )
    try:
        payload, mode, fetched_at = fetch_json(
            f"{ARRIVALS_URL}?{query}",
            cache_key="flightaware_ksea_arrivals_p2",
            ttl_seconds=TTL_SECONDS,
            headers={"x-apikey": key, "Accept": "application/json"},
        )
    except FeedError as error:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, str(error)[:300])
    if not isinstance(payload, dict):
        return [], FeedStatus(NAME, "error", SOURCE, fetched_at, 0, "unexpected payload")
    signals = parse(
        payload,
        parse_start,
        parse_end,
        fetched_at=fetched_at,
        page_limit=DEMAND_PAGES,
    )
    n = len(payload.get("arrivals") or [])
    detail = (
        f"{len(signals)} live bank(s) from {n} KSEA arrivals "
        f"(max_pages={DEMAND_PAGES}, on-demand 90min wave)"
    )
    return signals, FeedStatus(NAME, mode, SOURCE, fetched_at, len(signals), detail)


def _parse_iso_utc(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(UTC)


# A simultaneous second explicit refresh observes existing data instead of
# duplicating the six paid-provider requests.
_forecast_lock = Lock()


def seatac_6h_forecast(now: datetime | None = None, *, pull: bool = False) -> dict:
    """On-demand hourly arrival report; reads and Qwen planning never spend."""
    from farol.adapters.base import read_cache, write_cache
    from farol.seatac_report import REPORT_VERSION, normalize_hour, project, windows
    from farol.usage import current_run

    current = (now or datetime.now(UTC)).astimezone(UTC)
    saved = read_cache("flightaware_ksea_6h_forecast")
    saved_payload = saved.get("payload") if isinstance(saved, dict) else None
    saved_payload = saved_payload if isinstance(saved_payload, dict) else None
    if not pull:
        return {**project(saved_payload, current), "cached": bool(saved_payload)}
    if not _forecast_lock.acquire(blocking=False):
        return {**project(saved_payload, current), "cached": bool(saved_payload), "refreshing": True}
    parent_usage = current_run.get()
    measured = {}
    token = current_run.set(measured)
    try:
        key = _api_key()
        if not key:
            raise ValueError("FLIGHTAWARE_API_KEY is not configured")
        hours = []
        seen = set()
        for index, start, end in windows(current):
            query = urlencode({"max_pages": 1, "start": _utc_iso(start), "end": _utc_iso(end)})
            try:
                payload, mode, fetched_at = fetch_json(
                    f"{SCHEDULED_ARRIVALS_URL}?{query}",
                    cache_key=f"fa_ksea_sched_utc_{start.strftime('%Y%m%d%H%M')}_{end.strftime('%Y%m%d%H%M')}",
                    ttl_seconds=FORECAST_TTL_SECONDS,
                    headers={"x-apikey": key, "Accept": "application/json"},
                )
            except FeedError:
                # Preserve the other windows and report unknown, never a zero count.
                payload, mode, fetched_at = None, "error", None
            hours.append(normalize_hour(index, start, end, payload, mode, fetched_at,
                                        seen, LONG_HAUL_ORIGINS, _origin_code))
        fetched = [h["fetched_at"] for h in hours if h["fetched_at"]]
        counts = measured.get("aeroapi.flightaware.com", {})
        usage = {name: counts.get(name, 0) for name in ("http_attempts", "http_failures", "cache_hits")}
        usage.update(max_http_requests=6, max_pages_per_request=1, billed_cost=None,
                     credits_remaining=None, measurement="Adapter transport counters for this refresh")
        completed = datetime.now(UTC) if now is None else current
        result = project({"report_schema_version": REPORT_VERSION, "hours": hours,
                          "fetched_at": min(fetched) if fetched else None,
                          "requested_at": current.isoformat(), "provider_usage": usage,
                          "http_requests_made": usage["http_attempts"],
                          "cached": all(h["mode"] != "live" for h in hours)}, completed)
        write_cache("flightaware_ksea_6h_forecast", result)
        return result
    finally:
        current_run.reset(token)
        if parent_usage is not None:
            for provider, counts in measured.items():
                target = parent_usage.setdefault(provider, {"http_attempts": 0, "cache_hits": 0, "http_failures": 0})
                for event, count in counts.items():
                    target[event] = target.get(event, 0) + count
        _forecast_lock.release()
