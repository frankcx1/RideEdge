"""Local receipt imports and descriptive session summaries, never a forecast.

Run ``py -3.11 -m farol.history import <weekly.csv> [<weekly.csv> ...]``.
Only normalized trip fields are saved; input files are left in place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import threading
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from uuid import uuid4

from farol.ingest import parse_export

LEDGER_NAME = "receipts.json"
SHIFTS_NAME = "shifts.json"
OUTCOMES_NAME = "driver_outcomes.json"
_SHIFT_LOCK = threading.RLock()
TRIP_FIELDS = (
    "requested_at", "ended_at", "pickup_zone", "dropoff_zone", "duration_minutes",
    "paid_miles", "seattle_miles", "washington_miles", "seattle_minutes",
    "washington_minutes", "wait_minutes", "earnings", "tip", "customer_fare",
    "uber_kept", "minimum_fare_supplement", "airport_surcharge", "basis",
)


def trip_key(trip: dict) -> tuple:
    """Exclude money: later exports can add tips to the same trip."""
    return tuple(trip.get(key) for key in (
        "requested_at", "pickup_zone", "dropoff_zone", "duration_minutes", "paid_miles",
    ))


def merge_trips(trips: list[dict]) -> list[dict]:
    """Last supplied version wins, including updated tips; keep stable local IDs."""
    merged = {}
    for trip in trips:
        key = trip_key(trip)
        record = {name: trip[name] for name in TRIP_FIELDS if name in trip}
        digest = hashlib.sha256(json.dumps(key).encode("utf-8")).hexdigest()[:20]
        record["id"] = f"receipt-{digest}"
        merged[key] = record
    return sorted(merged.values(), key=lambda item: item["requested_at"])


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("trips"), list):
        raise ValueError("unrecognized local receipt ledger")
    return payload["trips"]


def read_local_trips(directory: Path) -> list[dict]:
    trips = []
    for path in sorted(directory.glob("*.csv"), key=lambda item: (item.stat().st_mtime, item.name)):
        trips.extend(parse_export(path))
    # Explicit imports override old raw exports, including subsequently paid tips.
    trips.extend(read_ledger(directory / LEDGER_NAME))
    return merge_trips(trips)


def import_exports(paths: list[Path], directory: Path, *, preview: bool = False) -> dict:
    """Validate every export before replacing the ledger. Later arguments win."""
    target = directory / LEDGER_NAME
    existing = read_local_trips(directory)
    incoming = []
    for path in paths:
        rows = parse_export(path)
        if not rows:
            raise ValueError(f"no recognized trip rows in {path.name}")
        incoming.extend(rows)
    merged = merge_trips([*existing, *incoming])
    old = {trip_key(trip): trip for trip in existing}
    added = sum(trip_key(trip) not in old for trip in merged)
    revised = sum(
        trip_key(trip) in old and any(
            trip.get(field) != old[trip_key(trip)].get(field) for field in TRIP_FIELDS
        )
        for trip in merged
    )
    if not preview:
        directory.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f".{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps({"schema_version": 1, "trips": merged}, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
    return {
        "preview": preview, "files": len(paths), "input_trips": len(incoming),
        "added": added, "revised": revised, "total_trips": len(merged),
        "duplicates_or_updates": len(existing) + len(incoming) - len(merged),
        "first_trip_at": merged[0]["requested_at"] if merged else None,
        "last_trip_at": merged[-1]["requested_at"] if merged else None,
    }


def _default_shifts_dir() -> Path | None:
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("FAROL_USE_FIELD_TRIPS", "") != "1":
        return None
    from farol.trips import field_data_dir

    return field_data_dir()


def _validate_finite_number(value: object, name: str, *, allow_zero: bool = True, max_val: float = 2_000_000.0) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be a finite number")
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(num):
        raise ValueError(f"{name} must be a finite number")
    if allow_zero:
        if num < 0 or num > max_val:
            raise ValueError(f"{name} must be between 0 and {max_val:g}")
    else:
        if num <= 0 or num > max_val:
            raise ValueError(f"{name} must be positive and at most {max_val:g}")
    return num


def _validate_aware_timestamp(raw: str | None, name: str) -> datetime:
    if raw is None or not str(raw).strip():
        return datetime.now().astimezone()
    try:
        dt = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid ISO-8601 timestamp") from exc
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{name} must include an explicit timezone offset")
    return dt


def _parse_stored_dt(raw: object) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return None
    return dt


def _is_valid_shift_record(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    start_odo = row.get("start_odometer_miles")
    if isinstance(start_odo, bool) or not isinstance(start_odo, (int, float)) or not math.isfinite(float(start_odo)) or float(start_odo) < 0:
        return False
    end_odo = row.get("end_odometer_miles")
    if end_odo is not None:
        if isinstance(end_odo, bool) or not isinstance(end_odo, (int, float)) or not math.isfinite(float(end_odo)) or float(end_odo) < float(start_odo):
            return False
    if _parse_stored_dt(row.get("started_at")) is None:
        return False
    if row.get("ended_at") is not None and _parse_stored_dt(row.get("ended_at")) is None:
        return False
    return True


def _enrich_shift_record(row: dict, vehicle_cost_per_mile: float = 0.45) -> dict:
    item = dict(row)
    trips = [
        t for t in (item.get("logged_trips") or [])
        if isinstance(t, dict)
        and isinstance(t.get("gross_fare"), (int, float))
        and math.isfinite(float(t.get("gross_fare")))
    ]
    item["logged_trips"] = trips
    gross = round(sum(float(t.get("gross_fare") or 0.0) for t in trips), 2)
    paid_miles = round(
        sum(float(t.get("miles") or 0.0) for t in trips if math.isfinite(float(t.get("miles") or 0.0))),
        1,
    )
    item["running_trip_count"] = len(trips)
    item["running_gross_earnings"] = gross
    item["running_paid_miles"] = paid_miles
    elapsed = item.get("committed_minutes")
    if elapsed is None and item.get("started_at"):
        start_dt = _parse_stored_dt(item.get("started_at"))
        if start_dt is not None:
            now_dt = datetime.now(start_dt.tzinfo)
            elapsed = round(max(0.0, (now_dt - start_dt).total_seconds() / 60.0), 1)
        else:
            elapsed = 0.0
    elapsed_min = float(elapsed or 0.0) if (isinstance(elapsed, (int, float)) and math.isfinite(float(elapsed))) else 0.0
    item["elapsed_minutes"] = elapsed_min
    denom_min = elapsed_min if elapsed_min >= 5.0 else (15.0 * len(trips) if trips else 0.0)
    hours = denom_min / 60.0 if denom_min > 0 else 0.0
    raw_total_miles = item.get("total_miles")
    total_miles = (
        float(raw_total_miles)
        if (isinstance(raw_total_miles, (int, float)) and math.isfinite(float(raw_total_miles)))
        else paid_miles
    )
    est_cost = round(total_miles * vehicle_cost_per_mile, 2)
    item["running_gross_per_hour"] = round(gross / hours, 2) if hours > 0 and gross > 0 else 0.0
    item["running_net_per_hour"] = (
        round((gross - est_cost) / hours, 2) if hours > 0 and gross > 0 else 0.0
    )
    return item


def read_shift_logs(directory: Path | None = None) -> list[dict]:
    target_dir = directory if directory is not None else _default_shifts_dir()
    if target_dir is None:
        return []
    path = target_dir / SHIFTS_NAME
    with _SHIFT_LOCK:
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        shifts = payload.get("shifts") if isinstance(payload, dict) else None
        return [
            _enrich_shift_record(row)
            for row in (shifts or [])
            if _is_valid_shift_record(row)
        ]


def _write_shift_logs(directory: Path, shifts: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / SHIFTS_NAME
    temporary = target.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps({"schema_version": 1, "shifts": shifts}, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def active_shift_log(directory: Path | None = None) -> dict | None:
    for row in reversed(read_shift_logs(directory)):
        if row.get("ended_at") is None:
            return _enrich_shift_record(row)
    return None


def log_shift_trip(
    gross_fare: float,
    miles: float = 0.0,
    directory: Path | None = None,
    *,
    shift_id: str | None = None,
    note: str = "",
    idempotency_key: str | None = None,
) -> dict:
    fare = round(_validate_finite_number(gross_fare, "gross_fare", allow_zero=False, max_val=10_000.0), 2)
    trip_miles = round(_validate_finite_number(miles, "miles", allow_zero=True, max_val=2_000.0), 1)
    from farol.trips import field_data_dir

    target_dir = directory if directory is not None else field_data_dir()
    clean_idem = (idempotency_key or "").strip() or None
    with _SHIFT_LOCK:
        shifts = read_shift_logs(target_dir)
        target = None
        for row in reversed(shifts):
            if shift_id and row.get("shift_id") == shift_id:
                target = row
                break
            if not shift_id and row.get("ended_at") is None:
                target = row
                break
        if target is None:
            raise ValueError("No active shift found. Start a shift before logging a ride.")
        trips = list(target.get("logged_trips") or [])
        if clean_idem:
            for existing_trip in trips:
                if isinstance(existing_trip, dict) and existing_trip.get("idempotency_key") == clean_idem:
                    return _enrich_shift_record(target)
        trip_record = {
            "trip_id": f"trip-{uuid4().hex[:8]}",
            "logged_at": datetime.now().astimezone().isoformat(),
            "gross_fare": fare,
            "miles": trip_miles,
            "note": note.strip(),
        }
        if clean_idem:
            trip_record["idempotency_key"] = clean_idem
        trips.append(trip_record)
        target["logged_trips"] = trips
        enriched = _enrich_shift_record(target)
        target.update(enriched)
        _write_shift_logs(target_dir, shifts)
        return enriched


def start_shift_log(
    odometer_miles: float,
    directory: Path | None = None,
    *,
    started_at: str | None = None,
    note: str = "",
    idempotency_key: str | None = None,
) -> dict:
    miles = round(_validate_finite_number(odometer_miles, "odometer_miles", allow_zero=True, max_val=2_000_000.0), 1)
    start_dt = _validate_aware_timestamp(started_at, "started_at")
    from farol.trips import field_data_dir

    target_dir = directory if directory is not None else field_data_dir()
    clean_idem = (idempotency_key or "").strip() or None
    with _SHIFT_LOCK:
        shifts = read_shift_logs(target_dir)
        for row in shifts:
            if row.get("ended_at") is None:
                if clean_idem and row.get("idempotency_key") == clean_idem:
                    return row
                raise ValueError("A shift odometer log is already active; end it first.")
        record = {
            "shift_id": f"shift-{uuid4().hex[:12]}",
            "started_at": start_dt.isoformat(),
            "ended_at": None,
            "start_odometer_miles": miles,
            "end_odometer_miles": None,
            "total_miles": None,
            "committed_minutes": None,
            "note": note.strip(),
        }
        if clean_idem:
            record["idempotency_key"] = clean_idem
        shifts.append(record)
        _write_shift_logs(target_dir, shifts)
        return record


def end_shift_log(
    odometer_miles: float,
    directory: Path | None = None,
    *,
    shift_id: str | None = None,
    ended_at: str | None = None,
    note: str = "",
    idempotency_key: str | None = None,
) -> dict:
    miles = round(_validate_finite_number(odometer_miles, "odometer_miles", allow_zero=True, max_val=2_000_000.0), 1)
    end_dt = _validate_aware_timestamp(ended_at, "ended_at")
    from farol.trips import field_data_dir

    target_dir = directory if directory is not None else field_data_dir()
    clean_idem = (idempotency_key or "").strip() or None
    with _SHIFT_LOCK:
        shifts = read_shift_logs(target_dir)
        if clean_idem:
            for row in reversed(shifts):
                if row.get("end_idempotency_key") == clean_idem:
                    return row
        target = None
        for row in reversed(shifts):
            if shift_id and row.get("shift_id") == shift_id:
                target = row
                break
            if not shift_id and row.get("ended_at") is None:
                target = row
                break
        if target is None:
            raise ValueError("No active shift odometer log found to end.")
        start_miles = float(target["start_odometer_miles"])
        if miles < start_miles:
            raise ValueError("end_odometer_miles cannot be less than start_odometer_miles")
        start_dt = _parse_stored_dt(target.get("started_at"))
        if start_dt is None:
            raise ValueError("Stored shift started_at is invalid")
        if end_dt <= start_dt:
            raise ValueError("ended_at must be after started_at")
        target["ended_at"] = end_dt.isoformat()
        target["end_odometer_miles"] = miles
        target["total_miles"] = round(miles - start_miles, 1)
        target["committed_minutes"] = round((end_dt - start_dt).total_seconds() / 60.0, 1)
        if clean_idem:
            target["end_idempotency_key"] = clean_idem
        if note.strip():
            target["note"] = (f"{target.get('note', '')} {note.strip()}").strip()
        _write_shift_logs(target_dir, shifts)
        return target


def log_driver_outcome(
    status: str,
    zone: str = "",
    recommended_action: str = "",
    note: str = "",
    directory: Path | None = None,
    *,
    idempotency_key: str | None = None,
    recommendation_id: str | None = None,
    evidence_version: str | None = None,
    recorded_at: str | None = None,
) -> dict:
    """Log driver availability / waiting / request / ride / break outcomes to measure pickup exposure."""
    allowed_statuses = {
        "waiting",
        "request_received",
        "accepted_ride",
        "break",
        "offline",
        "repositioned",
        "no_request",
        "no_request_after_15m",
    }
    clean_status = status.strip().lower()
    if clean_status not in allowed_statuses:
        raise ValueError(f"status must be one of {sorted(allowed_statuses)}")
    rec_dt = _validate_aware_timestamp(recorded_at, "recorded_at") if recorded_at else datetime.now(UTC)
    from farol.trips import field_data_dir

    target_dir = directory if directory is not None else field_data_dir()
    path = target_dir / OUTCOMES_NAME
    clean_idem = (idempotency_key or "").strip() or None
    with _SHIFT_LOCK:
        target_dir.mkdir(parents=True, exist_ok=True)
        existing: list[dict] = []
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("outcomes"), list):
                    existing = [r for r in raw["outcomes"] if isinstance(r, dict)]
            except (OSError, ValueError):
                existing = []
        if clean_idem:
            for item in reversed(existing):
                if item.get("idempotency_key") == clean_idem:
                    return item
        entry = {
            "id": f"outcome-{uuid4().hex[:10]}",
            "recorded_at": rec_dt.astimezone(UTC).isoformat(),
            "status": clean_status,
            "zone": zone.strip(),
            "recommended_action": recommended_action.strip(),
            "recommendation_id": (recommendation_id or "").strip() or None,
            "evidence_version": (evidence_version or "v2").strip(),
            "note": note.strip(),
        }
        if clean_idem:
            entry["idempotency_key"] = clean_idem
        existing.append(entry)
        temp = path.with_suffix(f".{uuid4().hex}.tmp")
        temp.write_text(json.dumps({"schema_version": 1, "outcomes": existing}, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
        return entry


def read_driver_outcomes(directory: Path | None = None, limit: int | None = 50) -> list[dict]:
    target_dir = directory if directory is not None else _default_shifts_dir()
    if target_dir is None:
        return []
    path = target_dir / OUTCOMES_NAME
    with _SHIFT_LOCK:
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            rows = raw.get("outcomes") if isinstance(raw, dict) else []
            valid = [r for r in (rows or []) if isinstance(r, dict)]
            return valid[-limit:] if (isinstance(limit, int) and limit > 0) else valid
        except (OSError, ValueError):
            return []


MAX_OUTCOME_AGE_DAYS = 14.0


def summarize_zone_outcomes(
    outcomes: list[dict] | None = None,
    *,
    directory: Path | None = None,
    now: datetime | None = None,
) -> dict[str, dict]:
    """Convert logged driver outcome transitions into zone-level waiting exposure & ping adjustments.

    Models linked waiting -> ping -> ride episodes so:
    - `Waiting -> Got Ping -> On Ride` and `Waiting -> On Ride` both count as 1 matched episode.
    - Repeated `Waiting` taps during a continuous wait in the same zone do not create fake dry waits
      or reset the episode start timestamp.
    - Events older than `MAX_OUTCOME_AGE_DAYS` are excluded from active scoring adjustments.
    """
    from farol.zones import canonical_zone

    rows = outcomes if outcomes is not None else read_driver_outcomes(directory, limit=None)
    if not rows:
        return {}
    ref_now = (now or datetime.now(UTC)).astimezone(UTC)
    parsed_events: list[tuple[datetime, dict]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        dt = _parse_stored_dt(r.get("recorded_at"))
        if dt is None:
            continue
        parsed_events.append((dt.astimezone(UTC), r))
    parsed_events.sort(key=lambda x: x[0])

    by_zone: dict[str, dict] = {}

    def _bucket(z_raw: str) -> dict | None:
        if not z_raw or not str(z_raw).strip():
            return None
        try:
            zid = canonical_zone(str(z_raw).strip())
        except Exception:
            zid = str(z_raw).strip().lower().replace(" ", "_")
        if not zid:
            return None
        return by_zone.setdefault(
            zid,
            {
                "zone": zid,
                "waiting_events": 0,
                "available_wait_minutes": 0.0,
                "matched_episodes": 0,
                "requests_received": 0,
                "accepted_rides": 0,
                "unsuccessful_waits": 0,
                "repeated_wait_taps": 0,
                "stale_events_excluded": 0,
                "break_events": 0,
                "offline_events": 0,
                "ping_wait_samples": [],
            },
        )

    active_episode: dict | None = None
    for dt, ev in parsed_events:
        st = str(ev.get("status") or "").strip().lower()
        b = _bucket(str(ev.get("zone") or ""))
        age_days = (ref_now - dt).total_seconds() / 86400.0
        if age_days > MAX_OUTCOME_AGE_DAYS or age_days < -0.1:
            if b is not None:
                b["stale_events_excluded"] += 1
            continue

        if st == "break":
            if b is not None:
                b["break_events"] += 1
            if active_episode is not None:
                if active_episode["state"] == "waiting":
                    wb = _bucket(active_episode["zone"])
                    if wb is not None:
                        wb["available_wait_minutes"] += min(
                            60.0, max(0.0, (dt - active_episode["started_at"]).total_seconds() / 60.0)
                        )
                active_episode = None
            continue
        if st == "offline":
            if b is not None:
                b["offline_events"] += 1
            if active_episode is not None:
                if active_episode["state"] == "waiting":
                    wb = _bucket(active_episode["zone"])
                    if wb is not None:
                        wb["available_wait_minutes"] += min(
                            60.0, max(0.0, (dt - active_episode["started_at"]).total_seconds() / 60.0)
                        )
                active_episode = None
            continue

        if st == "waiting":
            target_zone = b["zone"] if b is not None else None
            if (
                active_episode is not None
                and active_episode["state"] == "waiting"
                and target_zone is not None
                and active_episode["zone"] == target_zone
                and (dt - active_episode["last_at"]).total_seconds() <= 3600.0
            ):
                # Continuous wait in the same zone: keep original episode start time
                active_episode["last_at"] = dt
                if b is not None:
                    b["repeated_wait_taps"] += 1
                continue

            if active_episode is not None and active_episode["state"] == "waiting":
                wb = _bucket(active_episode["zone"])
                if wb is not None:
                    gap_m = min(60.0, max(0.0, (dt - active_episode["started_at"]).total_seconds() / 60.0))
                    wb["available_wait_minutes"] += gap_m
                    if gap_m >= 10.0:
                        wb["unsuccessful_waits"] += 1
            if b is not None:
                b["waiting_events"] += 1
                active_episode = {
                    "zone": b["zone"],
                    "started_at": dt,
                    "last_at": dt,
                    "state": "waiting",
                    "pinged_at": None,
                }
            else:
                active_episode = None
        elif st in {"request_received", "accepted_ride"}:
            target_b = b
            if target_b is None and active_episode is not None:
                target_b = _bucket(active_episode["zone"])

            if (
                active_episode is not None
                and active_episode["state"] == "waiting"
                and (target_b is None or active_episode["zone"] == target_b["zone"])
            ):
                wb = _bucket(active_episode["zone"])
                wait_m = min(60.0, max(0.0, (dt - active_episode["started_at"]).total_seconds() / 60.0))
                if wb is not None:
                    wb["available_wait_minutes"] += wait_m
                    wb["ping_wait_samples"].append(wait_m)
                    wb["matched_episodes"] += 1
                    wb["requests_received"] += 1
                    if st == "accepted_ride":
                        wb["accepted_rides"] += 1
                active_episode["last_at"] = dt
                active_episode["pinged_at"] = dt
                active_episode["state"] = "accepted" if st == "accepted_ride" else "pinged"
            elif (
                st == "accepted_ride"
                and active_episode is not None
                and active_episode["state"] == "pinged"
                and (target_b is None or active_episode["zone"] == target_b["zone"])
                and (dt - (active_episode["pinged_at"] or active_episode["last_at"])).total_seconds() <= 900.0
            ):
                # Linked acceptance of the already-counted request in the same episode
                wb = _bucket(active_episode["zone"])
                if wb is not None:
                    ping_dt = active_episode["pinged_at"] or active_episode["last_at"]
                    confirm_m = min(15.0, max(0.0, (dt - ping_dt).total_seconds() / 60.0))
                    wb["available_wait_minutes"] += confirm_m
                    wb["accepted_rides"] += 1
                active_episode["last_at"] = dt
                active_episode["state"] = "accepted"
            else:
                if active_episode is not None and active_episode["state"] == "waiting":
                    wb = _bucket(active_episode["zone"])
                    if wb is not None:
                        wait_m = min(60.0, max(0.0, (dt - active_episode["started_at"]).total_seconds() / 60.0))
                        wb["available_wait_minutes"] += wait_m
                if target_b is not None:
                    target_b["matched_episodes"] += 1
                    target_b["requests_received"] += 1
                    if st == "accepted_ride":
                        target_b["accepted_rides"] += 1
                    active_episode = {
                        "zone": target_b["zone"],
                        "started_at": dt,
                        "last_at": dt,
                        "state": "accepted" if st == "accepted_ride" else "pinged",
                        "pinged_at": dt,
                    }
                else:
                    active_episode = None
        elif st in {"repositioned", "no_request", "no_request_after_15m"}:
            if active_episode is not None and active_episode["state"] == "waiting":
                wb = _bucket(active_episode["zone"])
                if wb is not None:
                    wait_m = min(60.0, max(0.0, (dt - active_episode["started_at"]).total_seconds() / 60.0))
                    wb["available_wait_minutes"] += wait_m
                    if st in {"repositioned", "no_request_after_15m"} or wait_m >= 15.0:
                        wb["unsuccessful_waits"] += 1
            active_episode = None

    if active_episode is not None and active_episode["state"] == "waiting":
        wb = _bucket(active_episode["zone"])
        if wb is not None:
            open_m = min(60.0, max(0.0, (ref_now - active_episode["started_at"]).total_seconds() / 60.0))
            wb["available_wait_minutes"] += open_m
            if open_m >= 15.0:
                wb["unsuccessful_waits"] += 1

    result: dict[str, dict] = {}
    for zid, info in by_zone.items():
        samples = info.pop("ping_wait_samples", [])
        mean_ping = round(sum(samples) / len(samples), 1) if samples else None
        positives = int(info["matched_episodes"])
        unsuccessful = int(info["unsuccessful_waits"])
        wait_events = int(info["waiting_events"])
        adj = min(4.0, positives * 1.25) - min(4.5, unsuccessful * 1.5)
        if positives == 0 and wait_events >= 1 and unsuccessful == 0:
            adj -= min(2.0, wait_events * 0.75)
        adj = round(max(-4.5, min(4.0, adj)), 2)
        note = ""
        if positives > 0 or unsuccessful > 0 or wait_events > 0:
            note = (
                f"Logged outcomes: {positives} ping/ride event(s), {unsuccessful} dry wait(s), "
                f"{info['available_wait_minutes']:.0f}m available wait"
            )
        result[zid] = {
            **info,
            "available_wait_minutes": round(float(info["available_wait_minutes"]), 1),
            "mean_minutes_to_ping": mean_ping,
            "score_adjustment": adj,
            "note": note,
        }
    return result


def _match_shift_log(
    first: datetime,
    last: datetime,
    shift_logs: list[dict],
    used_shift_ids: set[str] | None = None,
) -> dict | None:
    """R14: Require actual temporal containment/overlap between the receipt span and shift interval."""
    first_utc = first.astimezone(UTC)
    last_utc = last.astimezone(UTC)
    candidates: list[tuple[float, dict]] = []
    for row in shift_logs:
        sid = str(row.get("shift_id") or "")
        if used_shift_ids is not None and sid and sid in used_shift_ids:
            continue
        if not row.get("started_at") or not row.get("ended_at"):
            continue
        if row.get("start_odometer_miles") is None or row.get("end_odometer_miles") is None:
            continue
        s_start = _parse_stored_dt(row.get("started_at"))
        s_end = _parse_stored_dt(row.get("ended_at"))
        if s_start is None or s_end is None:
            continue
        s_start_utc = s_start.astimezone(UTC)
        s_end_utc = s_end.astimezone(UTC)
        if s_end_utc <= s_start_utc:
            continue
        # Require actual overlap AND that the receipt session falls within the shift (with up to 15m post-shift dropoff tolerance)
        if s_start_utc > last_utc or s_end_utc < first_utc:
            continue
        if first_utc < s_start_utc - timedelta(minutes=10) or last_utc > s_end_utc + timedelta(minutes=15):
            continue
        overlap_start = max(first_utc, s_start_utc)
        overlap_end = min(last_utc, s_end_utc)
        overlap_sec = (overlap_end - overlap_start).total_seconds()
        if overlap_sec < 0:
            continue
        candidates.append((overlap_sec, row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    best_row = candidates[0][1]
    if used_shift_ids is not None and best_row.get("shift_id"):
        used_shift_ids.add(str(best_row["shift_id"]))
    return best_row


def summarize_history(
    trips: list[dict],
    vehicle_cost_per_mile: float = 0.45,
    *,
    shift_logs: list[dict] | None = None,
) -> dict:
    """Split at gaps over four hours; retain post-midnight trips in their session.

    Receipt spans are not committed shift hours. No net hourly rate or claim
    about clearing the driver's floor can be inferred from these records alone
    unless paired with a driver-recorded shift odometer log.
    """
    ordered = merge_trips(trips)
    logs = shift_logs if shift_logs is not None else read_shift_logs()
    groups: list[list[dict]] = []
    last_end = None
    for trip in ordered:
        start = datetime.fromisoformat(trip["requested_at"])
        end = datetime.fromisoformat(trip["ended_at"])
        if last_end is None or start - last_end > timedelta(hours=4):
            groups.append([])
        groups[-1].append(trip)
        last_end = max(last_end, end) if last_end is not None else end
    sessions = []
    used_shift_ids: set[str] = set()
    for group in groups:
        first = datetime.fromisoformat(group[0]["requested_at"])
        last = max(datetime.fromisoformat(trip["ended_at"]) for trip in group)
        operating_date = (first - timedelta(hours=4)).date()
        gross = round(sum(trip["earnings"] for trip in group), 2)
        paid_miles = round(sum(trip["paid_miles"] for trip in group), 2)
        paid_cost = round(paid_miles * vehicle_cost_per_mile, 2)
        row = {
            "date": operating_date.isoformat(), "weekday": operating_date.strftime("%A"),
            "first_request_at": first.isoformat(), "last_dropoff_at": last.isoformat(),
            "trips": len(group), "gross_earnings": gross,
            "completed_trip_count": sum(float(trip.get("duration_minutes") or 0) > 0 for trip in group),
            "tips_included": round(sum(trip.get("tip", 0) for trip in group), 2),
            "paid_miles": paid_miles,
            "paid_mile_cost": paid_cost,
            "earnings_after_paid_mile_cost": round(gross - paid_cost, 2),
            "receipt_span_minutes": round((last - first).total_seconds() / 60, 1),
            "on_trip_minutes": round(sum(trip["duration_minutes"] for trip in group), 1),
            "pickup_zones": dict(Counter(trip["pickup_zone"] for trip in group)),
            "net_per_committed_hour": None,
        }
        matched_shift = _match_shift_log(first, last, logs, used_shift_ids)
        if matched_shift is not None:
            s_start = datetime.fromisoformat(matched_shift["started_at"])
            s_end = datetime.fromisoformat(matched_shift["ended_at"])
            committed_min = round(
                max((s_end - s_start).total_seconds() / 60.0, row["receipt_span_minutes"]), 1
            )
            odometer_delta = float(matched_shift["end_odometer_miles"]) - float(
                matched_shift["start_odometer_miles"]
            )
            total_miles = round(max(odometer_delta, paid_miles), 2)
            deadhead_miles = round(max(0.0, total_miles - paid_miles), 2)
            total_cost = round(total_miles * vehicle_cost_per_mile, 2)
            net_earnings = round(gross - total_cost, 2)
            row.update(
                shift_log_id=matched_shift.get("shift_id"),
                committed_minutes=committed_min,
                total_miles=total_miles,
                deadhead_miles=deadhead_miles,
                total_mile_cost=total_cost,
                net_earnings=net_earnings,
                net_per_committed_hour=(
                    round(net_earnings / (committed_min / 60.0), 2)
                    if committed_min > 0
                    else None
                ),
            )
        sessions.append(row)
    fridays = [item for item in sessions if item["weekday"] == "Friday"]
    calibrated = [
        item["net_per_committed_hour"]
        for item in sessions
        if item["net_per_committed_hour"] is not None
    ]
    if calibrated:
        status = "calibrated" if len(calibrated) == len(sessions) else "calibrated_partial"
    else:
        status = "uncalibrated"
    result = {
        "trips": len(ordered), "session_count": len(sessions),
        "completed_trip_count": sum(float(trip.get("duration_minutes") or 0) > 0 for trip in ordered),
        "session_basis": "receipt gaps over 4 hours; driving date rolls at 4 AM",
        "sessions": list(reversed(sessions)),
        "friday_sessions": len(fridays),
        "friday_median_gross": round(median(item["gross_earnings"] for item in fridays), 2)
        if fridays else None,
        "earnings_status": status,
        "note": (
            "Past receipts include tips and cancellation payments. Session boundaries are inferred; the first request "
            "and last drop-off exclude travel from and to home. Costs cover paid miles only. "
            "Full shift time and total driving miles are missing, so net hourly earnings "
            "and whether your time floor was met remain unknown."
        ),
    }
    if calibrated:
        result["calibrated_sessions"] = len(calibrated)
        result["calibrated_median_net_per_hour"] = round(median(calibrated), 2)
    return result


def main() -> None:
    from farol.trips import field_data_dir, load_observed_trips

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="import WA receipt CSVs without copying addresses")
    importer.add_argument("csv", nargs="+", type=Path)
    importer.add_argument("--preview", action="store_true")
    commands.add_parser("summary", help="summarize the local receipt history")
    shift_start = commands.add_parser("shift-start", help="record shift start odometer miles")
    shift_start.add_argument("odometer_miles", type=float)
    shift_start.add_argument("--note", default="")
    shift_end = commands.add_parser("shift-end", help="record shift end odometer miles")
    shift_end.add_argument("odometer_miles", type=float)
    shift_end.add_argument("--note", default="")
    commands.add_parser("shifts", help="list recorded shift odometer bookmarks")
    args = parser.parse_args()
    if args.command == "import":
        result = import_exports(args.csv, field_data_dir(), preview=args.preview)
    elif args.command == "shift-start":
        result = start_shift_log(args.odometer_miles, field_data_dir(), note=args.note)
    elif args.command == "shift-end":
        result = end_shift_log(args.odometer_miles, field_data_dir(), note=args.note)
    elif args.command == "shifts":
        result = {"active": active_shift_log(field_data_dir()), "shifts": read_shift_logs(field_data_dir())}
    else:
        result = summarize_history(load_observed_trips())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
