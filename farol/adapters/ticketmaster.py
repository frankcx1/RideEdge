"""Ticketmaster Discovery API: ticketed concerts and shows in the Seattle box.

Sports home games stay on ESPN/MLB/NHL so we do not double-count Apple Cup or
Kraken. Ticketmaster fills Climate Pledge concerts, Marymoor, Paramount, WaMu,
Neptune, and similar. Consumer key is free; set TICKETMASTER_API_KEY.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import urlencode

from farol.adapters.base import FeedError, FeedStatus, cache_dir, fetch_json
from farol.dashboard import FIXTURES
from farol.signals import Signal
from farol.zones import canonical_zone, load_zones

NAME = "ticketmaster_events"
SOURCE = "ticketmaster:discovery/v2/events"
EVENTS_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
TTL_SECONDS = 6 * 60 * 60
# Seattle-Tacoma DMA from Discovery docs. latlong is deprecated; venueId is the
# precise call for rooms TM actually inventories (Climate Pledge, Marymoor, Chateau).
DMA_SEATTLE = "385"
LATLONG = "47.62,-122.33"
RADIUS_MILES = "35"
VENUE_CATALOG = FIXTURES / "ticketmaster_venues.json"
# Longer needles first.
VENUE_ZONES = (
    ("climate pledge", "seattle_center"),
    ("mccaw hall", "seattle_center"),
    ("wamu theater", "sodo_stadiums"),
    ("wa mu theater", "sodo_stadiums"),
    ("showbox so-do", "sodo_stadiums"),
    ("showbox sodo", "sodo_stadiums"),
    ("lumen field", "sodo_stadiums"),
    ("t-mobile park", "sodo_stadiums"),
    ("husky stadium", "uw_district"),
    ("neptune theatre", "uw_district"),
    ("neptune theater", "uw_district"),
    ("paramount theatre", "capitol_hill"),
    ("paramount theater", "capitol_hill"),
    ("moore theatre", "seattle_core"),
    ("moore theater", "seattle_core"),
    ("benaroya", "seattle_core"),
    ("showbox", "seattle_core"),
    ("crocodile", "belltown"),
    ("nectar lounge", "fremont_ballard"),
    ("chop suey", "capitol_hill"),
    ("tractor", "fremont_ballard"),
    ("marymoor", "marymoor"),
    ("chateau ste", "woodinville_wine"),
    ("5th avenue theatre", "seattle_core"),
    ("fifth avenue theatre", "seattle_core"),
    ("hec edmundson", "uw_district"),
    ("alaska airlines arena", "uw_district"),
    ("seattle convention center", "seattle_core"),
    ("woodland park zoo", "fremont_ballard"),
    ("zootunes", "fremont_ballard"),
    ("meydenbauer", "bellevue_core"),
    ("kirkland performance", "kirkland_waterfront"),
    ("village theatre", "issaquah"),
)
TOUR_NOISE = (
    "ballpark tour",
    "stadium tour",
    "stadium tours",
    "arena tours",
    "all access pass",
    "not an event ticket",
    "amplified access",
    "tables & cabanas",
    "tables and cabanas",
    "parking pass",
    "vip upgrade",
    "meet & greet",
    "meet and greet",
)
SKIP_SPORTS_SEGMENTS = {"sports"}
_TOKEN_STOP = {
    "exit", "the", "and", "tour", "tours", "presents", "featuring", "with",
    "for", "from", "plus", "ages", "event", "live", "world",
}


def _api_key() -> str:
    return os.getenv("TICKETMASTER_API_KEY", "").strip()


@lru_cache(maxsize=1)
def load_venue_catalog() -> list[dict]:
    if not VENUE_CATALOG.is_file():
        return []
    payload = json.loads(VENUE_CATALOG.read_text(encoding="utf-8"))
    return list(payload.get("venues") or [])


def priority_venue_ids() -> tuple[str, ...]:
    return tuple(str(row["id"]) for row in load_venue_catalog() if row.get("id"))


def zone_for_venue_id(venue_id: str) -> str | None:
    for row in load_venue_catalog():
        if row.get("id") == venue_id and row.get("zone"):
            return canonical_zone(str(row["zone"]))
    return None


def zone_for_venue(name: str) -> str | None:
    lowered = name.lower()
    for needle, zone in VENUE_ZONES:
        if needle in lowered:
            return canonical_zone(zone)
    return None


def _segment_name(event: dict) -> str:
    for item in event.get("classifications") or []:
        name = ((item.get("segment") or {}).get("name") or "").strip()
        if name:
            return name
    return ""


def _kickoff(event: dict, tzinfo) -> datetime | None:
    start = (event.get("dates") or {}).get("start") or {}
    raw = start.get("dateTime")
    if raw:
        stamp = datetime.fromisoformat(str(raw))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=tzinfo)
        return stamp.astimezone(tzinfo)
    local_date = start.get("localDate")
    local_time = start.get("localTime") or "19:00:00"
    if not local_date:
        return None
    try:
        stamp = datetime.fromisoformat(f"{local_date}T{local_time}")
    except ValueError:
        return None
    return stamp.replace(tzinfo=tzinfo)


def _timing(segment: str) -> tuple[timedelta, timedelta]:
    lowered = segment.lower()
    if lowered == "sports":
        return timedelta(hours=3), timedelta(hours=1)
    if lowered == "music":
        return timedelta(hours=3), timedelta(minutes=45)
    return timedelta(hours=2, minutes=30), timedelta(minutes=40)


def _zone_label(zone_id: str | None) -> str:
    if not zone_id:
        return "Unmapped area"
    try:
        z = load_zones().by_id.get(zone_id)
        if z:
            return z.label
    except Exception:  # noqa: BLE001
        pass
    return zone_id.replace("_", " ").title()


def _collapse_duplicate_exits_with_map(signals: list[Signal]) -> tuple[list[Signal], int, dict[str, str]]:
    """Keep one listing when TM splits a show, and map each collapsed signal ID to its kept primary signal ID."""
    kept: list[Signal] = []
    used: set[int] = set()
    collapsed_to_primary: dict[str, str] = {}
    for index, first in enumerate(signals):
        if index in used:
            continue
        group = [first]
        first_kick = datetime.fromisoformat(str(first.details.get("kickoff") or first.starts_at))
        first_tokens = _title_tokens(str(first.details.get("title") or ""))
        for other_index, other in enumerate(signals):
            if other_index <= index or other_index in used:
                continue
            if other.zone != first.zone:
                continue
            other_kick = datetime.fromisoformat(str(other.details.get("kickoff") or other.starts_at))
            if abs((first_kick - other_kick).total_seconds()) > 3 * 3600:
                continue
            other_tokens = _title_tokens(str(other.details.get("title") or ""))
            if first_tokens and other_tokens and not (first_tokens & other_tokens):
                continue
            group.append(other)
            used.add(other_index)
        winner = max(group, key=lambda item: len(str(item.details.get("title") or "")))
        kept.append(winner)
        for member in group:
            if member.id != winner.id:
                collapsed_to_primary[member.id] = winner.id
        used.add(index)
    return kept, len(signals) - len(kept), collapsed_to_primary


def inspect_events(
    payload: dict,
    window_start: datetime,
    window_end: datetime,
    *,
    fetched_at: str,
    query_summaries: list[dict] | None = None,
    mode: str = "live",
) -> tuple[list[Signal], int, dict]:
    """Parse Ticketmaster events into signals AND build a complete retained source-detail inspection snapshot."""
    skipped = 0
    signals: list[Signal] = []
    event_rows: list[dict] = []
    embedded = (payload.get("_embedded") or {}).get("events") or []
    for idx, event in enumerate(embedded):
        if not isinstance(event, dict):
            skipped += 1
            continue
        event_id = str(event.get("id") or f"tm-event-{idx}")
        title = str(event.get("name") or "Ticketed event")
        venues = ((event.get("_embedded") or {}).get("venues") or [{}])
        venue_row = venues[0] or {}
        venue_name = str(venue_row.get("name") or "")
        venue_id = str(venue_row.get("id") or "")
        city_name = str(((venue_row.get("city") or {}).get("name")) or "unknown")
        zone = zone_for_venue_id(venue_id) or zone_for_venue(venue_name)
        zone_lbl = _zone_label(zone)
        segment = _segment_name(event)
        dates = event.get("dates") or {}
        start_obj = dates.get("start") or {}
        end_obj = dates.get("end") or {}
        status_code = str(((dates.get("status") or {}).get("code")) or "unknown").strip() or "unknown"
        local_date = str(start_obj.get("localDate") or "unknown")
        local_time = str(start_obj.get("localTime") or "unknown")
        tz_name = str(dates.get("timezone") or getattr(window_start.tzinfo, "key", None) or "America/Los_Angeles")
        raw_start_dt = str(start_obj.get("dateTime") or "")
        raw_end_dt = str(end_obj.get("dateTime") or end_obj.get("localTime") or "")
        kickoff = _kickoff(event, window_start.tzinfo)
        duration, wave = _timing(segment)
        exit_start = (kickoff + duration) if kickoff is not None else None
        exit_end = (exit_start + wave) if exit_start is not None else None
        url = str(event.get("url") or "")

        row_detail = {
            "event_id": event_id,
            "title": title,
            "venue": venue_name or "unknown",
            "venue_id": venue_id,
            "city": city_name,
            "provider": "Ticketmaster Discovery v2",
            "segment": segment or "unknown",
            "status": status_code,
            "local_date": local_date,
            "local_time": local_time,
            "timezone": tz_name,
            "source_start_time": raw_start_dt or (kickoff.isoformat() if kickoff is not None else "unknown"),
            "source_end_time": raw_end_dt if raw_end_dt else None,
            "source_end_basis": "provider_reported" if raw_end_dt else "not_reported_by_provider",
            "estimated_departure_start": exit_start.isoformat() if exit_start is not None else None,
            "estimated_departure_end": exit_end.isoformat() if exit_end is not None else None,
            "exit_timing_basis": (
                f"RideEdge estimate ({duration} show + {wave} exit wave); provider end time not reported"
                if exit_start is not None
                else "not estimated (start time missing)"
            ),
            "zone": zone,
            "zone_label": zone_lbl,
            "mapping_status": "excluded",
            "signal_id": None,
            "exclusion_reason": None,
            "mapping_explanation": "",
            "url": url,
        }

        if status_code.lower() in {"cancelled", "canceled", "postponed"}:
            skipped += 1
            row_detail["exclusion_reason"] = f"event_{status_code.lower()}"
            row_detail["mapping_explanation"] = f"Excluded: provider event status is '{status_code}'."
            event_rows.append(row_detail)
            continue
        if zone is None:
            skipped += 1
            row_detail["exclusion_reason"] = "unmapped_venue"
            row_detail["mapping_explanation"] = (
                f"Excluded: venue '{venue_name or 'unknown'}' is not mapped to a RideEdge Seattle/Eastside area."
            )
            event_rows.append(row_detail)
            continue
        if segment.lower() in SKIP_SPORTS_SEGMENTS:
            skipped += 1
            row_detail["exclusion_reason"] = "excluded_sports_segment"
            row_detail["mapping_explanation"] = (
                "Excluded: sports segment is handled by dedicated ESPN/MLB/NHL feeds to avoid double-counting."
            )
            event_rows.append(row_detail)
            continue
        if kickoff is None or exit_start is None or exit_end is None:
            skipped += 1
            row_detail["exclusion_reason"] = "missing_start_time"
            row_detail["mapping_explanation"] = "Excluded: provider did not supply a valid start date/time."
            event_rows.append(row_detail)
            continue
        if exit_end < window_start or exit_start > window_end:
            row_detail["exclusion_reason"] = "outside_query_window"
            row_detail["mapping_explanation"] = (
                f"Excluded: estimated departure window ({exit_start.isoformat()} to {exit_end.isoformat()}) "
                f"is outside the active query window ({window_start.isoformat()} to {window_end.isoformat()})."
            )
            event_rows.append(row_detail)
            continue
        blob = f"{title} {venue_name}".lower()
        if any(noise in blob for noise in TOUR_NOISE):
            skipped += 1
            row_detail["exclusion_reason"] = "excluded_non_event_listing"
            row_detail["mapping_explanation"] = (
                "Excluded: listing matches tour, VIP upgrade, parking pass, or cabana access noise filter."
            )
            event_rows.append(row_detail)
            continue

        sig_id = f"tm-{event.get('id') or exit_start.isoformat()}"
        sig = Signal(
            id=sig_id,
            kind="event_exit",
            zone=zone,
            starts_at=exit_start.isoformat(),
            ends_at=exit_end.isoformat(),
            magnitude=8000.0,
            basis="scheduled",
            source=SOURCE,
            fetched_at=fetched_at,
            expires_at=exit_end.isoformat(),
            evidence_quality=0.7,
            details={
                "title": f"{title} exit at {venue_name}",
                "venue": venue_name,
                "segment": segment or "unknown",
                "kickoff": kickoff.isoformat(),
                "url": url,
                "attendance_basis": "assumed mid-size ticketed draw; TM has no public headcount",
                "exit_timing_basis": f"assumed {duration} show + {wave} exit wave",
            },
        )
        signals.append(sig)
        row_detail["_candidate_signal_id"] = sig_id
        event_rows.append(row_detail)

    collapsed, dupes, collapsed_map = _collapse_duplicate_exits_with_map(signals)
    kept_ids = {s.id for s in collapsed}
    for row_detail in event_rows:
        cand_id = row_detail.pop("_candidate_signal_id", None)
        if cand_id is None:
            continue
        if cand_id in kept_ids:
            row_detail["mapping_status"] = "mapped_signal"
            row_detail["signal_id"] = cand_id
            row_detail["exclusion_reason"] = None
            row_detail["mapping_explanation"] = (
                f"Mapped departure signal '{cand_id}' in {row_detail['zone_label']} "
                f"(estimated departure window {row_detail['estimated_departure_start']} to {row_detail['estimated_departure_end']})."
            )
        else:
            primary_id = collapsed_map.get(cand_id, cand_id)
            row_detail["mapping_status"] = "merged_duplicate_signal"
            row_detail["signal_id"] = primary_id
            row_detail["exclusion_reason"] = "collapsed_duplicate_listing"
            row_detail["mapping_explanation"] = (
                f"Duplicate/split listing merged into primary mapped departure signal '{primary_id}' in {row_detail['zone_label']}."
            )

    q_list = list(query_summaries or [])
    q_times = [str(q.get("fetched_at")) for q in q_list if q.get("fetched_at")]
    detail_snapshot = {
        "adapter": NAME,
        "provider": "Ticketmaster Discovery v2",
        "kind": "events",
        "mode": mode,
        "source": SOURCE,
        "fetched_at": fetched_at or (max(q_times) if q_times else None),
        "query_fetched_at_min": min(q_times) if q_times else (fetched_at or None),
        "query_fetched_at_max": max(q_times) if q_times else (fetched_at or None),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "unique_events_count": len(event_rows),
        "mapped_signals_count": len(collapsed),
        "excluded_events_count": sum(1 for r in event_rows if r["mapping_status"] != "mapped_signal"),
        "duplicate_collapsed_count": dupes,
        "summary_plain": f"{len(event_rows)} events · {len(collapsed)} mapped departure signals",
        "mapping_note": (
            "A mapped departure signal is an event associated with a RideEdge area and an estimated "
            "departure window; it is not proof that passengers are currently leaving."
        ),
        "truncated": any(bool(q.get("truncated")) for q in q_list),
        "queries": q_list,
        "events": event_rows,
        "signals": [
            {
                "id": s.id,
                "zone": s.zone,
                "zone_label": _zone_label(s.zone),
                "starts_at": s.starts_at,
                "ends_at": s.ends_at,
                "basis": s.basis,
                "title": s.details.get("title"),
                "venue": s.details.get("venue"),
                "kickoff": s.details.get("kickoff"),
                "exit_timing_basis": s.details.get("exit_timing_basis"),
            }
            for s in collapsed
        ],
    }
    return collapsed, skipped + dupes, detail_snapshot


def parse(payload: dict, window_start: datetime, window_end: datetime, *, fetched_at: str) -> tuple[list[Signal], int]:
    collapsed, total_skipped, _ = inspect_events(
        payload, window_start, window_end, fetched_at=fetched_at
    )
    return collapsed, total_skipped


def _title_tokens(title: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", title.lower())
        if len(word) > 2 and word not in _TOKEN_STOP
    }


def collapse_duplicate_exits(signals: list[Signal]) -> tuple[list[Signal], int]:
    """Keep one listing when TM splits a show (Marymoor Park vs Live, cabanas vs concert)."""
    kept, dupes, _ = _collapse_duplicate_exits_with_map(signals)
    return kept, dupes


def save_retained_detail(detail_snapshot: dict) -> None:
    if os.getenv("PYTEST_CURRENT_TEST") and not os.getenv("FAROL_CACHE_DIR"):
        return
    try:
        out_dir = cache_dir() / "source_details"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{NAME}.json").write_text(
            json.dumps(detail_snapshot, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _reconstruct_stamp(cdir, stamp: str, now: datetime | None = None) -> dict | None:
    matched_files = sorted(cdir.glob(f"ticketmaster_*_{stamp}.json"))
    if not matched_files:
        return None
    merged: dict[str, dict] = {}
    query_summaries: list[dict] = []
    fetched_at = ""
    multi_query_duplicates = 0
    for fpath in matched_files:
        try:
            wrapper = json.loads(fpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(wrapper, dict):
            continue
        q_fetched = str(wrapper.get("fetched_at") or "")
        if q_fetched > fetched_at:
            fetched_at = q_fetched
        payload = wrapper.get("payload")
        if not isinstance(payload, dict):
            continue
        label = fpath.stem.replace("ticketmaster_", "").replace(f"_{stamp}", "")
        total = (payload.get("page") or {}).get("totalElements")
        total_int = int(total) if isinstance(total, (int, float)) else None
        ev_list = _embedded_events(payload)
        q_dupes = 0
        for event in ev_list:
            event_id = str(event.get("id") or "")
            if event_id:
                if event_id in merged:
                    multi_query_duplicates += 1
                    q_dupes += 1
                merged[event_id] = event
        query_summaries.append({
            "label": label,
            "mode": "cache",
            "fetched_at": q_fetched or None,
            "total_elements": total_int,
            "fetched_count": len(ev_list),
            "duplicate_ids_in_query": q_dupes,
            "truncated": bool(total_int is not None and total_int > len(ev_list)),
        })
    if not query_summaries:
        return None
    from zoneinfo import ZoneInfo
    pacific = ZoneInfo("America/Los_Angeles")
    m_bounds = re.match(r"^v2_(\d{8}T\d{2})_(\d{8}T\d{2})$", stamp)
    if m_bounds:
        try:
            q_start = datetime.strptime(m_bounds.group(1), "%Y%m%dT%H").replace(tzinfo=UTC)
            q_end = datetime.strptime(m_bounds.group(2), "%Y%m%dT%H").replace(tzinfo=UTC)
            cur = (q_start + timedelta(hours=4)).astimezone(pacific)
            win_end = (q_end - timedelta(hours=1)).astimezone(pacific)
        except ValueError:
            cur = (now or datetime.now(pacific)).astimezone(pacific)
            win_end = (cur.astimezone(UTC) + timedelta(hours=12)).astimezone(pacific)
    else:
        cur = (now or datetime.now(pacific)).astimezone(pacific)
        win_end = (cur.astimezone(UTC) + timedelta(hours=12)).astimezone(pacific)
    combined = {"_embedded": {"events": list(merged.values())}, "page": {}}
    _, _, detail_snapshot = inspect_events(
        combined,
        cur,
        win_end,
        fetched_at=fetched_at,
        query_summaries=query_summaries,
        mode="cache",
    )
    detail_snapshot["multi_query_duplicates"] = multi_query_duplicates
    return detail_snapshot


def _detail_matches_expectations(
    data: dict,
    *,
    expected_events: int | None = None,
    expected_signals: int | None = None,
    expected_fetched_at: str | None = None,
    expected_snapshot_id: str | None = None,
) -> bool:
    ev_cnt = len(data.get("events") or [])
    sig_cnt = len(data.get("signals") or [])
    if ev_cnt <= 0:
        return False
    if expected_events is not None and ev_cnt != expected_events:
        return False
    if expected_signals is not None and sig_cnt != expected_signals:
        return False
    if expected_snapshot_id and data.get("snapshot_id") and str(data.get("snapshot_id")) != str(expected_snapshot_id):
        return False
    if expected_fetched_at:
        from farol.evidence import parse_time

        exp_dt = parse_time(expected_fetched_at)
        det_dt = parse_time(data.get("fetched_at"))
        min_dt = parse_time(data.get("query_fetched_at_min"))
        max_dt = parse_time(data.get("query_fetched_at_max"))
        if exp_dt is not None:
            if det_dt is None and min_dt is None:
                return False
            close_to_fetched = det_dt is not None and abs((exp_dt - det_dt).total_seconds()) <= 300.0
            within_query_span = (
                min_dt is not None
                and max_dt is not None
                and (min_dt - timedelta(minutes=5)) <= exp_dt <= (max_dt + timedelta(minutes=5))
            )
            if not (close_to_fetched or within_query_span):
                return False
    return True


def load_retained_detail(
    now: datetime | None = None,
    *,
    expected_events: int | None = None,
    expected_signals: int | None = None,
    expected_fetched_at: str | None = None,
    expected_snapshot_id: str | None = None,
) -> dict | None:
    sdir = cache_dir() / "source_details"
    candidate_paths = []
    if expected_snapshot_id:
        safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(expected_snapshot_id))
        candidate_paths.append(sdir / f"{NAME}_{safe_id}.json")
    candidate_paths.append(sdir / f"{NAME}.json")
    for path in candidate_paths:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and _detail_matches_expectations(
                    data,
                    expected_events=expected_events,
                    expected_signals=expected_signals,
                    expected_fetched_at=expected_fetched_at,
                    expected_snapshot_id=expected_snapshot_id,
                ):
                    return data
            except (OSError, ValueError):
                pass
    # Attempt offline reconstruction from retained ticketmaster_* cache files if present
    cdir = cache_dir()
    if not cdir.is_dir():
        return None
    candidates = sorted(cdir.glob("ticketmaster_*_v2_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    seen_stamps: list[str] = []
    for cand in candidates:
        m = re.search(r"_(v2_\d{8}T\d{2}_\d{8}T\d{2})$", cand.stem)
        if m and m.group(1) not in seen_stamps:
            seen_stamps.append(m.group(1))
        if len(seen_stamps) >= 12:
            break
    has_strict_expectations = any(
        x is not None for x in (expected_events, expected_signals, expected_fetched_at, expected_snapshot_id)
    )
    fallback_snap: dict | None = None
    for stamp in seen_stamps:
        snap = _reconstruct_stamp(cdir, stamp, now=now)
        if snap is None:
            continue
        if _detail_matches_expectations(
            snap,
            expected_events=expected_events,
            expected_signals=expected_signals,
            expected_fetched_at=expected_fetched_at,
            expected_snapshot_id=expected_snapshot_id,
        ):
            return snap
        if not has_strict_expectations and fallback_snap is None and snap.get("unique_events_count", 0) > 0:
            fallback_snap = snap
    return fallback_snap if not has_strict_expectations else None


def _events_query(key: str, extra: dict) -> str:
    params = {
        "apikey": key,
        "size": "200",
        "sort": "date,asc",
        "includeTBA": "yes",
        "includeTBD": "yes",
    }
    params.update(extra)
    return urlencode(params)


def _embedded_events(payload: dict) -> list[dict]:
    rows = ((payload.get("_embedded") or {}).get("events") or [])
    return [row for row in rows if isinstance(row, dict)]


def event_query_bounds(window_start: datetime, window_end: datetime) -> tuple[datetime, datetime]:
    """UTC show starts covering exits in the window, cached by whole-hour bounds.

    Current adapters assume at most three hours of show plus 45 minutes of exit.
    Four hours of lookback includes shows already underway when HERE is checked.
    """
    start = (window_start.astimezone(UTC) - timedelta(hours=4)).replace(minute=0, second=0, microsecond=0)
    end = (window_end.astimezone(UTC) + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return start, end


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    key = _api_key()
    if not key:
        return [], FeedStatus(
            NAME,
            "needs_key",
            "env:TICKETMASTER_API_KEY",
            None,
            0,
            "set TICKETMASTER_API_KEY — Discovery API concerts/shows in the Seattle box",
        )
    start, end = event_query_bounds(window_start, window_end)
    date_bounds = {
        "startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    stamp = f"v2_{start:%Y%m%dT%H}_{end:%Y%m%dT%H}"
    ids = priority_venue_ids()
    queries: list[tuple[str, dict]] = []
    chunk = 8
    for index in range(0, len(ids), chunk):
        queries.append(
            (f"venues{index // chunk}", {"venueId": ",".join(ids[index : index + chunk]), **date_bounds})
        )
    queries.append(("dma", {"dmaId": DMA_SEATTLE, **date_bounds}))
    merged: dict[str, dict] = {}
    modes: list[str] = []
    fetched_at = ""
    errors: list[str] = []
    totals: list[str] = []
    query_summaries: list[dict] = []
    multi_query_duplicates = 0
    for label, extra in queries:
        try:
            payload, mode, fetched_at = fetch_json(
                f"{EVENTS_URL}?{_events_query(key, extra)}",
                cache_key=f"ticketmaster_{label}_{stamp}",
                ttl_seconds=TTL_SECONDS,
            )
        except FeedError as error:
            errors.append(f"{label}: {error}")
            query_summaries.append({
                "label": label,
                "mode": "error",
                "fetched_at": None,
                "total_elements": None,
                "fetched_count": 0,
                "truncated": False,
                "error": str(error)[:200],
            })
            continue
        modes.append(mode)
        if not isinstance(payload, dict):
            errors.append(f"{label}: unexpected payload")
            continue
        total = (payload.get("page") or {}).get("totalElements")
        if total is not None:
            totals.append(f"{label}={total}")
        ev_list = _embedded_events(payload)
        q_dupes = 0
        for event in ev_list:
            event_id = str(event.get("id") or "")
            if event_id:
                if event_id in merged:
                    multi_query_duplicates += 1
                    q_dupes += 1
                merged[event_id] = event
        total_int = int(total) if isinstance(total, (int, float)) else None
        query_summaries.append({
            "label": label,
            "mode": mode,
            "fetched_at": fetched_at,
            "total_elements": total_int,
            "fetched_count": len(ev_list),
            "duplicate_ids_in_query": q_dupes,
            "truncated": bool(total_int is not None and total_int > len(ev_list)),
        })
    if not modes and errors:
        return [], FeedStatus(NAME, "error", SOURCE, None, 0, "; ".join(errors)[:300])
    combined = {"_embedded": {"events": list(merged.values())}, "page": {}}
    mode = "stale_cache" if "stale_cache" in modes else ("cache" if set(modes) == {"cache"} else "live")
    signals, skipped, detail_snapshot = inspect_events(
        combined,
        window_start,
        window_end,
        fetched_at=fetched_at,
        query_summaries=query_summaries,
        mode=mode,
    )
    detail_snapshot["multi_query_duplicates"] = multi_query_duplicates
    save_retained_detail(detail_snapshot)
    detail = f"{len(signals)} mapped exits from {len(merged)} unique TM events"
    if skipped:
        detail += f"; {skipped} skipped (unmapped venue, sports, or tours)"
    if totals:
        detail += f"; {', '.join(totals)}"
    if errors:
        detail += f"; {'; '.join(errors)}"
    return signals, FeedStatus(NAME, mode, SOURCE, fetched_at or None, len(signals), detail)
