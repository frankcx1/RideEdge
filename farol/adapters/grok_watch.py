"""Grok 4.6 watch-bot: public driver intel and Eastside demand pages.

Does not log into Uber, copy cookies, or hit drivers.uber.com private APIs.
Sources are union reports, L&I rate cards, city calendars, Gridwise *public*
writeups, and public forum posts. Anecdote $/hr is tagged assumed.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime

from farol.adapters.base import FeedError, FeedStatus, read_cache
from farol.grok import api_key, complete, extract_json_object, extract_text, model, reasoning_effort
from farol.service_lifecycle import WorkThread
from farol.signals import Signal
from farol.zones import canonical_zone, load_zones

NAME = "grok_watch"
SOURCE = "xai:grok-4.6 watch-bot"
WATCHLIST = [
    "https://www.driversunionwa.org/",
    "https://lni.wa.gov/workers-rights/industry-specific-requirements/transportation-network-company-drivers-rights/getting-paid",
    "https://www.uber.com/us/en/blog/washington-state-tnc-notice-of-rights/",
    "https://gridwise.io/analytics/2026-annual-gig-mobility-report",
    "https://www.seattletimes.com/",
    "https://www.reddit.com/r/uberdrivers/search/?q=Seattle%20OR%20Kirkland%20OR%20Bellevue%20OR%20Redmond%20OR%20SeaTac&restrict_sr=1&sort=new",
    "https://www.portseattle.org/",
    "https://www.marymoorlive.com/",
    "https://bellevuewa.gov/",
    "https://www.kirklandwa.gov/",
    "https://www.redmond.gov/",
    "https://www.thelimekirkland.com/",
]

SYSTEM_PROMPT = """You are Farol's watch-bot for a Kirkland-based Uber driver.

Search the live web and X. Return ONLY JSON:
{"notes":[{"id":"...","kind":"driver_intel|rate_card|supply|event_exit|special_event|airport_arrivals","zone":"optional zone id or all","starts_at":"ISO if timed else omit","ends_at":"ISO if timed else omit","title":"...","summary":"one sentence of what the SOURCE said","source_url":"https://...","evidence_quality":0.2-0.8}]}

Watch for:
- Drivers Union WA / FairFare / deadhead / saturation reports
- Washington and Seattle TNC minimum pay rate-card changes
- Gridwise *public* reports (not a login)
- r/uberdrivers posts about Seattle, Eastside, Kirkland, Bellevue, Redmond, SEA
- Marymoor, Woodinville, Bellevue downtown, Kirkland waterfront, SEA arrivals
- WSDOT 520 / I-405 / I-90 incidents only as event context

Rules:
- Prefer cited public pages over vibes.
- Do NOT scrape or log into drivers.uber.com or copy anyone's cookies.
- Do NOT invent a neighborhood $/hr or treat one Reddit screenshot as a forecast.
- Do NOT output GPS, names, or trip history.
- If an anecdote includes a dollar figure, put it in summary as a quote and keep evidence_quality <= 0.35.
- Omit notes you cannot ground in a URL.
- Traffic incidents and road closures are driver_intel, never event_exit or demand.
- These notes are advisory context; authoritative adapters own scored demand windows.
"""


def _cache_key(window_start: datetime, window_end: datetime) -> str:
    del window_end
    from farol.grok import cache_bucket

    return f"grok_watch_{cache_bucket(window_start)}"


def parse(payload: dict, window_start: datetime, window_end: datetime, *, fetched_at: str) -> list[Signal]:
    blob = extract_json_object(extract_text(payload))
    allowed = {zone.id for zone in load_zones().zones} | {"all"}
    signals: list[Signal] = []
    for index, note in enumerate(blob.get("notes") or []):
        if not isinstance(note, dict):
            continue
        kind = str(note.get("kind") or "driver_intel")
        if kind not in {
            "driver_intel",
            "rate_card",
            "supply",
            "event_exit",
            "special_event",
            "airport_arrivals",
            "closing_wave",
        }:
            kind = "driver_intel"
        zone = canonical_zone(str(note.get("zone") or "all"))
        if zone not in allowed:
            zone = "all"
        from farol.evidence import parse_time

        raw_start, raw_end = note.get("starts_at"), note.get("ends_at")
        if raw_start:
            starts_dt = parse_time(raw_start)
            if starts_dt is None:
                continue
        else:
            starts_dt = window_start
        if raw_end:
            ends_dt = parse_time(raw_end)
            if ends_dt is None:
                continue
        else:
            ends_dt = window_end
        if ends_dt < starts_dt:
            continue
        starts = starts_dt.isoformat()
        ends = ends_dt.isoformat()
        try:
            quality = float(note.get("evidence_quality") or 0.4)
        except (TypeError, ValueError):
            quality = 0.4
        quality = min(quality, 0.45)
        title = str(note.get("title") or kind.replace("_", " "))
        summary = str(note.get("summary") or "")
        source = str(note.get("source_url") or SOURCE)
        slug = str(note.get("id") or f"{kind}-{index}")
        signals.append(
            Signal(
                id=f"watch-{slug}",
                # Watch notes contain no calibrated magnitude and can misclassify
                # a road closure as an event exit. Keep all notes as context;
                # they must not create scored opportunities or stadium penalties.
                kind="driver_intel",
                zone=zone,
                starts_at=starts,
                ends_at=ends,
                magnitude=0,
                basis="assumed",
                source=source,
                fetched_at=fetched_at,
                expires_at=ends,
                evidence_quality=max(0.2, min(0.8, quality)),
                details={"title": title, "notes": summary, "watchlist": True,
                         "reported_kind": kind, "scoring_role": "advisory_only"},
            )
        )
    return signals


_refresh_lock = threading.Lock()
_refreshing: set[str] = set()


def _watch_user(window_start: datetime, window_end: datetime) -> str:
    return json.dumps(
        {
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "watchlist": WATCHLIST,
            "allowed_zones": [zone.id for zone in load_zones().zones],
        }
    )


def _call_watch(window_start: datetime, window_end: datetime, cache_key: str):
    return complete(
        system=SYSTEM_PROMPT,
        user=_watch_user(window_start, window_end),
        cache_key=cache_key,
        prompt_cache_key="farol-watch-bot",
        tools=[{"type": "web_search"}, {"type": "x_search"}],
        reasoning=reasoning_effort("research"),
    )


def _kick_watch(window_start: datetime, window_end: datetime, cache_key: str) -> None:
    with _refresh_lock:
        if cache_key in _refreshing:
            return
        _refreshing.add(cache_key)

    def run() -> None:
        try:
            _call_watch(window_start, window_end, cache_key)
        except (FeedError, ValueError, TypeError, json.JSONDecodeError):
            pass
        finally:
            with _refresh_lock:
                _refreshing.discard(cache_key)

    WorkThread(target=run, name="farol-grok-watch", daemon=True).start()


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    from farol.grok import brain_name

    if brain_name() != "grok":
        return [], FeedStatus(NAME, "disabled", SOURCE, None, 0,
                              "Cloud watch disabled; Qwen interprets connected feed evidence")
    if not api_key():
        return [], FeedStatus(
            NAME,
            "needs_key",
            "env:XAI_API_KEY",
            None,
            0,
            "watch-bot idle until XAI_API_KEY is set",
        )
    cache_key = _cache_key(window_start, window_end)
    cached = read_cache(cache_key)
    if cached is not None:
        try:
            signals = parse(
                cached["payload"], window_start, window_end, fetched_at=cached["fetched_at"]
            )
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return [], FeedStatus(NAME, "error", SOURCE, cached.get("fetched_at"), 0, str(error))
        return signals, FeedStatus(
            NAME,
            "cache",
            SOURCE,
            cached.get("fetched_at"),
            len(signals),
            f"{model()} · public driver intel + Eastside pages, no Uber login",
        )
    if os.getenv("FAROL_GROK_BLOCK", "") == "1":
        try:
            payload, mode, fetched_at = _call_watch(window_start, window_end, cache_key)
            signals = parse(payload, window_start, window_end, fetched_at=fetched_at)
        except FeedError as error:
            return [], FeedStatus(NAME, "error", SOURCE, None, 0, str(error))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return [], FeedStatus(NAME, "error", SOURCE, None, 0, str(error))
        return signals, FeedStatus(
            NAME,
            mode,
            SOURCE,
            fetched_at,
            len(signals),
            f"{model()} · public driver intel + Eastside pages, no Uber login",
        )
    _kick_watch(window_start, window_end, cache_key)
    return [], FeedStatus(
        NAME,
        "warming",
        SOURCE,
        None,
        0,
        f"{model()} watch-bot started; next brief refresh will include results",
    )
