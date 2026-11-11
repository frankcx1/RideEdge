"""Pure SeaTac report normalization. No provider calls or scoring-engine inputs."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
TTL_SECONDS = 1800
REPORT_VERSION = 1


def stamp(value: object) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def clock(at: datetime) -> str:
    return at.astimezone(PACIFIC).strftime("%I:%M %p %Z").lstrip("0")


def windows(now: datetime):
    current = now.astimezone(UTC)
    base = current.replace(minute=0, second=0, microsecond=0)
    for index in range(6):
        yield (
            index,
            current if index == 0 else base + timedelta(hours=index),
            base + timedelta(hours=index + 1),
        )


def flight_time(flight: dict):
    # Actual outranks estimated/scheduled; ON is runway, IN is the gate.
    for prefix in ("actual", "estimated", "scheduled"):
        for suffix, meaning in (("on", "landing"), ("in", "gate")):
            field = f"{prefix}_{suffix}"
            when = stamp(flight.get(field))
            if when is not None:
                return when, f"{prefix}_{meaning}", field
    return None, None, None


def normalize_hour(
    index, start, end, payload, mode, fetched_at, seen, long_haul_origins, origin_code
):
    raw = payload.get("scheduled_arrivals") if isinstance(payload, dict) else None
    valid_payload = isinstance(raw, list)
    rows = raw if valid_payload else []
    excluded = {
        key: 0
        for key in (
            "malformed",
            "cancelled",
            "cargo",
            "unknown_time",
            "out_of_window",
            "duplicate",
            "unknown_identity",
        )
    }
    records = []
    basis_counts = {}
    for flight in rows:
        if not isinstance(flight, dict):
            excluded["malformed"] += 1
            continue
        ident = str(flight.get("ident") or "").strip()
        if flight.get("cancelled") is True:
            excluded["cancelled"] += 1
            continue
        if ident.startswith(("FDX", "UPS", "GTI", "ABX", "ATN")):
            excluded["cargo"] += 1
            continue
        when, basis, field = flight_time(flight)
        if when is None:
            excluded["unknown_time"] += 1
            continue
        if not start <= when < end:
            excluded["out_of_window"] += 1
            continue
        identity = str(flight.get("fa_flight_id") or "").strip() or (
            f"{ident}:{when.isoformat()}" if ident else None
        )
        if identity is None:
            excluded["unknown_identity"] += 1
            continue
        if identity in seen:
            excluded["duplicate"] += 1
            continue
        seen.add(identity)
        origin = origin_code(flight)
        records.append(
            {
                "ident": ident or "Unlabeled flight",
                "origin": origin,
                "arrival_at": when.isoformat(),
                "time_basis": basis,
                "time_field": field,
                "long_haul": origin in long_haul_origins,
            }
        )
        basis_counts[basis] = basis_counts.get(basis, 0) + 1
    records.sort(key=lambda r: r["arrival_at"])
    links = payload.get("links") if isinstance(payload, dict) else None
    has_more = bool(links.get("next")) if isinstance(links, dict) else False
    count = len(records)
    minutes = (end - start).total_seconds() / 60
    estimate = count
    if has_more and len(records) >= 2 and len(basis_counts) == 1:
        span = max(
            8.0,
            (stamp(records[-1]["arrival_at"]) - stamp(records[0]["arrival_at"])).total_seconds()
            / 60,
        )
        estimate = max(count, min(48, round(count * minutes / span)))
    fetched = stamp(fetched_at)
    valid_until = fetched + timedelta(seconds=TTL_SECONDS) if fetched else None
    return {
        "hour_index": index,
        "hour_label": f"{clock(start)} – {clock(end)}",
        "starts_at": start.isoformat(),
        "ends_at": end.isoformat(),
        "window_minutes": round(minutes, 3),
        "partial_hour": minutes < 60,
        "estimated_planes": estimate if valid_payload else None,
        "sampled_flights": count if valid_payload else None,
        "returned_records": len(rows) if valid_payload else None,
        "extrapolated": estimate > count,
        "long_haul_count": sum(r["long_haul"] for r in records),
        "page_full": has_more,
        "coverage": "unavailable"
        if not valid_payload
        else "partial_page"
        if has_more
        else "returned_page",
        "mode": mode,
        "fetched_at": fetched.isoformat() if fetched else None,
        "valid_until": valid_until.isoformat() if valid_until else None,
        "timing_basis_counts": basis_counts,
        "excluded_records": excluded,
        "flights": records,
        "sample_flights": [f"{r['ident']} ({r['origin']})" for r in records[:5]],
        "estimate_method": "Returned count × window minutes / max(sample span, 8 minutes), capped at 48 and never below the sample. Assumes uniform arrivals; not a measured total."
        if estimate > count
        else "Count of identified, timed records in this window; no extrapolation.",
        "passenger_ready_starts_at": (start + timedelta(minutes=20)).isoformat(),
        "passenger_ready_ends_at": (end + timedelta(minutes=20)).isoformat(),
        "passenger_ready_basis": "Illustrative 20-minute delay after arrival, not observed passenger readiness; gate and runway times differ.",
        # Compatibility only; the new phone presents a range and never a lot directive.
        "lot_arrival_target": clock(start + timedelta(minutes=20)),
        "is_peak": False,
    }


def project(saved: dict | None, now: datetime) -> dict:
    """Re-evaluate cached per-window freshness without renewing any provider timestamp."""
    current = now.astimezone(UTC)
    result = (
        copy.deepcopy(saved)
        if saved
        else {"state": "not_pulled_yet", "hours": [], "fetched_at": None}
    )
    result["server_time"] = current.isoformat()
    result["report_schema_version"] = REPORT_VERSION
    result["best_hour_label"] = "No current arrival window"
    result["best_lot_arrival_time"] = ""
    result["best_hour_starts_at"] = None
    legacy = saved is not None and saved.get("report_schema_version") != REPORT_VERSION
    hours = []
    eligible = []
    for row in result.get("hours") or []:
        if not isinstance(row, dict):
            continue
        start, end, fetched = (
            stamp(row.get("starts_at")),
            stamp(row.get("ends_at")),
            stamp(row.get("fetched_at")),
        )
        if end is None or end <= current:
            continue
        age = (current - fetched).total_seconds() if fetched else None
        row["valid_until"] = (
            (fetched + timedelta(seconds=TTL_SECONDS)).isoformat() if fetched else None
        )
        usable = (
            not legacy
            and start is not None
            and start < end
            and age is not None
            and -300 <= age < TTL_SECONDS
            and row.get("mode") in {"live", "cache"}
            and row.get("estimated_planes") is not None
        )
        row.update(usable=usable, is_peak=False)
        hours.append(row)
        if usable:
            eligible.append(row)
    result["hours"] = hours
    if eligible:
        result["state"] = "ready" if len(eligible) == len(hours) else "partial"
        peak = max(
            eligible,
            key=lambda h: (
                h["estimated_planes"],
                h.get("long_haul_count", 0),
                -h.get("hour_index", 0),
            ),
        )
        # An all-zero response is an observed empty page, not a "best time".
        if peak["estimated_planes"] > 0:
            peak["is_peak"] = True
            result["best_hour_starts_at"] = peak["starts_at"]
            result["best_hour_label"] = f"{peak['hour_label']} (~{peak['estimated_planes']} planes)"
            result["best_lot_arrival_time"] = peak.get("lot_arrival_target", "")
        result["valid_until"] = min(stamp(h["valid_until"]) for h in eligible).isoformat()
        result["summary"] = (
            "Compare returned or estimated arrivals in the remaining windows. Missing pages and unavailable hours can change the apparent peak."
        )
    else:
        result["state"] = "stale" if saved else "not_pulled_yet"
        result["valid_until"] = current.isoformat()
        result["summary"] = (
            "Refresh to obtain current arrivals. Saved rows are for inspection only."
            if saved
            else "No arrivals report has been requested. Refresh is on demand."
        )
    result["expired"] = not eligible
    result["coverage_note"] = (
        "One page per window, six requests maximum. Cargo exclusion uses a limited carrier-prefix list; passenger loads, ride requests, queue wait and rematches are unknown."
    )
    result["selection_basis"] = "most_forecast_arrivals"
    result["timing_note"] = (
        "ON timestamps describe runway arrivals; IN timestamps describe gate arrivals. Each returned flight retains its selected time field and basis."
    )
    return result
