"""Placeholder statuses for feeds that need API keys or accounts.

Each entry surfaces in the brief's feed list as `needs_key` until the owner
supplies the credential in .env, at which point the real adapter gets built.
"""

import os
from datetime import datetime

from farol.adapters.base import FeedStatus
from farol.signals import Signal

KEYED_FEEDS = []


def statuses(window_start: datetime, window_end: datetime) -> list[FeedStatus]:
    results = []
    for name, env_var, provides in KEYED_FEEDS:
        if os.getenv(env_var):
            detail = f"{env_var} present; live adapter not yet implemented"
        else:
            detail = f"set {env_var} in .env — provides {provides}"
        results.append(FeedStatus(name, "needs_key", f"env:{env_var}", None, 0, detail))
    return results


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], list[FeedStatus]]:
    return [], statuses(window_start, window_end)
