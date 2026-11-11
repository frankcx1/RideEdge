"""Amtrak live train arrivals at Seattle King Street Station (Pioneer Square / SODO).

Queries the keyless Amtraker v3 JSON API (api-v3.amtraker.com/v3/trains) for
Amtrak Cascades (Vancouver BC / Portland / Eugene), Coast Starlight (Los Angeles),
and Empire Builder (Chicago) trains arriving at King Street Station (code SEA).
Arriving rail travelers with luggage generate high-fare Uber trips to Downtown
Seattle hotels, SLU, Bellevue, Kirkland, and Redmond.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from farol.adapters.base import FeedError, FeedStatus, fetch_json
from farol.evidence import format_clock, parse_time
from farol.signals import Signal

NAME = "amtrak_king_street"
SOURCE = "amtraker:api-v3.amtraker.com/v3/trains (SEA King Street Station)"
TRAINS_URL = "https://api-v3.amtraker.com/v3/trains"
TTL_SECONDS = 10 * 60


def parse(
    payload: dict,
    window_start: datetime,
    window_end: datetime,
    *,
    fetched_at: str,
) -> list[Signal]:
    signals: list[Signal] = []
    if not isinstance(payload, dict):
        return signals
    tz = window_start.tzinfo
    seen_keys: set[str] = set()
    for _train_key, train_list in payload.items():
        if not isinstance(train_list, list):
            continue
        for train in train_list:
            if not isinstance(train, dict):
                continue
            orig_code = str(train.get("origCode") or "").upper()
            if orig_code == "SEA":
                # Departing train originating at Seattle, not an arrival wave
                continue
            route_name = str(train.get("routeName") or "Amtrak").strip()
            train_num = str(train.get("trainNum") or "?").strip()
            orig_name = str(train.get("origName") or orig_code or "Origin").strip()
            stations = train.get("stations") or []
            for idx, st in enumerate(stations):
                if not isinstance(st, dict) or str(st.get("code") or "").upper() != "SEA":
                    continue
                if idx == 0:
                    continue
                arr_raw = st.get("arr") or st.get("schArr")
                sch_raw = st.get("schArr") or arr_raw
                arr_dt = parse_time(arr_raw)
                sch_dt = parse_time(sch_raw)
                if arr_dt is None or arr_dt.tzinfo is None:
                    continue
                arr_local = arr_dt.astimezone(tz)
                disembark_end = arr_local + timedelta(minutes=30)
                if disembark_end < window_start or arr_local > window_end:
                    continue
                dedupe_id = f"amtrak-sea-{train_num}-{arr_local.strftime('%Y%m%d%H%M')}"
                if dedupe_id in seen_keys:
                    continue
                seen_keys.add(dedupe_id)
                delay_min = 0
                if sch_dt and sch_dt.tzinfo and arr_dt > sch_dt:
                    delay_min = int(round((arr_dt - sch_dt).total_seconds() / 60.0))
                status_text = str(st.get("status") or "").strip()
                is_long_distance = any(
                    k in route_name.lower() for k in ("starlight", "builder")
                )
                magnitude = 13000.0 if is_long_distance else 12000.0
                if delay_min >= 20:
                    magnitude += 1000.0
                delay_note = f" ({delay_min}m late)" if delay_min >= 10 else ""
                clock_str = format_clock(arr_local)
                title = (
                    f"{route_name} #{train_num} arrival from {orig_name} at King Street Station "
                    f"({clock_str}){delay_note}"
                )
                basis = "live" if st.get("arr") else "scheduled"
                signals.append(
                    Signal(
                        id=dedupe_id,
                        kind="special_event",
                        zone="seattle_core",
                        starts_at=arr_local.isoformat(),
                        ends_at=disembark_end.isoformat(),
                        magnitude=magnitude,
                        basis=basis,
                        source=SOURCE,
                        fetched_at=fetched_at,
                        expires_at=disembark_end.isoformat(),
                        evidence_quality=0.8 if basis == "live" else 0.68,
                        details={
                            "title": title,
                            "venue": "King Street Station (Pioneer Square)",
                            "route_name": route_name,
                            "train_number": train_num,
                            "origin": orig_name,
                            "status": status_text,
                            "delay_minutes": delay_min,
                            "notes": (
                                f"Rail passengers with luggage exiting onto 4th Ave S & S Jackson St "
                                f"from {orig_name}. High proportion of hotel and Eastside Uber rides."
                            ),
                        },
                    )
                )
    return signals


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    try:
        payload, mode, fetched_at = fetch_json(
            TRAINS_URL, cache_key="amtraker_v3_trains", ttl_seconds=TTL_SECONDS
        )
    except FeedError as error:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, str(error)[:240])
    signals = parse(payload, window_start, window_end, fetched_at=fetched_at)
    detail = f"{len(signals)} King Street Station train arrival(s) in window"
    return signals, FeedStatus(NAME, mode, SOURCE, fetched_at, len(signals), detail)
