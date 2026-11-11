"""Explicit, expiring BestTime request allowance shared by all local processes.

Missing policy means paused. Attempts are reserved atomically before HTTP; a
timeout may still be billable. Request counts are not provider credit estimates.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path


class BestTimePaused(RuntimeError):
    pass


def _connect():
    path = Path(os.getenv("RIDEEDGE_BESTTIME_CONTROL_FILE") or
                Path(__file__).resolve().parents[1] / ".cache/besttime/network-policy.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY, until REAL, remaining INTEGER)")
    db.execute("INSERT OR IGNORE INTO policy VALUES (1, 0, 0)")
    db.commit()
    return db


def status() -> dict:
    db = _connect()
    try:
        until, remaining = db.execute("SELECT until, remaining FROM policy WHERE id=1").fetchone()
        enabled = time.time() < until and remaining > 0
        return {"enabled": enabled, "state": "enabled" if enabled else "paused",
                "expires_at_epoch": until or None, "requests_remaining": remaining if enabled else 0,
                "detail": "Paid requests allowed within this temporary allowance" if enabled else
                "Paid BestTime requests paused; saved evidence retains its original age"}
    finally:
        db.close()


def configure(minutes: int = 0, requests: int = 0) -> dict:
    if not (minutes == requests == 0 or 1 <= minutes <= 60 and 1 <= requests <= 100):
        raise ValueError("Use 1-60 minutes and 1-100 requests, or pause with both zero")
    db = _connect()
    try:
        with db:
            db.execute("UPDATE policy SET until=?, remaining=? WHERE id=1",
                       (time.time() + minutes * 60 if minutes else 0, requests))
    finally:
        db.close()
    return status()


def reserve_request() -> None:
    db = _connect()
    try:
        with db:
            changed = db.execute("UPDATE policy SET remaining=remaining-1 "
                                 "WHERE id=1 AND until>? AND remaining>0", (time.time(),)).rowcount
            if changed != 1:
                raise BestTimePaused("Paid BestTime requests paused or allowance exhausted")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "pause", "enable"))
    parser.add_argument("--minutes", type=int, default=10)
    parser.add_argument("--requests", type=int, default=12)
    args = parser.parse_args()
    result = (configure(args.minutes, args.requests) if args.action == "enable" else
              configure() if args.action == "pause" else status())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
