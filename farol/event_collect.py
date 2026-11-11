"""Scheduled Seattle/Redmond event collection, independent of the API and GPU jobs.

Usage: py -3.11 -m farol.event_collect --days 14
"""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

from farol.community_events import (
    PACIFIC,
    SOURCES,
    atomic_json,
    catalog,
    connect,
    digest,
    directory,
    store_source,
)

USER_AGENT = "RideEdge-Events/1.0 (Seattle community calendar; local personal use)"
ALLOWED_HOSTS = {"visitseattle.org", "www.visitseattle.org", "www.seattlecenter.com", "seattlecenter.com",
                 "seattlefarmersmarkets.org", "www.seattlefarmersmarkets.org", "www.trumba.com",
                 "www.redmond.gov", "redmond.gov", "data.kingcounty.gov"}
MAX_PAGE_BYTES = 3 * 1024 * 1024


def checked_url(url: str) -> str:
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.username
            or parts.password or parts.port not in {None, 443}):
        raise ValueError("Event crawl URL is outside the configured source sites")
    return url


class SourceRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Fetcher:
    def __init__(self, folder: Path, *, budget_seconds=300, max_requests=90):
        self.cache = folder / "http"
        self.deadline = time.monotonic() + budget_seconds
        self.max_requests = max_requests
        self.requests = 0
        self.cache_hits = 0
        self.host_times = {}
        self.robots = {}
        self.opener = build_opener(SourceRedirect())

    def _get(self, url, headers=None):
        checked_url(url)
        if self.requests >= self.max_requests or time.monotonic() >= self.deadline:
            raise RuntimeError("Collection reached its request/time budget")
        host = urlsplit(url).hostname
        robots = self.robots.get(host)
        interval = max(.7, (robots.crawl_delay(USER_AGENT) or 0) if robots else 0)
        pause = interval - (time.monotonic() - self.host_times.get(host, 0))
        if pause > 0:
            time.sleep(pause)
        self.requests += 1
        self.host_times[host] = time.monotonic()
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,text/plain;q=0.8", **(headers or {})})
        try:
            with self.opener.open(request, timeout=20) as response:
                body = response.read(MAX_PAGE_BYTES + 1)
                if len(body) > MAX_PAGE_BYTES:
                    raise ValueError("Event page exceeds download limit")
                return body.decode(response.headers.get_content_charset() or "utf-8", errors="replace"), response.headers
        except HTTPError:
            raise
        except (URLError, TimeoutError) as error:
            raise RuntimeError("Source could not be reached within the timeout") from error

    def __call__(self, url: str) -> str:
        checked_url(url)
        parts = urlsplit(url)
        host = parts.hostname
        if host not in self.robots:
            robots = RobotFileParser()
            try:
                content, _ = self._get(f"https://{host}/robots.txt")
                robots.parse(content.splitlines())
            except HTTPError as error:
                if error.code == 404:
                    robots.parse(["User-agent: *", "Allow: /"])
                elif error.code in {401, 403}:
                    robots.parse(["User-agent: *", "Disallow: /"])
                else:
                    raise
            self.robots[host] = robots
        if not self.robots[host].can_fetch(USER_AGENT, url):
            raise RuntimeError("Source does not allow this page to be crawled")
        path = self.cache / (digest(url) + ".json")
        cached = {}
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        headers = {}
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("modified"):
            headers["If-Modified-Since"] = cached["modified"]
        try:
            body, response_headers = self._get(url, headers)
        except HTTPError as error:
            if error.code == 304 and isinstance(cached.get("body"), str):
                self.cache_hits += 1
                return cached["body"]
            raise RuntimeError(f"Source returned HTTP {error.code}") from error
        atomic_json(path, {"url": url, "body": body, "checked_at": datetime.now(UTC).isoformat(),
                           "etag": response_headers.get("ETag"), "modified": response_headers.get("Last-Modified")})
        return body


@contextmanager
def collection_lock(folder: Path):
    """OS releases this lock on process exit, including scheduler termination."""
    folder.mkdir(parents=True, exist_ok=True)
    handle = (folder / "collector.lock").open("a+b")
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                pass
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                pass
        yield acquired
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def run(*, now=None, days=14, folder=None, fetch=None, only=None) -> dict:
    from farol.event_sources import collect_source

    if not 1 <= days <= 30:
        raise ValueError("Choose 1 to 30 days")
    folder = folder or directory()
    now = (now or datetime.now(PACIFIC)).astimezone(PACIFIC)
    first, last = now.date(), now.date() + timedelta(days=days - 1)
    with collection_lock(folder) as acquired:
        if not acquired:
            return {"state": "already_running", "sources": []}
        run_id = uuid.uuid4().hex
        started = datetime.now(UTC).isoformat()
        with connect(folder, write=True) as conn:
            conn.execute("INSERT INTO runs(id,started_at) VALUES(?,?)", (run_id, started))
        fetch = fetch or Fetcher(folder)
        results = []
        for source_id in (only or SOURCES):
            before = getattr(fetch, "requests", 0)
            try:
                rows, errors = collect_source(source_id, fetch, first, last)
                state = "partial" if errors else "ready"
                detail = "; ".join(errors) if errors else "Published occurrences checked within configured source coverage"
                result = store_source(source_id, rows, now=now, first=first, last=last, state=state,
                                      detail=detail, requests=getattr(fetch, "requests", 0) - before, folder=folder)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
                result = store_source(source_id, [], now=now, first=first, last=last, state="error",
                                      detail=f"{type(error).__name__}: {str(error)[:250]}",
                                      requests=getattr(fetch, "requests", 0) - before, folder=folder)
            results.append(result)
            print(json.dumps(result, ensure_ascii=True), flush=True)
        report = {"run_id": run_id, "state": "ready" if all(r["state"] == "ready" for r in results) else "partial",
                  "started_at": started, "finished_at": datetime.now(UTC).isoformat(),
                  "from_date": first.isoformat(), "through_date": last.isoformat(), "sources": results,
                  "requests": getattr(fetch, "requests", 0), "cache_hits": getattr(fetch, "cache_hits", 0),
                  "model_calls": 0, "delivery": "local RideEdge catalog"}
        with connect(folder, write=True) as conn:
            conn.execute("UPDATE runs SET finished_at=?,report=? WHERE id=?",
                         (report["finished_at"], json.dumps(report), run_id))
        atomic_json(folder / "last_run.json", report)
        view = catalog(now=now, days=days, folder=folder)
        atomic_json(folder / "latest.json", view)
        year, week, _ = now.isocalendar()
        weekly = folder / "weekly" / f"{year}-W{week:02d}.json"
        # First completed run of the week is a dated baseline, not overwritten by
        # subsequent checks. Database revisions retain later changes.
        if not weekly.exists() and all(source["state"] == "ready" for source in view["sources"]):
            atomic_json(weekly, view)
        report["scheduled_count"] = view["scheduled_count"]
        return report


def main():
    from farol.env import load_env

    load_env()
    parser = argparse.ArgumentParser(description="Collect published Seattle and Redmond community events locally")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--store", type=Path)
    parser.add_argument("--source", choices=list(SOURCES), action="append")
    args = parser.parse_args()
    report = run(days=args.days, folder=args.store, only=args.source)
    print(json.dumps(report, ensure_ascii=True), flush=True)
    return 0 if report["state"] in {"ready", "already_running"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
