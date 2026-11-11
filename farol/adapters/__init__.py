"""Signal feed registry.

MOCK_FEEDS=1 (the default) serves the deterministic fixture pipeline; setting
MOCK_FEEDS=0 activates the live adapters. Every adapter is independently
fallible: one failing feed degrades to an error status without touching the
others, and the brief reports every feed's mode and source timestamp.
"""

import os
from datetime import UTC, datetime, timedelta

from farol.adapters import (
    amtrak_sea,
    community_events,
    cruise,
    eastside,
    espn_seattle,
    flightaware,
    grok_research,
    grok_watch,
    keyed,
    mlb,
    nhl,
    nws,
    onebusaway,
    openclaw,
    places,
    sea_fifo,
    seatgeek,
    seattle_events,
    situational_waves,
    ticketmaster,
    venues,
    weather_live,
    wsdot,
    wsf_ferries,
)
from farol.adapters.base import FeedStatus
from farol.dashboard import FIXTURES
from farol.signals import FixtureSignalAdapter, Signal

ADAPTERS = [
    community_events,
    nws,
    weather_live,
    mlb,
    nhl,
    espn_seattle,
    ticketmaster,
    seatgeek,
    seattle_events,
    sea_fifo,
    flightaware,
    cruise,
    wsf_ferries,
    amtrak_sea,
    eastside,
    situational_waves,
    venues,
    places,
    wsdot,
    onebusaway,
    openclaw,
    grok_research,
    grok_watch,
]
LLM_ADAPTERS = frozenset({"grok_research", "grok_watch"})
# Metered feeds the collector and Tonight Brief must not poll. HERE at SEA
# sets include_on_demand=True and spends one cached AeroAPI page.
ON_DEMAND_ADAPTERS = frozenset({"flightaware_sea"})

DOCTRINE_ZONES = {"sodo_stadiums", "seattle_center"}
DOCTRINE_MAGNITUDE = 18.0


def mock_feeds_active() -> bool:
    return os.getenv("MOCK_FEEDS", "1") == "1"


def _prefer_google_venue_hours(signals: list[Signal]) -> list[Signal]:
    """Drop fixture venue harvests when Places returned hours for the same venue+start."""
    google_keys = {
        (item.details.get("venue_id"), item.starts_at)
        for item in signals
        if item.kind == "closing_wave"
        and item.source.startswith("google:places")
        and item.details.get("venue_id")
    }
    if not google_keys:
        return signals
    kept = []
    for item in signals:
        key = (item.details.get("venue_id"), item.starts_at)
        if item.kind == "closing_wave" and key in google_keys and not item.source.startswith(
            "google:places"
        ):
            continue
        kept.append(item)
    return kept


def is_wamu_exit(signal: Signal) -> bool:
    venue = str(signal.details.get("venue") or "").lower()
    compact = "".join(character for character in venue if character.isalnum())
    return signal.kind == "event_exit" and (
        "wamutheater" in compact or "wamutheatre" in compact
    )


def _doctrine_signals(signals: list[Signal]) -> list[Signal]:
    """Static convergence penalty shadowing every arena/stadium exit wave."""
    stamped = datetime.now(UTC).isoformat()
    doctrine = []
    for signal in signals:
        if signal.kind != "event_exit" or signal.zone not in DOCTRINE_ZONES:
            continue
        # WAMU is an indoor theater in the stadium district. Sharing a zone
        # with Lumen does not make its own exit a stadium-sized crowd. A
        # concurrent stadium event still contributes its district penalty.
        if is_wamu_exit(signal):
            continue
        starts = datetime.fromisoformat(signal.starts_at) - timedelta(minutes=15)
        ends = datetime.fromisoformat(signal.ends_at) + timedelta(minutes=45)
        doctrine.append(
            Signal(
                id=f"doctrine-{signal.id}",
                kind="doctrine_penalty",
                zone=signal.zone,
                starts_at=starts.isoformat(),
                ends_at=ends.isoformat(),
                magnitude=DOCTRINE_MAGNITUDE,
                basis="assumed",
                source="farol:doctrine",
                fetched_at=stamped,
                expires_at=ends.isoformat(),
                evidence_quality=0.45,
                details={
                    "title": "Transit and driver-convergence penalty",
                    "shadowed_signal": signal.id,
                },
            )
        )
    return doctrine


def gather_signals(
    window_start: datetime,
    window_end: datetime,
    *,
    include_llm: bool = True,
    include_on_demand: bool = False,
) -> tuple[list[Signal], list[dict]]:
    if mock_feeds_active():
        signals = FixtureSignalAdapter(FIXTURES / "tonight_signals.json").fetch(
            window_start, window_end
        )
        status = FeedStatus(
            "fixture_signals",
            "fixture",
            "fixtures/tonight_signals.json",
            None,
            len(signals),
            "MOCK_FEEDS=1",
        )
        return signals, [status.public()]
    all_signals: list[Signal] = []
    statuses: list[dict] = []
    for adapter in ADAPTERS:
        name = getattr(adapter, "NAME", "")
        if not include_llm and name in LLM_ADAPTERS:
            continue
        try:
            if name in ON_DEMAND_ADAPTERS:
                signals, status = adapter.fetch(
                    window_start, window_end, demand=include_on_demand
                )
            else:
                signals, status = adapter.fetch(window_start, window_end)
        except Exception as error:  # noqa: BLE001 — a feed must never sink the brief
            signals = []
            status = FeedStatus(
                adapter.NAME, "error", getattr(adapter, "SOURCE", "?"), None, 0, repr(error)
            )
        all_signals.extend(signals)
        statuses.append(status.public())
    from farol.evidence import dedupe_events, sanitize_signals

    all_signals = sanitize_signals(all_signals)
    all_signals = _prefer_google_venue_hours(all_signals)
    all_signals = dedupe_events(all_signals)
    doctrine = _doctrine_signals(all_signals)
    all_signals.extend(doctrine)
    statuses.append(
        FeedStatus(
            "stadium_doctrine",
            "static",
            "farol:doctrine",
            None,
            len(doctrine),
            "convergence penalty shadowing arena/stadium exits",
        ).public()
    )
    statuses.extend(item.public() for item in keyed.statuses(window_start, window_end))
    return all_signals, statuses
