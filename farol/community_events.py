"""Local community event catalog. Reads never crawl or call a model.

Each source occurrence keeps its own receipts and revisions. Public views merge
corroborating listings, preserve uncertain hours, and never manufacture demand.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from farol.dashboard import ROOT
from farol.signals import Signal
from farol.zones import load_zones

PACIFIC = ZoneInfo("America/Los_Angeles")
SOURCES = {
    "visit_seattle": {"name": "Visit Seattle", "url": "https://visitseattle.org/things-to-do/events/", "rank": 1},
    "seattle_center": {"name": "Seattle Center Festál", "url": "https://www.seattlecenter.com/events/featured-events/festal", "rank": 3},
    "farmers_markets": {"name": "Seattle Neighborhood Farmers Markets", "url": "https://seattlefarmersmarkets.org/", "rank": 3},
    "neighborhoods": {"name": "Seattle Department of Neighborhoods", "url": "https://www.seattle.gov/neighborhoods/event-calendar", "rank": 2},
    "redmond_city": {"name": "City of Redmond", "url": "https://www.redmond.gov/calendar.aspx?CID=22", "rank": 3},
    "king_county_parks": {"name": "King County Parks · Redmond", "url": "https://kingcounty.gov/en/dept/dnrp/nature-recreation/parks-recreation/king-county-parks/get-involved/parks-events", "rank": 3},
}
CITY_BOUNDS = {"Seattle": (47.45, 47.8, -122.5, -122.2),
               "Redmond": (47.57, 47.78, -122.20, -121.98)}


def directory() -> Path:
    return Path(os.environ.get("FAROL_EVENTS_DIR") or ROOT / ".cache" / "community-events")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"\bfestal\s*:?|\b20\d{2}\b|\bthe\b", "", value.lower())
    return re.sub(r"[^a-z0-9]+", "", value)


def safe_url(value: str | None) -> str | None:
    try:
        parsed = urlsplit(value or "")
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return None


def atomic_json(path: Path, value) -> None:
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     delete=False, suffix=".tmp") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        temp = Path(handle.name)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


SCHEMA = """
CREATE TABLE IF NOT EXISTS occurrences (
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_key TEXT NOT NULL,
 local_date TEXT NOT NULL, payload TEXT NOT NULL, content_hash TEXT NOT NULL,
 first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, changed_at TEXT NOT NULL,
 missing_since TEXT, UNIQUE(source_id, source_key)
);
CREATE INDEX IF NOT EXISTS event_days ON occurrences(local_date);
CREATE TABLE IF NOT EXISTS revisions (
 id INTEGER PRIMARY KEY, occurrence_id TEXT NOT NULL, observed_at TEXT NOT NULL,
 payload TEXT NOT NULL, reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
 source_id TEXT PRIMARY KEY, last_attempt TEXT, last_success TEXT, state TEXT,
 item_count INTEGER, detail TEXT, requests INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, report TEXT
);
"""


@contextmanager
def connect(folder: Path | None = None, *, write=False):
    path = (folder or directory()) / "events.db"
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA)
    else:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        if write:
            connection.commit()
    finally:
        connection.close()


def validate(row: dict) -> dict:
    """Reject malformed occurrences; nullable hours are deliberately preserved."""
    row = dict(row)
    if row.get("source_id") not in SOURCES or not row.get("source_key"):
        raise ValueError("Unknown event source or missing source identity")
    if not str(row.get("title", "")).strip() or not safe_url(row.get("source_url")):
        raise ValueError("Event needs a title and source link")
    day = date.fromisoformat(row["local_date"])
    for key in ("starts_at", "ends_at"):
        if row.get(key):
            stamp = datetime.fromisoformat(row[key])
            if stamp.tzinfo is None:
                raise ValueError("Event hours must include a timezone")
            row[key] = stamp.astimezone(PACIFIC).isoformat()
    if row.get("starts_at") and datetime.fromisoformat(row["starts_at"]).date() != day:
        raise ValueError("Occurrence day differs from event start")
    if row.get("starts_at") and row.get("ends_at"):
        start, end = (datetime.fromisoformat(row[key]) for key in ("starts_at", "ends_at"))
        if not timedelta(0) < end - start <= timedelta(days=1):
            raise ValueError("Invalid daily event hours")
    if row.get("status") not in {"scheduled", "canceled", "postponed"}:
        raise ValueError("Unknown event status")
    if row.get("city") not in CITY_BOUNDS:
        raise ValueError("This collector covers Seattle and Redmond")
    lat, lon = row.get("lat"), row.get("lon")
    if (lat is None) != (lon is None):
        raise ValueError("Incomplete event coordinates")
    south, north, west, east = CITY_BOUNDS[row["city"]]
    if lat is not None and not (south <= float(lat) <= north and west <= float(lon) <= east):
        raise ValueError("Event coordinates outside its city's bounds")
    if row.get("schedule_warnings"):
        row["schedule_warnings"] = [str(note)[:300] for note in row["schedule_warnings"]][:5]
    else:
        row.pop("schedule_warnings", None)
    row["organizer_url"] = safe_url(row.get("organizer_url"))
    # Bounds also protect the UI from unexpectedly enormous upstream descriptions.
    for key, limit in (("title", 240), ("venue", 240), ("address", 350), ("evidence", 1600),
                       ("notes", 600), ("organizer", 200)):
        row[key] = str(row.get(key) or "")[:limit]
    return row


def store_source(source_id: str, rows: list[dict], *, now: datetime, first: date,
                 last: date, state="ready", detail="", requests=0, folder=None) -> dict:
    """One transaction per source. A failed/partial fetch never erases old events."""
    stamp = now.astimezone(UTC).isoformat()
    rows = [validate(row) for row in rows]
    if any(row["source_id"] != source_id for row in rows):
        raise ValueError("Mixed source transaction")
    with connect(folder, write=True) as conn:
        seen, added, changed = set(), 0, 0
        for row in rows:
            ident = digest(source_id + ":" + row["source_key"])
            seen.add(ident)
            payload = json.dumps(row, sort_keys=True, ensure_ascii=False)
            fingerprint = digest(payload)
            previous = conn.execute("SELECT * FROM occurrences WHERE id=?", (ident,)).fetchone()
            if previous is None or previous["content_hash"] != fingerprint:
                reason = "added" if previous is None else "changed"
                conn.execute("INSERT INTO revisions(occurrence_id,observed_at,payload,reason) VALUES(?,?,?,?)",
                             (ident, stamp, payload, reason))
                added += previous is None
                changed += previous is not None
            conn.execute("""INSERT INTO occurrences VALUES(?,?,?,?,?,?,?,?,?,NULL)
                ON CONFLICT(id) DO UPDATE SET local_date=excluded.local_date,
                payload=excluded.payload, content_hash=excluded.content_hash,
                last_seen=excluded.last_seen, changed_at=CASE
                WHEN occurrences.content_hash!=excluded.content_hash THEN excluded.changed_at
                ELSE occurrences.changed_at END, missing_since=NULL""",
                (ident, source_id, row["source_key"], row["local_date"], payload,
                 fingerprint, stamp, stamp, stamp))
        # Absence is uncertainty, not proof of cancellation. Only complete successful
        # enumerations can mark a previously seen listing absent.
        if state == "ready":
            for old in conn.execute("SELECT id,missing_since FROM occurrences WHERE source_id=? AND local_date BETWEEN ? AND ?",
                                    (source_id, first.isoformat(), last.isoformat())):
                if old["id"] not in seen and not old["missing_since"]:
                    conn.execute("UPDATE occurrences SET missing_since=? WHERE id=?", (stamp, old["id"]))
        conn.execute("""INSERT INTO sources VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET last_attempt=excluded.last_attempt,
            last_success=COALESCE(excluded.last_success,sources.last_success), state=excluded.state,
            item_count=excluded.item_count,detail=excluded.detail,requests=excluded.requests""",
            (source_id, stamp, stamp if state == "ready" else None, state, len(rows), detail[:1500], requests))
    return {"source_id": source_id, "name": SOURCES[source_id]["name"], "state": state,
            "count": len(rows), "added": added, "changed": changed, "detail": detail,
            "requests": requests}


def records(first: date, last: date, *, folder=None) -> list[dict]:
    try:
        with connect(folder) as conn:
            results = []
            for item in conn.execute("SELECT * FROM occurrences WHERE local_date BETWEEN ? AND ? ORDER BY local_date,id",
                                     (first.isoformat(), last.isoformat())):
                row = json.loads(item["payload"])
                row.update(id=item["id"], first_seen=item["first_seen"], last_checked=item["last_seen"],
                           changed_at=item["changed_at"], missing_since=item["missing_since"])
                results.append(row)
            return results
    except (OSError, sqlite3.Error, ValueError):
        return []


def source_status(*, now: datetime | None = None, folder=None) -> list[dict]:
    now = now or datetime.now(UTC)
    try:
        with connect(folder) as conn:
            saved = {row["source_id"]: dict(row) for row in conn.execute("SELECT * FROM sources")}
    except (OSError, sqlite3.Error):
        saved = {}
    result = []
    for key, source in SOURCES.items():
        row = saved.get(key, {"source_id": key, "state": "not_collected", "item_count": 0})
        row.update(name=source["name"], url=source["url"])
        checked = row.get("last_success")
        age = (now - datetime.fromisoformat(checked)).total_seconds() / 60 if checked else None
        row["age_minutes"] = round(max(age, 0), 1) if age is not None else None
        if row["state"] == "ready" and (age is None or age > 36 * 60):
            row["state"] = "stale"
        result.append(row)
    return result


def merged_events(first: date, last: date, *, now=None, folder=None) -> list[dict]:
    """Merge exact event identities across sources, retaining their disagreements."""
    now = now or datetime.now(UTC)
    sources = {s["source_id"]: s for s in source_status(now=now, folder=folder)}
    candidates = records(first, last, folder=folder)
    # Current organizer evidence wins over an aggregator, but a disappeared listing
    # must not displace a current source that explicitly verifies the event.
    candidates.sort(key=lambda row: (not bool(row["missing_since"]),
                    (now - datetime.fromisoformat(row["last_checked"])).total_seconds() <= 36 * 3600,
                    SOURCES[row["source_id"]]["rank"], row["last_checked"]), reverse=True)
    groups: dict[tuple, list[dict]] = {}
    for row in candidates:
        key = (row["city"], slug(row["title"]), row.get("venue_key") or slug(row["venue"]), row["local_date"])
        buckets = groups.setdefault(key, [])
        # Two performances from one source remain two occurrences.
        target = next((item for item in buckets if row["source_id"] not in
                       {receipt["source_id"] for receipt in item["receipts"]}), None)
        receipt = {"source_id": row["source_id"], "name": SOURCES[row["source_id"]]["name"],
                   "url": row["source_url"], "checked_at": row["last_checked"],
                   "starts_at": row.get("starts_at"), "ends_at": row.get("ends_at"),
                   "status": row["status"], "missing_since": row["missing_since"],
                   "source_state": sources[row["source_id"]]["state"]}
        if target is None:
            target = dict(row, receipts=[receipt], conflicts=list(row.get("schedule_warnings", [])))
            buckets.append(target)
        else:
            target["receipts"].append(receipt)
            target["conflicts"].extend(row.get("schedule_warnings", []))
            for field in ("starts_at", "ends_at", "status"):
                if row.get(field) and target.get(field) and row[field] != target[field]:
                    target["conflicts"].append(f"Sources disagree on {field.replace('_', ' ')}")
            # A secondary source may add hours; record the source of those hours.
            if (not target.get("starts_at") and row.get("starts_at") and not row["missing_since"]
                    and sources[row["source_id"]]["state"] == "ready"
                    and (now - datetime.fromisoformat(row["last_checked"])).total_seconds() <= 36 * 3600):
                target.update(starts_at=row["starts_at"], ends_at=row.get("ends_at"),
                              timing_basis=row.get("timing_basis"), timing_source=row["source_url"])
    output = []
    for buckets in groups.values():
        for row in buckets:
            row["conflicts"] = sorted(set(row["conflicts"]))
            checked = datetime.fromisoformat(row["last_checked"])
            state = sources[row["source_id"]]["state"]
            row["freshness"] = ("not seen on latest check" if row["missing_since"] else
                                "source refresh failed" if state in {"error", "partial"} else
                                "old source data" if (now - checked).total_seconds() > 36 * 3600 else
                                "recently checked")
            row["attendance"] = None
            row["ride_demand"] = "unknown"
            output.append(row)
    return sorted(output, key=lambda row: (row["local_date"], row.get("starts_at") or "", row["title"]))


def catalog(*, now=None, days=14, folder=None) -> dict:
    if not 1 <= days <= 30:
        raise ValueError("Choose 1 to 30 days")
    now = (now or datetime.now(PACIFIC)).astimezone(PACIFIC)
    first, last = now.date(), now.date() + timedelta(days=days - 1)
    events = merged_events(first, last, now=now, folder=folder)
    return {"as_of": now.isoformat(), "timezone": "America/Los_Angeles", "city": "Seattle and Redmond",
            "cities": list(CITY_BOUNDS),
            "from_date": first.isoformat(), "through_date": last.isoformat(),
            "sources": source_status(now=now, folder=folder), "events": events,
            "scheduled_count": sum(row["status"] == "scheduled" for row in events),
            "note": "Published schedules; attendance and ride demand are unknown."}


def event_signals(start: datetime, end: datetime, *, now=None, folder=None) -> list[Signal]:
    now = now or datetime.now(UTC)
    result = []
    allowed = load_zones().by_id
    for row in merged_events(start.astimezone(PACIFIC).date(), end.astimezone(PACIFIC).date(), now=now, folder=folder):
        if row["status"] != "scheduled":
            continue
        day = date.fromisoformat(row["local_date"])
        begins = datetime.fromisoformat(row["starts_at"]) if row.get("starts_at") else datetime.combine(day, time(), PACIFIC)
        ends = datetime.fromisoformat(row["ends_at"]) if row.get("ends_at") else datetime.combine(day + timedelta(days=1), time(), PACIFIC)
        if ends <= start or begins >= end:
            continue
        zone = row.get("zone")
        # Metro can display an unresolved Seattle venue; do not assign it a made-up
        # pickup area. Scoring excludes every context-only catalog signal.
        if zone not in allowed:
            zone = "all"
        notes = ["Scheduled community event; attendance and ride demand unknown."]
        if not row.get("starts_at") or not row.get("ends_at"):
            notes.append("Daily hours are not fully published; this is not a midnight closing time.")
        notes.extend(row["conflicts"])
        if row.get("notes"):
            notes.append(row["notes"])
        details = {"title": row["title"], "venue": row["venue"], "venue_id": row.get("venue_key"),
                   "url": row["source_url"], "source_urls": row["receipts"], "category": row["category"],
                   "notes": " ".join(notes), "context_only": True, "community_event": True,
                   "timing_basis": row.get("timing_basis"), "date_only": not row.get("starts_at"),
                   "end_unknown": not row.get("ends_at"), "local_date": row["local_date"],
                   "freshness": row["freshness"], "conflicts": row["conflicts"],
                   "location_label": row.get("neighborhood") or row["venue"] or row["city"] + " · venue unconfirmed",
                   "location_precision": row.get("location_precision", "unknown"),
                   "position": {"lat": row["lat"], "lon": row["lon"]} if row.get("lat") is not None else None,
                   "attendance_basis": "unknown"}
        result.append(Signal("community-" + row["id"], "special_event", zone, begins.isoformat(),
                             ends.isoformat(), 0, "scheduled", "community:" + row["source_id"],
                             row["last_checked"], ends.isoformat(), .7, details))
    return result
