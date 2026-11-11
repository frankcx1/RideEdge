"""Washington State Ferries (WSF) live arrivals at Seattle Colman Dock (Pier 52).

Uses the same WSDOT_API_KEY as wsdot.py to query WSF Vessels REST API for
Bainbridge Island and Bremerton ferries arriving at Colman Dock (TerminalID 7).
Walk-on ferry passengers unloading at Pier 52 create concentrated 25-minute
pickup waves for Downtown Seattle hotels, SLU, Capitol Hill, and Belltown.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta

from farol.adapters.base import FeedError, FeedStatus, fetch_json
from farol.evidence import format_clock
from farol.signals import Signal

NAME = "wsf_colman_ferries"
SOURCE = "wsdot:Ferries Vessels REST (Colman Dock Terminal 7)"
VESSELS_URL = "https://www.wsdot.wa.gov/Ferries/API/Vessels/rest/vessellocations"
TTL_SECONDS = 5 * 60
COLMAN_DOCK_TERMINAL_ID = 7


def _access_code() -> str:
    return os.getenv("WSDOT_API_KEY", "").strip()


def _wsdot_time(value: object, tzinfo) -> datetime | None:
    if not value:
        return None
    match = re.fullmatch(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/", str(value))
    try:
        stamp = (
            datetime.fromtimestamp(int(match[1]) / 1000, UTC)
            if match
            else datetime.fromisoformat(str(value))
        )
        return stamp.astimezone(tzinfo) if stamp.tzinfo else None
    except (ValueError, OverflowError, OSError):
        return None


def parse(
    payload: list,
    window_start: datetime,
    window_end: datetime,
    *,
    fetched_at: str,
) -> list[Signal]:
    signals: list[Signal] = []
    if not isinstance(payload, list):
        return signals
    tz = window_start.tzinfo
    for vessel in payload:
        if not isinstance(vessel, dict) or not vessel.get("InService", True):
            continue
        arriving_id = vessel.get("ArrivingTerminalID")
        departing_name = str(vessel.get("DepartingTerminalName") or "Puget Sound").strip()
        arriving_name = str(vessel.get("ArrivingTerminalName") or "").strip()
        if arriving_id != COLMAN_DOCK_TERMINAL_ID and arriving_name.lower() != "seattle":
            continue
        vessel_name = str(vessel.get("VesselName") or "WSF Ferry").strip()
        eta = _wsdot_time(vessel.get("Eta"), tz)
        scheduled_dep = _wsdot_time(vessel.get("ScheduledDeparture"), tz)
        left_dock = _wsdot_time(vessel.get("LeftDock"), tz)
        at_dock = bool(vessel.get("AtDock"))
        if eta is None:
            if at_dock and scheduled_dep is not None:
                # Vessel is currently loading at origin; estimate crossing (~35m Bainbridge, ~60m Bremerton)
                crossing_min = 60 if "bremerton" in departing_name.lower() else 35
                eta = scheduled_dep + timedelta(minutes=crossing_min)
            else:
                continue
        disembark_end = eta + timedelta(minutes=25)
        if disembark_end < window_start or eta > window_end:
            continue
        delay_minutes = 0
        if scheduled_dep and left_dock and left_dock > scheduled_dep:
            delay_minutes = int(round((left_dock - scheduled_dep).total_seconds() / 60.0))
        is_bainbridge = "bainbridge" in departing_name.lower()
        base_mag = 12500.0 if is_bainbridge else 11500.0
        if delay_minutes >= 15:
            base_mag += 1500.0
        eta_clock = format_clock(eta)
        delay_tag = f" ({delay_minutes}m late — bunched walk-on wave)" if delay_minutes >= 15 else ""
        title = (
            f"WSF {vessel_name} ferry arrival from {departing_name} at Colman Dock "
            f"({eta_clock}){delay_tag}"
        )
        signals.append(
            Signal(
                id=f"wsf-colman-{vessel.get('VesselID', vessel_name.lower())}-{eta.strftime('%Y%m%d%H%M')}",
                kind="special_event",
                zone="seattle_core",
                starts_at=eta.isoformat(),
                ends_at=disembark_end.isoformat(),
                magnitude=base_mag,
                basis="live",
                source=SOURCE,
                fetched_at=fetched_at,
                expires_at=disembark_end.isoformat(),
                evidence_quality=0.82,
                details={
                    "title": title,
                    "venue": "Colman Dock (Pier 52)",
                    "vessel": vessel_name,
                    "origin_terminal": departing_name,
                    "destination_terminal": "Seattle Colman Dock (Pier 52)",
                    "delay_minutes": delay_minutes,
                    "notes": (
                        f"Walk-on ferry passengers unloading at Pier 52 (Alaskan Way & Marion St) "
                        f"from {departing_name}. Prime pickups to Downtown hotels, SLU, and Capitol Hill."
                    ),
                },
            )
        )
    return signals


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    code = _access_code()
    if not code:
        return [], FeedStatus(
            NAME,
            "needs_key",
            "env:WSDOT_API_KEY",
            None,
            0,
            "set WSDOT_API_KEY — WSF live ferry arrivals at Colman Dock",
        )
    url = f"{VESSELS_URL}?apiaccesscode={code}"
    try:
        payload, mode, fetched_at = fetch_json(
            url, cache_key="wsf_vessel_locations", ttl_seconds=TTL_SECONDS
        )
    except FeedError as error:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, str(error)[:240])
    signals = parse(payload, window_start, window_end, fetched_at=fetched_at)
    detail = f"{len(signals)} Colman Dock ferry arrival wave(s) in window"
    return signals, FeedStatus(NAME, mode, SOURCE, fetched_at, len(signals), detail)
