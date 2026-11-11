"""Lossless hourly forecast retention, with no provider requests or TTL renewal.

BestTime provider days run 06:00–05:00. Keys here use each hour's normalized
calendar weekday, not the containing provider day's label. A partial scan must
never turn the other six days into freshly retrieved observations.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from farol.besttime import number, review_entry

PACIFIC = ZoneInfo("America/Los_Angeles")


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def hours(forecast):
    """Project legacy or merged records without modifying the saved receipt."""
    for day in forecast.get("days") or []:
        for raw in day.get("hours") or []:
            weekday, hour = raw.get("weekday"), raw.get("hour")
            if type(weekday) is not int or type(hour) is not int or not (0 <= weekday <= 6 and 0 <= hour <= 23):
                continue
            row = copy.deepcopy(raw)
            row.setdefault("retrieved_at", day.get("retrieved_at", forecast.get("retrieved_at")))
            row.setdefault("provenance", {
                "provider_venue_id": (forecast.get("venue") or {}).get("venue_id"),
                "basis": forecast.get("basis"),
                "provider_analysis_time": forecast.get("provider_analysis_time"),
                "source_record_hash": hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest(),
            })
            yield row


def hour_record(forecast, at):
    local = at.astimezone(PACIFIC)
    matches = [h for h in hours(forecast) if (h["weekday"], h["hour"]) == (local.weekday(), local.hour)]
    # Malformed or ambiguous duplicates must not quietly choose a convenient value.
    if not matches:
        return None
    dated = [h for h in matches if timestamp(h.get("retrieved_at"))]
    return max(dated, key=lambda h: timestamp(h["retrieved_at"])) if dated else matches[0]


def usable_hour(forecast, at, now, ttl_seconds=14*24*3600):
    row = hour_record(forecast, at)
    observed = timestamp(row.get("retrieved_at")) if row else None
    if not observed or not -300 <= (now-observed).total_seconds() <= ttl_seconds:
        return None
    return row


def merge_entries(previous, incoming):
    """Merge compatible hours only. Keep incoming live status, including failures.

    Identity checks include the full provider ID (our short radar IDs can collide).
    Original provider-day records remain in retained_forecasts for provenance;
    canonical hourly records carry their own source timestamp and metadata.
    """
    result = copy.deepcopy(incoming)
    if not previous:
        return result
    old, new = previous.get("forecast") or {}, incoming.get("forecast") or {}
    old_id, new_id = (old.get("venue") or {}).get("venue_id"), (new.get("venue") or {}).get("venue_id")
    if not old_id or old_id != new_id or not all(review_entry(e)["identity_matched"] for e in (previous, incoming)):
        return result
    combined = {}
    for forecast in (old, new):
        for row in hours(forecast):
            key = (row["weekday"], row["hour"])
            existing = combined.get(key)
            stamp, prior = timestamp(row.get("retrieved_at")), timestamp(existing.get("retrieved_at")) if existing else None
            if existing is None or (stamp and (not prior or stamp >= prior)):
                combined[key] = row
    if not combined:
        return result
    records = list(combined.values())
    # Conservative compatibility stamp for consumers that have not adopted
    # per-hour freshness. It can understate coverage but cannot renew old data.
    stamps = [timestamp(h.get("retrieved_at")) for h in records]
    valid_stamps = [s for s in stamps if s]
    retained = {}
    for forecast in (old, new):
        originals = forecast.get("retained_forecasts") or [forecast]
        for original in originals:
            record = copy.deepcopy(original)
            record.pop("retained_forecasts", None)
            key = hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()
            retained[key] = record
    # Retain receipts that actually supply canonical hours, not an unbounded scan
    # history. Every retained value can be traced to its original timestamp.
    used_stamps = {h.get("retrieved_at") for h in records}
    originals = [f for f in retained.values() if f.get("retrieved_at") in used_stamps]
    result["forecast"] = {**new, "available": True,
        "retrieved_at": min(valid_stamps).isoformat() if len(valid_stamps) == len(stamps) else None,
        "latest_retrieved_at": max(valid_stamps).isoformat() if valid_stamps else None,
        "days_available": len({h["weekday"] for h in records}),
        "days": [{"weekday": d, "hours": sorted((h for h in records if h["weekday"] == d), key=lambda h: h["hour"])}
                 for d in sorted({h["weekday"] for h in records})],
        "retained_forecasts": originals, "hourly_provenance": True}
    return result


def coverage(entries, at, now):
    """Counts describe applicable evidence, never just the number of cached rows."""
    counts = {key: 0 for key in ("cached_venues", "unmatched_identity", "missing_hour", "expired_hour",
                                "closed_hour", "usable_pattern", "usable_live")}
    timestamps = []
    for entry in entries:
        counts["cached_venues"] += 1
        checked = review_entry(entry)
        if not checked["identity_matched"]:
            counts["unmatched_identity"] += 1
            continue
        forecast, live = checked.get("forecast") or {}, checked.get("live") or {}
        record = hour_record(forecast, at)
        usable = usable_hour(forecast, at, now)
        if record is None:
            counts["missing_hour"] += 1
        elif usable is None:
            counts["expired_hour"] += 1
        elif usable.get("closed") is True:
            counts["closed_hour"] += 1
        elif number(usable.get("typical_busyness")) is not None and 0 <= usable["typical_busyness"] <= 100:
            counts["usable_pattern"] += 1
            timestamps.append(usable["retrieved_at"])
        else:
            counts["missing_hour"] += 1
        stamp = timestamp(live.get("retrieved_at"))
        if (checked["identity_review"]["live_matched"] and live.get("available") is True and
                number(live.get("busyness")) is not None and live["busyness"] >= 0 and stamp and -300 <= (now-stamp).total_seconds() <= 3600
                and live.get("open_status") not in (False, "Closed")):
            counts["usable_live"] += 1
    local = at.astimezone(PACIFIC)
    return {**counts, "weekday": local.strftime("%A"), "hour": local.hour, "timezone": str(PACIFIC),
            "oldest_usable_pattern_at": min(timestamps, key=timestamp) if timestamps else None,
            "newest_usable_pattern_at": max(timestamps, key=timestamp) if timestamps else None}
