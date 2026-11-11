"""Count adapter HTTP attempts once per collector run, without URLs or credentials."""
from contextvars import ContextVar
from urllib.parse import urlsplit

current_run = ContextVar("farol_usage_run", default=None)


def record(url: str, event: str):
    counts = current_run.get()
    if counts is None:
        return
    provider = urlsplit(url).hostname or "unknown"
    row = counts.setdefault(provider, {"http_attempts":0, "cache_hits":0, "http_failures":0})
    row[event] += 1
