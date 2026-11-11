"""Shared plumbing for live signal adapters.

Every adapter is cached, independently fallible, and source-timestamped.
A network failure serves the stale cache when one exists and otherwise
degrades to an error status; it never takes down the brief.
"""

import copy
import json
import os
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from farol.dashboard import ROOT
from farol.usage import record as record_usage

DEFAULT_TIMEOUT_SECONDS = 10


class FeedError(RuntimeError):
    """A feed could not produce a payload, even from cache."""


@dataclass(frozen=True)
class FeedStatus:
    adapter: str
    mode: str  # fixture | live | cache | stale_cache | static | needs_key | warming | error
    source: str
    fetched_at: str | None
    signal_count: int
    detail: str = ""

    def public(self) -> dict:
        return asdict(self)


def http_user_agent() -> str:
    # NWS asks for an identifying agent; keep it generic and override via env.
    return os.getenv("FAROL_HTTP_USER_AGENT", "farol/0.1 (local driving copilot)")


def cache_dir() -> Path:
    override = os.getenv("FAROL_CACHE_DIR")
    return Path(override) if override else ROOT / ".cache" / "feeds"


def read_cache(cache_key: str) -> dict | None:
    cache_path = cache_dir() / f"{cache_key}.json"
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def write_cache(cache_key: str, payload: dict | list, *, url: str = "") -> str:
    from farol.evidence import redact_url

    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC).isoformat()
    (directory / f"{cache_key}.json").write_text(
        json.dumps({"fetched_at": fetched_at, "url": redact_url(url), "payload": payload}),
        encoding="utf-8",
    )
    return fetched_at


class MemoryCache:
    """Bounded transient cache. Expired sensitive entries never become disk fallback."""

    def __init__(self, ttl_seconds: float, capacity: int = 64):
        self.ttl_seconds = ttl_seconds
        self.capacity = capacity
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def _expire(self):
        now = time.monotonic()
        for key, (deadline, _) in list(self._entries.items()):
            if deadline <= now:
                del self._entries[key]

    def read(self, key: str) -> dict | None:
        with self._lock:
            self._expire()
            entry = self._entries.get(key)
            return copy.deepcopy(entry[1]) if entry else None

    def write(self, key: str, payload: dict | list, *, url: str = "") -> str:
        del url  # Private request URLs are not retained, even in the cache envelope.
        fetched_at = datetime.now(UTC).isoformat()
        with self._lock:
            self._expire()
            self._entries[key] = (time.monotonic() + self.ttl_seconds,
                                  {"fetched_at": fetched_at, "payload": copy.deepcopy(payload)})
            self._entries.move_to_end(key)
            while len(self._entries) > self.capacity:
                self._entries.popitem(last=False)
        return fetched_at

    def clear(self):
        with self._lock:
            self._entries.clear()

    def expire(self):
        with self._lock:
            self._expire()


def fetch_json(
    url: str,
    *,
    cache_key: str,
    ttl_seconds: float,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    method: str = "GET",
    body: dict | None = None,
    memory_cache: MemoryCache | None = None,
) -> tuple[dict | list, str, str]:
    """Return (payload, mode, fetched_at) with cache-first, stale-fallback semantics."""
    cached = memory_cache.read(cache_key) if memory_cache is not None else read_cache(cache_key)
    if cached is not None:
        age = (datetime.now(UTC) - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
        if age < ttl_seconds:
            record_usage(url, "cache_hits")
            return cached["payload"], "cache", cached["fetched_at"]
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "User-Agent": http_user_agent(),
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
            **(headers or {}),
        },
    )
    try:
        record_usage(url, "http_attempts")
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        record_usage(url, "http_failures")
        if cached is not None:
            return cached["payload"], "stale_cache", cached["fetched_at"]
        raise FeedError(f"{cache_key}: {error}") from error
    writer = memory_cache.write if memory_cache is not None else write_cache
    fetched_at = writer(cache_key, payload, url=url)
    return payload, "live", fetched_at
