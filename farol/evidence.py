"""Central signal hygiene: validate, then collapse duplicate event coverage.

Adapters stay independently fallible. This module runs after gather so one
bad timestamp cannot crash scoring, and Ticketmaster+SeatGeek cannot double
a let-out as two crowds.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from farol.signals import Signal
from farol.zones import canonical_zone, load_zones

KNOWN_KINDS = {
    "closing_wave",
    "event_exit",
    "special_event",
    "cruise_disembark",
    "airport_arrivals",
    "doctrine_penalty",
    "precipitation",
    "highway_alert",
    "travel_delay",
    "transit_disruption",
    "driver_intel",
    "supply",
    "rate_card",
}
EVENT_KINDS = {
    "closing_wave",
    "event_exit",
    "special_event",
    "cruise_disembark",
    "airport_arrivals",
}
_SECRET_KEYS = {
    "key",
    "apikey",
    "api_key",
    "accesscode",
    "access_code",
    "token",
    "client_secret",
    "secret",
    "password",
    "x-apikey",
    "client_id",
}


def parse_time(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return stamp


def format_clock(value: object) -> str:
    stamp = value if isinstance(value, datetime) else parse_time(value)
    if stamp is None:
        return ""
    hour = stamp.hour % 12 or 12
    ampm = "am" if stamp.hour < 12 else "pm"
    return f"{hour}:{stamp.minute:02d} {ampm}"


def http_source(url: str) -> bool:
    raw = (url or "").strip().lower()
    return raw.startswith("http://") or raw.startswith("https://")


def redact_url(url: str) -> str:
    """Persist a fetch URL without credential query params or userinfo."""
    if not url:
        return ""
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower().replace("-", "_")
        if lowered in _SECRET_KEYS or "key" in lowered or "secret" in lowered or "token" in lowered:
            query.append((key, "REDACTED"))
        else:
            query.append((key, value))
    host = parts.netloc.rsplit("@", 1)[-1] if "@" in parts.netloc else parts.netloc
    return urlunsplit((parts.scheme, host, parts.path, urlencode(query), parts.fragment))


def sanitize_signal(signal: Signal, allowed_zones: set[str] | None = None) -> Signal | None:
    """Drop or clamp a row so scoring can iterate without try/except."""
    try:
        if signal.kind not in KNOWN_KINDS:
            return None
        zones = allowed_zones if allowed_zones is not None else {zone.id for zone in load_zones().zones}
        zone = canonical_zone(signal.zone)
        if zone not in zones and zone != "all":
            return None
        starts = parse_time(signal.starts_at)
        ends = parse_time(signal.ends_at)
        # R19: Check tzinfo BEFORE comparing ends < starts so mixed naive/aware datetimes never raise TypeError
        if starts is None or ends is None or starts.tzinfo is None or ends.tzinfo is None:
            return None
        if ends < starts:
            return None
        try:
            magnitude = float(signal.magnitude)
        except (TypeError, ValueError):
            return None
        if not (magnitude == magnitude) or magnitude < 0:  # NaN check
            return None
        magnitude = min(magnitude, 50_000.0)
        try:
            quality = float(signal.evidence_quality)
        except (TypeError, ValueError):
            quality = 0.3
        quality = max(0.0, min(1.0, quality))
        basis = signal.basis if signal.basis in {"scheduled", "live", "assumed"} else "assumed"
        details = dict(signal.details or {})
        return replace(
            signal,
            zone=zone,
            starts_at=starts.isoformat(),
            ends_at=ends.isoformat(),
            magnitude=magnitude,
            evidence_quality=quality,
            basis=basis,
            details=details,
        )
    except Exception:
        return None


def sanitize_signals(signals: list[Signal]) -> list[Signal]:
    allowed = {zone.id for zone in load_zones().zones} | {"all"}
    kept = []
    for item in signals:
        clean = sanitize_signal(item, allowed)
        if clean is not None:
            kept.append(clean)
    return kept


def _title_slug(signal: Signal) -> str:
    title = str((signal.details or {}).get("title") or signal.id)
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:28]


def _venue_slug(raw: object) -> str:
    text = str(raw or "").lower().strip()
    if not text:
        return ""
    text = re.sub(r"^the\s+", "", text)
    text = re.sub(r"\s*[-–—]\s*(wa|seattle|bellevue|kirkland|redmond)$", "", text)
    text = text.replace("theatre", "theater")
    return re.sub(r"[^a-z0-9]+", "", text)


def event_key(signal: Signal) -> tuple:
    """Same venue/time/kind collapses across providers. Doctrine and roads stay unique."""
    if signal.kind not in EVENT_KINDS:
        return ("id", signal.id)
    details = signal.details or {}
    venue = (
        str(details.get("venue_id") or details.get("venueId") or details.get("tm_id") or "")
        or _venue_slug(details.get("venue"))
    )
    start = parse_time(signal.starts_at)
    if start is None:
        return ("id", signal.id)
    bucket = start.replace(second=0, microsecond=0, minute=(start.minute // 30) * 30)
    return (signal.kind, signal.zone, bucket.isoformat(), venue or _title_slug(signal))


def dedupe_events(signals: list[Signal]) -> list[Signal]:
    """One crowd per event. Extra providers become receipts, not extra points."""
    chosen: dict[tuple, Signal] = {}
    order: list[tuple] = []
    venue_buckets: list[tuple[str, str, str, datetime, tuple]] = []
    for item in signals:
        key = event_key(item)
        if key not in chosen and item.kind in EVENT_KINDS:
            details = item.details or {}
            v_slug = (
                str(details.get("venue_id") or details.get("venueId") or details.get("tm_id") or "")
                or _venue_slug(details.get("venue"))
            )
            item_start = parse_time(item.starts_at)
            if v_slug and item_start is not None:
                for kind_k, zone_k, slug_k, start_k, existing_key in venue_buckets:
                    if (
                        kind_k == item.kind
                        and zone_k == item.zone
                        and slug_k == v_slug
                        and abs((item_start - start_k).total_seconds()) <= 90 * 60
                    ):
                        key = existing_key
                        break
                else:
                    venue_buckets.append((item.kind, item.zone, v_slug, item_start, key))
        if key not in chosen:
            chosen[key] = item
            order.append(key)
            continue
        current = chosen[key]
        receipts = list((current.details or {}).get("receipts") or [current.source])
        if item.source and item.source not in receipts:
            receipts.append(item.source)
        better = item if (item.evidence_quality, item.magnitude) > (
            current.evidence_quality,
            current.magnitude,
        ) else current
        other = current if better is item else item
        details = dict(better.details or {})
        details["receipts"] = receipts
        if other.id != better.id:
            details.setdefault("merged_ids", [])
            if other.id not in details["merged_ids"]:
                details["merged_ids"].append(other.id)
        chosen[key] = replace(
            better,
            magnitude=max(better.magnitude, other.magnitude),
            evidence_quality=max(better.evidence_quality, other.evidence_quality),
            details=details,
        )
    return [chosen[key] for key in order]
