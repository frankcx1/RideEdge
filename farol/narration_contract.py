"""Deterministic temporal/evidence contract shared by narrators and evaluators.

Models may explain a decision. Clock times, venue-window associations, route
status, and risk statements must use the provided complete sentences. Rejecting
a valid paraphrase is preferable to accepting a wrong venue/time association.
"""

from __future__ import annotations

import re
from datetime import datetime


def duration_text(value: str) -> str:
    """Legacy timedelta strings in captures are durations, never clock times."""
    def minutes(match: re.Match) -> str:
        amount = int(match[1]) * 60 + int(match[2]) + int(match[3]) / 60
        return f"{amount:g} minutes"
    return re.sub(r"\b(\d+):(\d{2}):(\d{2})\b", minutes, str(value))


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _clock(value: datetime) -> str:
    return f"{value.hour % 12 or 12}:{value.minute:02d} {'am' if value.hour < 12 else 'pm'}"


def _label(item: dict) -> str:
    return str(item.get("venue_name") or item["zone"].replace("_", " "))


def window_sentence(item: dict) -> str:
    start, end = _time(item["starts_at"]), _time(item["ends_at"])
    day = start.strftime("%b %d")
    end_day = "" if start.date() == end.date() else end.strftime("%b %d ")
    return f"{_label(item)}: estimated pickup window {day} {_clock(start)} to {end_day}{_clock(end)}."


def route_sentence(item: dict) -> str:
    route = item.get("route") or {}
    label = _label(item)
    minutes = route.get("traffic_minutes")
    if not isinstance(minutes, (int, float)):
        return f"{label}: travel time and current traffic are unknown."
    if route.get("basis") == "live":
        return f"{label}: captured traffic-aware route is {minutes:g} minutes."
    return f"{label}: travel time is estimated at {minutes:g} minutes; current traffic is unknown."


def _best(brief: dict) -> dict | None:
    by_id = {item["id"]: item for item in brief.get("opportunities", [])}
    decision = brief.get("shift_decision") or {}
    if decision.get("action") == "NO CLEAR SIGNAL":
        return None
    for ident in brief.get("ranked_opportunity_ids", []):
        item = by_id.get(ident)
        if item and item.get("action") != "AVOID":
            return item
    return None


def contract(brief: dict) -> dict:
    items = brief.get("opportunities") or []
    best = _best(brief)
    errors = [feed["adapter"] for feed in brief.get("feeds", []) if feed.get("mode") == "error"]
    risks = [
        "Ride requests, competing drivers, and hourly earnings are unknown.",
        "Venue exit times and attendance are estimates.",
        "Corridor advisories are not matched to this specific route.",
        "Advisory reports are unverified; check access before repositioning.",
    ]
    required = []
    if not any(item.get("navigation_available") for item in items):
        required.append("No pickup curb is approved; navigation is disabled.")
    if errors:
        required.append("Feeds unavailable: " + ", ".join(errors) + ".")
    if best and (best.get("route") or {}).get("basis") != "live":
        required.append(route_sentence(best))
    if best and best["zone"] == "sea_airport":
        required.append("The Uber airport queue and waiting time are unknown.")
    if items and all(item.get("audit", {}).get("missed_window") for item in items):
        required.append("All candidate windows are expired or unreachable before they end; do not chase them.")
    if any(fact.get("kind") == "transit_disruption" for item in items for fact in item.get("facts", [])):
        risks.append("The transit feed reports service disruptions; check its notice for affected stations.")
    risks = list(dict.fromkeys([*required, *risks]))
    if best:
        spoken = window_sentence(best) + " " + route_sentence(best)
        if best["zone"] == "sea_airport":
            spoken += " The Uber airport queue and waiting time are unknown."
    elif errors and not items:
        spoken = "No clear signal. Feeds are unavailable; missing data does not establish whether driving would pay."
    elif items and all(item.get("audit", {}).get("missed_window") for item in items):
        spoken = "No clear signal. All candidate windows are expired or unreachable before they end. Avoid chasing them."
    else:
        spoken = "No clear reachable signal. Review the available evidence; hourly earnings remain unknown."
    # Long venue labels must not defeat the spoken limit. Full details stay in notes.
    if len(spoken.split()) > 45:
        spoken = (brief.get("shift_decision") or {}).get("explanation") or "Review the available evidence."
    return {
        "version": "checked-claims-v1",
        "instructions": (
            "Copy window and route sentences verbatim, one venue at a time. Never combine different "
            "venues into one clock range. Do not invent show start times. Select risks verbatim from "
            "allowed_risks and include required_risks. Free wording must not add clocks or route-status claims."
        ),
        "opportunities": {item["id"]: {"window": window_sentence(item), "route": route_sentence(item)}
                          for item in items},
        "allowed_risks": risks, "required_risks": required, "fallback_spoken": spoken,
    }


_CLOCK = re.compile(
    r"\b\d{1,2}:\d{2}\b|\b(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    r"\s*[ap]\.?m\.?\b|\bmidnight\b|\bnoon\b", re.IGNORECASE,
)
_START = re.compile(r"\b(?:show|concert|event)\s+(?:starts?|begins?|starting|began)\b", re.IGNORECASE)
_ROUTE_STATUS = re.compile(
    r"\b(?:traffic|travel times?|drive times?|route)\b[^.!?\n]{0,85}"
    r"\b(?:unknown|unavailable|known|live|estimated|estimates|assumed|clear|heavy|free.flow|minutes?|mins?)\b|"
    r"\b(?:live|estimated|assumed|unknown)\b[^.!?\n]{0,35}\b(?:traffic|travel|route)\b|"
    r"\b\d+(?:\.\d+)?\s*(?:minutes?|mins?|miles?)\s+(?:drive|away|reposition)\b",
    re.IGNORECASE,
)


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def text_issues(brief: dict, text: str, *, opportunity_id: str | None = None) -> list[str]:
    """Known sensitive claims fail closed unless an exact scoped sentence matches."""
    catalog = contract(brief)
    items = catalog["opportunities"]
    selected = [items[opportunity_id]] if opportunity_id in items else list(items.values())
    remaining = _normalized(text)
    for row in selected:
        for sentence in row.values():
            remaining = remaining.replace(_normalized(sentence), " ")
    # The contract's generic cautions are valid evidence statements too.
    for sentence in catalog["allowed_risks"]:
        if opportunity_id is None or sentence not in {row["route"] for row in items.values()}:
            remaining = remaining.replace(_normalized(sentence), " ")
    issues = []
    if _CLOCK.search(remaining) or _START.search(remaining):
        issues.append("clock/venue claim is not a checked sentence for this opportunity")
    if _ROUTE_STATUS.search(remaining):
        issues.append("route/evidence claim is not a checked sentence for this opportunity")
    return issues


def narration_issues(brief: dict, narration: dict) -> dict[str, list[str]]:
    issues = {}
    for field in ("headline", "spoken", "shift_rationale", "now_move"):
        found = text_issues(brief, str(narration.get(field) or ""))
        if found:
            issues[field] = found
    for ident, note in (narration.get("opportunity_notes") or {}).items():
        found = text_issues(brief, str(note), opportunity_id=ident)
        if found:
            issues[f"opportunity_notes.{ident}"] = found
    catalog = contract(brief)
    allowed = {_normalized(row) for row in catalog["allowed_risks"]}
    for index, risk in enumerate(narration.get("risks") or []):
        if _normalized(str(risk)) not in allowed:
            issues[f"risks.{index}"] = ["risk is not a checked catalog statement"]
    supplied = {_normalized(str(row)) for row in narration.get("risks") or []}
    missing = [row for row in catalog["required_risks"] if _normalized(row) not in supplied]
    if missing:
        issues["required_risks"] = missing
    return issues
