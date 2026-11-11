"""Grok 4.6 research adapter: public Eastside demand intel via live web/X search.

The model does not score, forecast dollars, or see trip history. It only
returns tagged world-state signals. SuperGrok consumer access is not an API
key — set XAI_API_KEY from https://console.x.ai.

Live search is required: grok-4.6's knowledge cutoff is 2026-02-01.
Cold cache does not block the brief; a background refresh fills the next poll.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta

from farol.adapters.base import FeedError, FeedStatus, fetch_json, read_cache, write_cache
from farol.evidence import http_source
from farol.grok import API_URL, extract_json_object, extract_text
from farol.grok import model as grok_model
from farol.service_lifecycle import WorkThread
from farol.signals import Signal
from farol.zones import canonical_zone, load_zones

NAME = "grok_research"
SOURCE = "xai:grok-4.6 web_search+x_search"
KNOWN_KINDS = {
    "event_exit",
    "special_event",
    "closing_wave",
    "cruise_disembark",
    "airport_arrivals",
}
_refresh_lock = threading.Lock()
_refreshing: set[str] = set()

SYSTEM_PROMPT = """You are Farol's public-world researcher for a Kirkland-based Uber driver.

Return ONLY a JSON object of the form {"signals":[...]}. No markdown, no advice.

Each signal:
- id: stable slug
- kind: event_exit | special_event | closing_wave | cruise_disembark | airport_arrivals
- zone: one of the allowed zone ids
- starts_at / ends_at: ISO-8601 with offset
- magnitude: sourced attendance/headcount if the page states one, else 0
- basis: scheduled (calendar/start time posted), live (current conditions), assumed (you inferred timing)
- source_url: the page you used
- evidence_quality: 0.2-0.9
- title: short human title
- notes: one line of what the source actually said

Rules:
- Search the live web (and X for current crowd/traffic chatter) for the given window.
- Cover Kirkland, Bellevue, Redmond, Woodinville, Cottage Lake, Marymoor Park, SEA airport, plus Seattle venues that send riders back to the Eastside.
- Check city calendars, Marymoor Live, Chateau Ste. Michelle, Climate Pledge, Lumen Field, T-Mobile Park, Port of Seattle, Ticketmaster/Live Nation Seattle, 206.events, WSDOT 520/I-405 incidents only as event context.
- A sibling watch-bot handles Drivers Union / L&I rate cards / public Gridwise / r/uberdrivers. You may still note a sourced event.
- Omit anything you cannot ground in a fetched page or post.
- NEVER output money, $/hr, ride probability, surge, EV, or where the driver should go.
- NEVER request or use GPS, names, trip history, or earnings.
- Prefer fewer verified signals over a long guessed list.
"""


def _model() -> str:
    return grok_model()


def _ttl() -> float:
    from farol.grok import ttl_seconds

    return ttl_seconds()


def _timeout() -> float:
    from farol.grok import timeout_seconds

    return timeout_seconds()


def _cache_key(window_start: datetime, window_end: datetime) -> str:
    del window_end
    from farol.grok import cache_bucket

    return f"grok_{cache_bucket(window_start)}"


def parse(
    payload: dict, window_start: datetime, window_end: datetime, *, fetched_at: str
) -> list[Signal]:
    blob = extract_json_object(extract_text(payload))
    allowed = {zone.id for zone in load_zones().zones}
    signals: list[Signal] = []
    for index, item in enumerate(blob.get("signals") or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if kind not in KNOWN_KINDS:
            continue
        try:
            starts = datetime.fromisoformat(str(item["starts_at"]))
            ends = datetime.fromisoformat(str(item["ends_at"]))
        except (KeyError, TypeError, ValueError):
            continue
        if starts.tzinfo is None:
            starts = starts.replace(tzinfo=window_start.tzinfo)
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=window_start.tzinfo)
        if ends < window_start or starts > window_end:
            continue
        zone = canonical_zone(str(item.get("zone") or ""))
        if zone not in allowed:
            continue
        try:
            magnitude = max(0.0, float(item.get("magnitude") or 0))
        except (TypeError, ValueError):
            magnitude = 0.0
        try:
            quality = float(item.get("evidence_quality") or 0.45)
        except (TypeError, ValueError):
            quality = 0.45
        source_url = str(item.get("source_url") or item.get("source") or "")
        if not http_source(source_url):
            continue
        basis = item.get("basis") if item.get("basis") in {"scheduled", "live", "assumed"} else "scheduled"
        title = str(item.get("title") or kind.replace("_", " "))
        signal_id = re.sub(r"[^a-z0-9]+", "-", str(item.get("id") or f"{zone}-{index}").lower()).strip("-")
        signals.append(
            Signal(
                id=f"grok-{signal_id}",
                kind=kind,
                zone=zone,
                starts_at=starts.isoformat(),
                ends_at=ends.isoformat(),
                magnitude=magnitude,
                basis=basis,
                source=source_url,
                fetched_at=fetched_at,
                expires_at=(starts + timedelta(hours=8)).isoformat(),
                evidence_quality=max(0.2, min(0.9, quality)),
                details={
                    "title": title,
                    "notes": str(item.get("notes") or ""),
                    "researcher": _model(),
                },
            )
        )
    return signals


def _request_body(window_start: datetime, window_end: datetime) -> dict:
    zones = ", ".join(zone.id for zone in load_zones().zones)
    user = (
        f"Window start: {window_start.isoformat()}\n"
        f"Window end: {window_end.isoformat()}\n"
        f"Allowed zones: {zones}\n"
        "Find verified events, venue let-outs, fairs, concerts, bar-district closings, "
        "and SEA arrival banks that overlap this window."
    )
    return {
        "model": _model(),
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "tools": [{"type": "web_search"}, {"type": "x_search"}],
        "reasoning": {"effort": os.getenv("FAROL_GROK_REASONING", "low")},
        "prompt_cache_key": "farol-eastside-research",
    }


def _call_grok(window_start: datetime, window_end: datetime) -> tuple[dict, str, str]:
    from farol.grok import require_cloud_enabled

    require_cloud_enabled()
    key = os.getenv("XAI_API_KEY", "")
    cache_key = _cache_key(window_start, window_end)
    return fetch_json(
        API_URL,
        cache_key=cache_key,
        ttl_seconds=_ttl(),
        timeout=_timeout(),
        method="POST",
        body=_request_body(window_start, window_end),
        headers={"Authorization": f"Bearer {key}"},
    )


def _background_refresh(window_start: datetime, window_end: datetime, cache_key: str) -> None:
    try:
        payload, mode, fetched_at = _call_grok(window_start, window_end)
        if mode == "live":
            write_cache(cache_key, payload, url=API_URL)
            _ = fetched_at
    except FeedError:
        pass
    finally:
        with _refresh_lock:
            _refreshing.discard(cache_key)


def fetch(window_start: datetime, window_end: datetime) -> tuple[list[Signal], FeedStatus]:
    from farol.grok import brain_name

    if brain_name() != "grok":
        return [], FeedStatus(NAME, "disabled", SOURCE, None, 0,
                              "Cloud web/X discovery disabled; using connected data APIs")
    if not os.getenv("XAI_API_KEY"):
        return [], FeedStatus(
            NAME,
            "needs_key",
            "env:XAI_API_KEY",
            None,
            0,
            "set XAI_API_KEY from https://console.x.ai — SuperGrok app login is not an API key",
        )
    cache_key = _cache_key(window_start, window_end)
    cached = read_cache(cache_key)
    ttl = _ttl()
    if cached is not None:
        age = (datetime.now().astimezone() - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
        mode = "cache" if age < ttl else "stale_cache"
        try:
            signals = parse(
                cached["payload"], window_start, window_end, fetched_at=cached["fetched_at"]
            )
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            signals = []
            mode = "error"
            return [], FeedStatus(NAME, mode, SOURCE, cached.get("fetched_at"), 0, str(error))
        if age >= ttl:
            _kick_refresh(window_start, window_end, cache_key)
        return signals, FeedStatus(
            NAME,
            mode,
            SOURCE,
            cached.get("fetched_at"),
            len(signals),
            f"{_model()} · ttl {int(ttl)}s · web+X search",
        )
    if os.getenv("FAROL_GROK_BLOCK", "") == "1":
        try:
            payload, mode, fetched_at = _call_grok(window_start, window_end)
        except FeedError as error:
            return [], FeedStatus(NAME, "error", SOURCE, None, 0, str(error))
        try:
            signals = parse(payload, window_start, window_end, fetched_at=fetched_at)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return [], FeedStatus(NAME, "error", SOURCE, fetched_at, 0, str(error))
        return signals, FeedStatus(
            NAME, mode, SOURCE, fetched_at, len(signals), f"{_model()} · web+X search"
        )
    _kick_refresh(window_start, window_end, cache_key)
    return [], FeedStatus(
        NAME,
        "warming",
        SOURCE,
        None,
        0,
        f"{_model()} research started; next brief refresh will include results",
    )


def _kick_refresh(window_start: datetime, window_end: datetime, cache_key: str) -> None:
    with _refresh_lock:
        if cache_key in _refreshing:
            return
        _refreshing.add(cache_key)
    thread = WorkThread(
        target=_background_refresh,
        args=(window_start, window_end, cache_key),
        name="farol-grok-refresh",
        daemon=True,
    )
    thread.start()
