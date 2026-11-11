"""Expiring desktop credentials issued only by a local operator, not an HTTP API."""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

BROWSER_TOKEN = re.compile(r"rb_[A-Za-z0-9_-]{43}\Z")
LIFETIME = 12 * 60 * 60


class BrowserAccess:
    def __init__(self, access_path: Path):
        self.path = access_path.with_name("browser-access.sqlite3")

    def issue(self, binding: str, origin: str) -> str:
        if not binding:
            raise ValueError("Configure RideEdge access before opening the dashboard.")
        token = "rb_" + secrets.token_urlsafe(32)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY, binding TEXT, origin TEXT, expires REAL)")
            db.execute("DELETE FROM sessions WHERE expires <= ? OR binding != ?", (time.time(), binding))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                       (hashlib.sha256(token.encode()).hexdigest(), binding, origin, time.time() + LIFETIME))
        return token

    def verify(self, token, binding: str | None, origin: str) -> bool:
        if not binding or not isinstance(token, str) or not BROWSER_TOKEN.fullmatch(token) or not self.path.exists():
            return False
        try:
            with closing(sqlite3.connect(self.path)) as db:
                return db.execute("SELECT 1 FROM sessions WHERE digest = ? AND binding = ? AND origin = ? AND expires > ?",
                                  (hashlib.sha256(token.encode()).hexdigest(), binding, origin, time.time())).fetchone() is not None
        except sqlite3.Error:
            return False


def main():
    # Output is captured by open-studio.ps1 and deliberately never printed there.
    from farol.access import AccessPolicy
    policy = AccessPolicy()
    print(BrowserAccess(policy.path).issue(policy.digest(), policy.origin))


if __name__ == "__main__":
    main()
