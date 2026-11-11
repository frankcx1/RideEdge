"""Experimental manual Uber Assistant (Beta) intelligence import, parser, and local store.

Design reference: docs/UberTRAC_Uber_Assistant_Intelligence_Design_Reference_v1.md

Core guardrails:
- Deterministic extraction only; no LLM inference or fabricated fields.
- Preserve raw input, per-field provenance, and original values when user-edited.
- Never treat '30+' as exact 30 (store as wait_minutes_lower_bound=30, wait_minutes_exact=None).
- Never infer wait_statistic='p90' from 'etr_p90_min' alone; require explicit percentile language.
- Never convert N/A, 'unavailable', or missing values to 0.
- Treat all pasted text as untrusted content; never execute instructions or open URLs.
- Strictly isolated from production opportunity scoring (recommend.py, here.py, tonight.py, course.py).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from farol.zones import canonical_zone, zone_record

PARSER_VERSION = "1.0.0"

# Feature gates (Section 8)
UBER_ASSISTANT_INTELLIGENCE_EXPERIMENTAL = True
UBER_ASSISTANT_SCORING_INTEGRATION_ENABLED = False

# Configurable plausibility bounds (Section 7)
DEFAULT_MAX_REQUESTS_30M = 5000
DEFAULT_MAX_WAIT_MINUTES = 240.0
DEFAULT_MAX_DRIVE_MINUTES = 180.0
PROMPT_SOFT_CHAR_WARN = 150
PROMPT_SOFT_CHAR_CAP = 200

# Validation flags (Section 7)
FLAG_MISSING_METRIC = "MISSING_METRIC"
FLAG_WAIT_BUCKET_NOT_EXACT = "WAIT_BUCKET_NOT_EXACT"
FLAG_WAIT_STATISTIC_UNKNOWN = "WAIT_STATISTIC_UNKNOWN"
FLAG_UNVERIFIED_BACKEND_FIELD = "UNVERIFIED_BACKEND_FIELD"
FLAG_SOURCE_TIMESTAMP_UNAVAILABLE = "SOURCE_TIMESTAMP_UNAVAILABLE"
FLAG_AREA_BOUNDARY_UNKNOWN = "AREA_BOUNDARY_UNKNOWN"
FLAG_CARD_NARRATIVE_CONFLICT = "CARD_NARRATIVE_CONFLICT"
FLAG_CROSS_SNAPSHOT_CHANGE = "CROSS_SNAPSHOT_CHANGE"
FLAG_OVERLAPPING_ROLLING_WINDOW = "OVERLAPPING_ROLLING_WINDOW"
FLAG_DUPLICATE_IMPORT = "DUPLICATE_IMPORT"
FLAG_OUT_OF_RANGE_VALUE = "OUT_OF_RANGE_VALUE"
FLAG_DRIVE_TIME_CONTEXT_CHANGED = "DRIVE_TIME_CONTEXT_CHANGED"
FLAG_PROMPT_INJECTION_IGNORED = "PROMPT_INJECTION_IGNORED"
FLAG_SUPPORT_FLOW_DETECTED = "SUPPORT_FLOW_DETECTED"
FLAG_SENSITIVE_TEXT_DETECTED = "SENSITIVE_TEXT_DETECTED"
FLAG_AMBIGUOUS_WAIT_VALUES = "AMBIGUOUS_WAIT_VALUES"
FLAG_AMBIGUOUS_REQUEST_VALUES = "AMBIGUOUS_REQUEST_VALUES"
FLAG_NON_30M_REQUEST_WINDOW = "NON_30M_REQUEST_WINDOW"
FLAG_UNPARSEABLE_STORAGE = "UNPARSEABLE_STORAGE"


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    title: str
    purpose: str
    default_text: str


PROMPT_CATALOG: tuple[PromptTemplate, ...] = (
    PromptTemplate(
        id="P1",
        title="P1 — Local demand",
        purpose="Multi-area last-30-min request counts and waits with explicit N/A.",
        default_text=(
            "Bellevue, Redmond, Kirkland, Bothell, Woodinville: last-30-min requests "
            "and driver waits. Use N/A if unavailable."
        ),
    ),
    PromptTemplate(
        id="P2",
        title="P2 — Exact waits",
        purpose="Ask for exact wait minutes and statistic type in Bellevue & Redmond.",
        default_text=(
            "Bellevue and Redmond: exact driver wait minutes and statistic type, if available. "
            "If missing, say N/A."
        ),
    ),
    PromptTemplate(
        id="P3",
        title="P3 — Validate source",
        purpose="Check source update time and whether figures are estimates.",
        default_text=(
            "For Bellevue, give current requests, estimated wait, source update time, "
            "and whether figures are estimates. No guesses."
        ),
    ),
    PromptTemplate(
        id="P4",
        title="P4 — Nearby shortest wait",
        purpose="Top 3 areas with shortest available waits, requests, and drive times.",
        default_text=(
            "Which 3 nearby areas have the shortest available driver waits? Give waits, "
            "recent requests and drive times. Exclude N/A waits."
        ),
    ),
    PromptTemplate(
        id="P5",
        title="P5 — Tonight (qualitative)",
        purpose="Qualitative demand windows, waits, and uncertainty for tonight.",
        default_text=(
            "What nearby areas have the best earning opportunity tonight? Include known "
            "demand windows, waits, and uncertainty."
        ),
    ),
)

KNOWN_AREA_NAMES: tuple[str, ...] = (
    "Totem Lake / Kingsgate",
    "Totem Lake",
    "Kingsgate",
    "Kirkland Waterfront",
    "Kirkland Rose Hill",
    "Rose Hill",
    "Kirkland",
    "Bellevue Core",
    "Downtown Bellevue",
    "Bellevue",
    "Redmond Downtown",
    "Downtown Redmond",
    "Redmond",
    "Woodinville Wine Country",
    "Woodinville",
    "Bothell",
    "Kenmore",
    "Sammamish",
    "Issaquah",
    "Renton",
    "Tukwila",
    "Marymoor",
    "Cottage Lake",
    "Sea-Tac Airport",
    "SeaTac Airport",
    "SeaTac",
    "SEA Airport",
    "Capitol Hill",
    "Seattle Center",
    "Queen Anne",
    "South Lake Union",
    "SLU",
    "University District",
    "U District",
    "UW District",
    "SoDo",
    "SODO",
    "Downtown Seattle",
    "Seattle Core",
    "Fremont",
    "Ballard",
    "Belltown",
    "West Seattle",
    "Columbia City",
    "Rainier Beach",
    "Lake City",
    "Greenwood",
    "Phinney",
    "Magnolia",
    "Northgate",
    "Central District",
    "Beacon Hill",
    "Georgetown",
    "Seattle",
)

_AREA_ALT = "|".join(re.escape(name) for name in sorted(KNOWN_AREA_NAMES, key=len, reverse=True))

_INJECTION_RE = re.compile(
    r"(?i)\b(ignore\s+(?:all\s+)?previous\s+instructions|"
    r"run\s+a\s+shell\s+command|"
    r"system\s+prompt|"
    r"execute\s+command|"
    r"upload\s+your\s+data|"
    r"rm\s+-rf|"
    r"curl\s+https?://|"
    r"invoke-webrequest)\b"
)

_SUPPORT_FLOW_RE = re.compile(
    r"(?i)\b(awaiting\s+your\s+reply|send\s+us\s+a\s+message!?|connect(?:ing)?\s+you\s+with\s+support)\b"
)

_SENSITIVE_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SENSITIVE_PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")
_SENSITIVE_COORD_RE = re.compile(r"(?<!\d)4[78]\.\d{4,}\s*,\s*-12[123]\.\d{4,}(?!\d)")


def detect_sensitive_text(raw_text: str) -> list[str]:
    """Detect unexpected PII (emails, phone numbers, raw GPS coordinates) in pasted text."""
    findings: list[str] = []
    if _SENSITIVE_EMAIL_RE.search(raw_text or ""):
        findings.append("email_address")
    if _SENSITIVE_PHONE_RE.search(raw_text or ""):
        findings.append("phone_number")
    if _SENSITIVE_COORD_RE.search(raw_text or ""):
        findings.append("precise_coordinates")
    return findings


def redact_sensitive_text(raw_text: str) -> str:
    """Redact unexpected emails, phone numbers, and precise coordinates from text before saving."""
    redacted = _SENSITIVE_EMAIL_RE.sub("[REDACTED_EMAIL]", raw_text or "")
    redacted = _SENSITIVE_PHONE_RE.sub("[REDACTED_PHONE]", redacted)
    redacted = _SENSITIVE_COORD_RE.sub("[REDACTED_COORDS]", redacted)
    return redacted

_BACKEND_FIELD_RE = re.compile(
    r"\b((?:etr|estimated_wait_time|wait_time|driver_wait|req_count)_[a-z0-9_]+)\b",
    re.IGNORECASE,
)

_EXPLICIT_P90_RE = re.compile(
    r"(?i)(?:\b90th[\s-]*percentile\b|(?<!etr_)\bp90\b)"
)
_EXPLICIT_P50_RE = re.compile(
    r"(?i)(?:\b50th[\s-]*percentile\b|\bmedian\b|(?<!etr_)\bp50\b)"
)
_EXPLICIT_MEAN_RE = re.compile(
    r"(?i)(?:\baverage\s+wait\b|\bmean\s+wait\b)"
)


def get_prompt_catalog() -> list[dict]:
    """Return the prewritten prompt catalog with live character counts and soft-cap status."""
    out = []
    for item in PROMPT_CATALOG:
        length = len(item.default_text)
        out.append({
            "id": item.id,
            "title": item.title,
            "purpose": item.purpose,
            "default_text": item.default_text,
            "char_count": length,
            "within_recommended_150": length <= PROMPT_SOFT_CHAR_WARN,
            "within_soft_cap_200": length <= PROMPT_SOFT_CHAR_CAP,
        })
    return out


def evaluate_prompt_length(text: str) -> dict:
    """Measure prompt length without falsely claiming an exact Uber maximum."""
    length = len(text or "")
    if length == 0:
        note = "Prompt is empty."
        level = "empty"
    elif length <= PROMPT_SOFT_CHAR_WARN:
        note = f"{length} chars — compact (under {PROMPT_SOFT_CHAR_WARN}-char practical target)."
        level = "ok"
    elif length <= PROMPT_SOFT_CHAR_CAP:
        note = (
            f"{length} chars — above {PROMPT_SOFT_CHAR_WARN}-char target but within "
            f"{PROMPT_SOFT_CHAR_CAP}-char soft cap (Uber's exact limit is unverified)."
        )
        level = "warn"
    else:
        note = (
            f"{length} chars — exceeds {PROMPT_SOFT_CHAR_CAP}-char soft cap; Uber Assistant's "
            f"input box may truncate this prompt."
        )
        level = "over_soft_cap"
    return {
        "char_count": length,
        "level": level,
        "note": note,
    }


def compute_fingerprint(raw_response: str) -> str:
    """Compute SHA-256 fingerprint over normalized whitespace for duplicate detection."""
    normalized = re.sub(r"\s+", " ", (raw_response or "").strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _resolve_area_key(area_label: str) -> str | None:
    if area_label.strip().lower() in ("unassigned area", "unassigned", "unknown", ""):
        return None
    rec = zone_record(area_label)
    if rec is not None:
        return rec.id
    slug = canonical_zone(area_label)
    return slug if slug != "unknown" else None


_NEGATION_PREFIX_RE = re.compile(
    r"(?i)(?:\bnot\b|\bno\b|\bnever\b|\bisn['’]?t\b|\baren['’]?t\b|\bwasn['’]?t\b|\bweren['’]?t\b|"
    r"\brather\s+than\b|\binstead\s+of\b|\bunverified\b|\bunknown\s+whether\b|\bcannot\s+confirm\b)"
    r"[^.;:!?]{0,40}$"
)
_REPLY_CONTEXT_PREFIX_RE = re.compile(
    r"(?i)(?:reply(?:\s+time|\s+sent|\s+received)?|captured(?:\s+at)?|pasted(?:\s+at)?|imported(?:\s+at)?|chat\s+timestamp)\s*[:=-]?\s*$"
)
_SOURCE_CONTEXT_PREFIX_RE = re.compile(
    r"(?i)(?:source\s+(?:update\s+)?time|source\s+window(?:\s+started\s+at)?|data\s+(?:as\s+of|updated(?:\s+at)?)|updated(?:\s+at)?|as\s+of)\s*[:=-]?\s*$"
)


def _extract_source_timestamps(raw_text: str) -> tuple[str | None, str | None, bool, str | None]:
    """Return (parsed_iso_if_tz_explicit, raw_claimed_string, explicitly_na, reply_display_time)."""
    na_match = re.search(
        r"(?i)\b(?:update\s+time|source\s+(?:update\s+)?time|updated|source\s+window)\s*[:=-]?\s*N/?A\b",
        raw_text,
    )
    if na_match:
        return None, None, True, None

    reply_time: str | None = None
    for iso_match in re.finditer(
        r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2}))\b",
        raw_text,
    ):
        raw_str = iso_match.group(1)
        prefix = raw_text[max(0, iso_match.start() - 45) : iso_match.start()]
        is_reply = bool(_REPLY_CONTEXT_PREFIX_RE.search(prefix))
        try:
            dt = datetime.fromisoformat(raw_str.replace(" ", "T").replace("Z", "+00:00"))
            parsed_iso = dt.astimezone(UTC).isoformat()
        except ValueError:
            parsed_iso = None
        if is_reply:
            if reply_time is None:
                reply_time = parsed_iso or raw_str
            continue
        return parsed_iso, raw_str, False, reply_time

    human_match = re.search(
        r"(?i)\b(?:latest\s+source\s+window\s+started\s+at|source\s+(?:update\s+)?time\s*[:=-]?|updated\s+(?:at\s+)?|as\s+of)"
        r"\s*([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM)?(?:\s*(?:local\s+time|PDT|PST|UTC|[+-]\d{2}:?\d{2}))?"
        r"(?:\s+on\s+[A-Za-z]+\s+\d{1,2},\s+\d{4})?)",
        raw_text,
    )
    if human_match:
        claimed_raw = human_match.group(1).strip().rstrip(".")
        tz_match = re.search(
            r"(?i)^(\d{1,2}):(\d{2})\s*(AM|PM)\s*(PDT|PST|UTC)\s+on\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})$",
            claimed_raw,
        )
        if tz_match:
            hr, mn, ampm, tz_abbr, date_part = tz_match.groups()
            offset = {"PDT": "-07:00", "PST": "-08:00", "UTC": "+00:00"}[tz_abbr.upper()]
            try:
                dt_naive = datetime.strptime(f"{date_part} {hr}:{mn} {ampm.upper()}", "%B %d, %Y %I:%M %p")
                iso_str = dt_naive.strftime("%Y-%m-%dT%H:%M:00") + offset
                return datetime.fromisoformat(iso_str).astimezone(UTC).isoformat(), claimed_raw, False, reply_time
            except ValueError:
                pass
        return None, claimed_raw, False, reply_time

    return None, None, False, reply_time


def _is_negated_match(text_segment: str, match_start: int, match_end: int) -> bool:
    before = text_segment[max(0, match_start - 45) : match_start]
    if _NEGATION_PREFIX_RE.search(before):
        return True
    after = text_segment[match_end : min(len(text_segment), match_end + 32)].lower()
    if re.search(r"^\s*(?:is|are|was|were)\s+(?:not|unverified|unknown)\b", after):
        return True
    return False


def _detect_explicit_statistic(text_segment: str) -> tuple[str, str | None]:
    found: list[tuple[str, str]] = []
    for stat_name, rx in (("p90", _EXPLICIT_P90_RE), ("p50", _EXPLICIT_P50_RE), ("mean", _EXPLICIT_MEAN_RE)):
        for m in rx.finditer(text_segment):
            if not _is_negated_match(text_segment, m.start(), m.end()):
                found.append((stat_name, m.group(0)))
                break
    distinct_stats = list(dict.fromkeys(s for s, _ in found))
    if len(distinct_stats) == 1:
        return found[0]
    return "unknown", None


def _new_obs_builder(area_label: str) -> dict:
    clean_label = area_label.strip()
    return {
        "area_label": clean_label,
        "area_key": _resolve_area_key(clean_label),
        "requests_30m": None,
        "requests_is_approximate": False,
        "wait_minutes_exact": None,
        "wait_minutes_lower_bound": None,
        "wait_statistic": "unknown",
        "drive_minutes": None,
        "reported_source_time": None,
        "reported_source_time_raw": None,
        "claimed_source_field": None,
        "claimed_source_field_verified": False,
        "claimed_statistic_hint": None,
        "text_origin_set": set(),
        "field_evidence": {},
        "field_spans": {},
        "narrative_exact_waits": [],
        "card_exact_waits": [],
        "card_requests": None,
        "narrative_requests": None,
        "explicit_wait_na": False,
        "explicit_no_measurement": False,
        "warnings": [],
        "source_spans": [],
    }


def _add_warning(target_list: list[str], flag: str) -> None:
    if flag not in target_list:
        target_list.append(flag)


def parse_assistant_response(
    raw_response: str,
    *,
    user_prompt: str | None = None,
    display_timezone: str = "America/Los_Angeles",
    created_at: str | None = None,
    max_requests_30m: int = DEFAULT_MAX_REQUESTS_30M,
    max_wait_minutes: float = DEFAULT_MAX_WAIT_MINUTES,
    max_drive_minutes: float = DEFAULT_MAX_DRIVE_MINUTES,
) -> dict:
    """Deterministically parse a pasted Uber Assistant response into an import + observations preview."""
    raw = raw_response if isinstance(raw_response, str) else ""
    now_iso = created_at or datetime.now(UTC).isoformat()
    fingerprint = compute_fingerprint(raw)

    import_warnings: list[str] = []
    if _INJECTION_RE.search(raw):
        _add_warning(import_warnings, FLAG_PROMPT_INJECTION_IGNORED)
    if _SUPPORT_FLOW_RE.search(raw):
        _add_warning(import_warnings, FLAG_SUPPORT_FLOW_DETECTED)
    sensitive_kinds = detect_sensitive_text(raw)
    if sensitive_kinds:
        _add_warning(import_warnings, FLAG_SENSITIVE_TEXT_DETECTED)

    parsed_src_time, raw_src_time, explicit_time_na, reply_display_time = _extract_source_timestamps(raw)
    if parsed_src_time is None:
        _add_warning(import_warnings, FLAG_SOURCE_TIMESTAMP_UNAVAILABLE)

    builders: dict[str, dict] = {}
    order: list[str] = []

    def get_builder(area_name: str) -> dict:
        key = area_name.strip().lower()
        if key not in builders:
            builders[key] = _new_obs_builder(area_name)
            order.append(key)
        return builders[key]

    lines = [ln.strip() for ln in raw.splitlines()]

    # Pass 1: Detect multi-line UI cards:
    # Line i:   "<Area> (<N> min away)" or "<Area>" followed by "About <N> requests in last 30 min"
    card_Header_re = re.compile(
        rf"^(?P<area>{_AREA_ALT})(?:\s*\(\s*~?(?P<drive>-?\d+(?:\.\d+)?)\s*(?:min|minutes?)\s+away\s*\))?$",
        re.IGNORECASE,
    )
    card_req_re = re.compile(
        r"^(?P<approx>about|approx\.?|approximately|~)?\s*(?P<req>-?\d+)\s+requests?\s+in\s+(?:the\s+)?last\s+30\s*(?:min|minutes?)$",
        re.IGNORECASE,
    )
    card_wait_re = re.compile(
        r"^(?:est\.?|estimated|driver\s+wait\s*[:=-]?|wait\s*[:=-]?)?\s*~?"
        r"(?:(?P<na>n/?a|unavailable)|(?P<val>-?\d+(?:\.\d+)?)(?P<plus>\+)?\s*(?:min|minutes?))"
        r"(?:\s*wait)?$",
        re.IGNORECASE,
    )

    consumed_lines: set[int] = set()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if not line:
            idx += 1
            continue
        m_head = card_Header_re.match(line)
        if m_head:
            next1 = lines[idx + 1] if idx + 1 < len(lines) else ""
            next2 = lines[idx + 2] if idx + 2 < len(lines) else ""
            m_req = card_req_re.match(next1)
            m_wait_1 = card_wait_re.match(next1)
            m_wait_2 = card_wait_re.match(next2) if m_req else None

            if m_req or m_wait_1 or m_head.group("drive") is not None:
                area_name = m_head.group("area")
                b = get_builder(area_name)
                b["text_origin_set"].add("card")
                b["source_spans"].append(line)
                consumed_lines.add(idx)

                if m_head.group("drive") is not None:
                    d_val = float(m_head.group("drive"))
                    b["drive_minutes"] = int(d_val) if d_val.is_integer() else d_val
                    b["field_evidence"]["drive_minutes"] = "ui_card"
                    b["field_spans"]["drive_minutes"] = line

                if m_req:
                    consumed_lines.add(idx + 1)
                    b["source_spans"].append(next1)
                    r_val = int(m_req.group("req"))
                    b["requests_30m"] = r_val
                    b["card_requests"] = r_val
                    b["requests_is_approximate"] = bool(m_req.group("approx"))
                    b["field_evidence"]["requests_30m"] = "ui_card"
                    b["field_spans"]["requests_30m"] = next1

                wait_match = m_wait_2 if m_req else m_wait_1
                wait_line_idx = (idx + 2) if m_req else (idx + 1)
                if wait_match:
                    consumed_lines.add(wait_line_idx)
                    w_span = lines[wait_line_idx]
                    b["source_spans"].append(w_span)
                    if wait_match.group("na"):
                        b["explicit_wait_na"] = True
                    elif wait_match.group("val") is not None:
                        w_num = float(wait_match.group("val"))
                        w_clean = int(w_num) if w_num.is_integer() else w_num
                        if wait_match.group("plus"):
                            b["wait_minutes_lower_bound"] = w_clean
                            b["field_evidence"]["wait_minutes_lower_bound"] = "ui_card"
                            b["field_spans"]["wait_minutes_lower_bound"] = w_span
                        else:
                            b["wait_minutes_exact"] = w_clean
                            b["card_exact_waits"].append(w_clean)
                            b["field_evidence"]["wait_minutes_exact"] = "ui_card"
                            b["field_spans"]["wait_minutes_exact"] = w_span
                idx = (wait_line_idx + 1) if wait_match else ((idx + 2) if m_req else (idx + 1))
                continue
        idx += 1

    # Pass 2: Parse remaining narrative lines and sentences
    narrative_lines = [
        lines[i] for i in range(len(lines)) if i not in consumed_lines and lines[i]
    ]
    sentences: list[str] = []
    for nline in narrative_lines:
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9-])", nline):
            s_clean = s.strip()
            if s_clean:
                sentences.append(s_clean)

    colon_pattern = re.compile(
        rf"^(?:(?:summary|current|update|overview|status)\s*:\s*)?(?:[-*•]\s*)?(?P<area>{_AREA_ALT})\s*:\s*(?P<body>.+)$",
        re.IGNORECASE,
    )

    for sent in sentences:
        if _INJECTION_RE.search(sent):
            continue
        if re.match(r"(?i)^(?:summary|current|update|overview|status)\s*:$", sent):
            continue
        if re.match(r"(?i)^update\s+time\s*:\s*n/?a\.?$", sent):
            continue
        if re.match(r"(?i)^these\s+estimates\s+are\s+current\.?$", sent):
            continue

        # Pattern A: "<Area>: 70 requests, 72 minutes" or "- <Area>: 120 requests in the last 30 mins, 4 min wait"
        m_colon = colon_pattern.match(sent)
        if m_colon:
            area_name = m_colon.group("area")
            body = m_colon.group("body")
            b = get_builder(area_name)
            b["text_origin_set"].add("narrative")
            b["source_spans"].append(sent)

            for m_r in re.finditer(
                r"(?P<approx>about|approx\.?|approximately|~)?\s*(?P<req>-?\d+)\s+requests?(?:\s+in\s+(?:the\s+)?last\s+(?P<win>\d+)\s*(?:min|mins|minutes?))?",
                body,
                re.IGNORECASE,
            ):
                r_val = int(m_r.group("req"))
                b["narrative_requests"] = r_val
                b.setdefault("narrative_requests_list", []).append(r_val)
                if b["requests_30m"] is None:
                    b["requests_30m"] = r_val
                    b["requests_is_approximate"] = bool(m_r.group("approx"))
                    b["field_evidence"]["requests_30m"] = "assistant_narrative"
                    b["field_spans"]["requests_30m"] = sent

            # Check for waits and drive times in body
            for m_w in re.finditer(
                r"(?P<val>-?\d+(?:\.\d+)?)(?P<plus>\+)?[\s-]*(?:min|mins|minute|minutes)\b",
                body,
                re.IGNORECASE,
            ):
                local_pre = body[max(0, m_w.start() - 32) : m_w.start()].lower()
                local_suf = body[m_w.end() : min(len(body), m_w.end() + 24)].lower()
                if re.search(r"\b(?:in\s+(?:the\s+)?(?:last|past)|(?:last|past|previous|within)\s+)\s*$", local_pre):
                    continue
                if re.search(r"^\s*(?:away|drive|driving)\b", local_suf) or re.search(r"\b(?:drive|driving|travel|route)(?:\s+time)?\s*(?:is|of|:|=)?\s*$", local_pre):
                    d_num = float(m_w.group("val"))
                    b["drive_minutes"] = int(d_num) if d_num.is_integer() else d_num
                    b["field_evidence"]["drive_minutes"] = "assistant_narrative"
                    b["field_spans"]["drive_minutes"] = sent
                    continue
                w_num = float(m_w.group("val"))
                w_clean = int(w_num) if w_num.is_integer() else w_num
                if m_w.group("plus"):
                    b["wait_minutes_lower_bound"] = w_clean
                    b["field_evidence"]["wait_minutes_lower_bound"] = "assistant_narrative"
                    b["field_spans"]["wait_minutes_lower_bound"] = sent
                else:
                    b["wait_minutes_exact"] = w_clean
                    b["narrative_exact_waits"].append(w_clean)
                    b["field_evidence"]["wait_minutes_exact"] = "assistant_narrative"
                    b["field_spans"]["wait_minutes_exact"] = sent

            stat, stat_span = _detect_explicit_statistic(body)
            if stat != "unknown":
                b["wait_statistic"] = stat
                b["field_evidence"]["wait_statistic"] = "assistant_narrative"
                b["field_spans"]["wait_statistic"] = stat_span or sent

            m_bf = _BACKEND_FIELD_RE.search(body)
            if m_bf:
                field_name = m_bf.group(1)
                b["claimed_source_field"] = field_name
                b["claimed_source_field_verified"] = False
                if "p90" in field_name.lower():
                    b["claimed_statistic_hint"] = "p90"
                b["field_evidence"]["claimed_source_field"] = "assistant_narrative"
                b["field_spans"]["claimed_source_field"] = sent
            continue

        # Pattern B: "The 49-minute Redmond wait comes directly from the marketplace field etr_p90_min..."
        # or "Redmond's exact estimated time is 49 minutes, the 90th-percentile request-time estimate."
        m_pre_wait = re.search(
            rf"(?i)\b(?P<val>-?\d+(?:\.\d+)?)[\s-]*(?:min|minute|minutes)\s+(?P<area>{_AREA_ALT})\s+wait\b",
            sent,
        )
        if m_pre_wait:
            area_name = m_pre_wait.group("area")
            w_num = float(m_pre_wait.group("val"))
            w_clean = int(w_num) if w_num.is_integer() else w_num
            b = get_builder(area_name)
            b["text_origin_set"].add("narrative")
            b["source_spans"].append(sent)
            b["wait_minutes_exact"] = w_clean
            b["narrative_exact_waits"].append(w_clean)
            b["field_evidence"]["wait_minutes_exact"] = "assistant_narrative"
            b["field_spans"]["wait_minutes_exact"] = sent

            stat, stat_span = _detect_explicit_statistic(sent)
            if stat != "unknown":
                b["wait_statistic"] = stat
                b["field_evidence"]["wait_statistic"] = "assistant_narrative"
                b["field_spans"]["wait_statistic"] = stat_span or sent

            m_bf = _BACKEND_FIELD_RE.search(sent)
            if m_bf:
                field_name = m_bf.group(1)
                b["claimed_source_field"] = field_name
                b["claimed_source_field_verified"] = False
                if "p90" in field_name.lower():
                    b["claimed_statistic_hint"] = "p90"
                b["field_evidence"]["claimed_source_field"] = "assistant_narrative"
                b["field_spans"]["claimed_source_field"] = sent
            continue

        # Pattern C: Clauses mentioning one or more areas (e.g. T4 sentence 1, T5 multi-area clauses)
        # Check if sentence mentions any known area
        area_mentions = list(re.finditer(rf"\b(?P<area>{_AREA_ALT})\b", sent, re.IGNORECASE))
        if not area_mentions:
            # Global sentence (e.g. timestamp claim in T3 or separate metric sentence R3-07)
            if parsed_src_time or raw_src_time:
                for key in order:
                    if parsed_src_time:
                        builders[key]["reported_source_time"] = parsed_src_time
                    if raw_src_time:
                        builders[key]["reported_source_time_raw"] = raw_src_time

            distinct_raw_areas: dict[str, str] = {}
            for m_ra in re.finditer(rf"\b(?P<area>{_AREA_ALT})\b", raw, re.IGNORECASE):
                a_raw = m_ra.group("area")
                a_k = _resolve_area_key(a_raw) or a_raw.strip().lower()
                if a_k not in distinct_raw_areas:
                    distinct_raw_areas[a_k] = a_raw

            has_wait_or_req = bool(
                re.search(r"(?i)-?\d+(?:\.\d+)?\+?\s*(?:min|mins|minute|minutes)\b", sent)
                or re.search(r"(?i)-?\d+\s+requests?\b", sent)
            )
            if has_wait_or_req:
                target_area_name = (
                    next(iter(distinct_raw_areas.values()))
                    if len(distinct_raw_areas) == 1
                    else "Unassigned area"
                )
                b_un = get_builder(target_area_name)
                b_un["text_origin_set"].add("narrative")
                if sent not in b_un["source_spans"]:
                    b_un["source_spans"].append(sent)
                for m_r in re.finditer(
                    r"(?P<approx>about|approx\.?|approximately|~)?\s*(?P<req>-?\d+)\s+requests?(?:\s+in\s+(?:the\s+)?last\s+(?P<win>\d+)\s*(?:min|mins|minutes?))?",
                    sent,
                    re.IGNORECASE,
                ):
                    r_val = int(m_r.group("req"))
                    b_un["narrative_requests"] = r_val
                    b_un.setdefault("narrative_requests_list", []).append(r_val)
                    if b_un["requests_30m"] is None:
                        b_un["requests_30m"] = r_val
                        b_un["requests_is_approximate"] = bool(m_r.group("approx"))
                        b_un["field_evidence"]["requests_30m"] = "assistant_narrative"
                        b_un["field_spans"]["requests_30m"] = sent
                for m_w in re.finditer(
                    r"(?P<val>-?\d+(?:\.\d+)?)(?P<plus>\+)?[\s-]*(?:min|mins|minute|minutes)\b",
                    sent,
                    re.IGNORECASE,
                ):
                    local_pre = sent[max(0, m_w.start() - 32) : m_w.start()].lower()
                    local_suf = sent[m_w.end() : min(len(sent), m_w.end() + 24)].lower()
                    if re.search(r"\b(?:in\s+(?:the\s+)?(?:last|past)|(?:last|past|previous|within)\s+)\s*$", local_pre):
                        continue
                    if re.search(r"^\s*(?:away|drive|driving)\b", local_suf) or re.search(r"\b(?:drive|driving|travel|route)(?:\s+time)?\s*(?:is|of|:|=)?\s*$", local_pre):
                        d_num = float(m_w.group("val"))
                        b_un["drive_minutes"] = int(d_num) if d_num.is_integer() else d_num
                        b_un["field_evidence"]["drive_minutes"] = "assistant_narrative"
                        b_un["field_spans"]["drive_minutes"] = sent
                        continue
                    w_num = float(m_w.group("val"))
                    w_clean = int(w_num) if w_num.is_integer() else w_num
                    if m_w.group("plus"):
                        b_un["wait_minutes_lower_bound"] = w_clean
                        b_un["field_evidence"]["wait_minutes_lower_bound"] = "assistant_narrative"
                        b_un["field_spans"]["wait_minutes_lower_bound"] = sent
                    else:
                        b_un["wait_minutes_exact"] = w_clean
                        b_un["narrative_exact_waits"].append(w_clean)
                        b_un["field_evidence"]["wait_minutes_exact"] = "assistant_narrative"
                        b_un["field_spans"]["wait_minutes_exact"] = sent
                stat_un, stat_span_un = _detect_explicit_statistic(sent)
                if stat_un != "unknown":
                    b_un["wait_statistic"] = stat_un
                    b_un["field_evidence"]["wait_statistic"] = "assistant_narrative"
                    b_un["field_spans"]["wait_statistic"] = stat_span_un or sent
            continue

        # Split sentence on semicolons or "while" so multi-city clauses retain their local predicates
        clauses = [c.strip() for c in re.split(r";|\bwhile\b", sent, flags=re.IGNORECASE) if c.strip()]
        for clause in clauses:
            clause_areas = list(re.finditer(rf"\b(?P<area>{_AREA_ALT})\b", clause, re.IGNORECASE))
            if not clause_areas:
                continue
            clause_wait_unavailable = bool(
                re.search(r"(?i)\b(?:waits?\s+(?:are|is)\s+(?:unavailable|n/?a)|wait\s*[:=]?\s*n/?a)\b", clause)
            )
            clause_no_measurement = bool(
                re.search(r"(?i)\bno\s+current\s+measurement\b|\bno\s+data\b|\bunavailable\b", clause)
            )

            for idx_m, m_area in enumerate(clause_areas):
                area_name = m_area.group("area")
                seg_start = m_area.end()
                seg_end = clause_areas[idx_m + 1].start() if (idx_m + 1) < len(clause_areas) else len(clause)
                segment = clause[seg_start:seg_end]

                b = get_builder(area_name)
                b["text_origin_set"].add("narrative")
                if sent not in b["source_spans"]:
                    b["source_spans"].append(sent)

                # Extract request count in segment (e.g. "has 75 requests", "has 20,", "12 and")
                m_req_seg = re.search(
                    r"(?P<approx>about|approx\.?|approximately|~)?\s*(?:has\s+)?(?P<req>-?\d+)\s*(?:requests?)?\b",
                    segment,
                    re.IGNORECASE,
                )
                if m_req_seg:
                    # Ensure this number is not actually a wait minute or percentile
                    after_num = segment[m_req_seg.end() : m_req_seg.end() + 18].lower()
                    before_num = segment[: m_req_seg.start()].lower()
                    is_wait_num = (
                        after_num.startswith((" min", "-min", "+ min", "+ minute"))
                        or "wait" in before_num
                        or "time is" in before_num
                    )
                    if not is_wait_num and ("request" in clause.lower()):
                        r_val = int(m_req_seg.group("req"))
                        b["narrative_requests"] = r_val
                        if b["requests_30m"] is None:
                            b["requests_30m"] = r_val
                            b["requests_is_approximate"] = bool(m_req_seg.group("approx"))
                            b["field_evidence"]["requests_30m"] = "assistant_narrative"
                            b["field_spans"]["requests_30m"] = clause

                # Extract wait in segment
                for m_w_seg in re.finditer(
                    r"(?P<val>-?\d+(?:\.\d+)?)(?P<plus>\+)?[\s-]*(?:min|minute|minutes)\b",
                    segment,
                    re.IGNORECASE,
                ):
                    tail_seg = segment[m_w_seg.end() : m_w_seg.end() + 10].lower()
                    if tail_seg.startswith(" away") or "last 30" in segment[: m_w_seg.end()].lower():
                        continue
                    w_num = float(m_w_seg.group("val"))
                    w_clean = int(w_num) if w_num.is_integer() else w_num
                    if m_w_seg.group("plus"):
                        b["wait_minutes_lower_bound"] = w_clean
                        b["field_evidence"]["wait_minutes_lower_bound"] = "assistant_narrative"
                        b["field_spans"]["wait_minutes_lower_bound"] = clause
                    else:
                        b["wait_minutes_exact"] = w_clean
                        b["narrative_exact_waits"].append(w_clean)
                        b["field_evidence"]["wait_minutes_exact"] = "assistant_narrative"
                        b["field_spans"]["wait_minutes_exact"] = clause

                stat, stat_span = _detect_explicit_statistic(segment)
                if stat != "unknown":
                    b["wait_statistic"] = stat
                    b["field_evidence"]["wait_statistic"] = "assistant_narrative"
                    b["field_spans"]["wait_statistic"] = stat_span or clause

                m_bf = _BACKEND_FIELD_RE.search(segment)
                if m_bf:
                    field_name = m_bf.group(1)
                    b["claimed_source_field"] = field_name
                    b["claimed_source_field_verified"] = False
                    if "p90" in field_name.lower():
                        b["claimed_statistic_hint"] = "p90"
                    b["field_evidence"]["claimed_source_field"] = "assistant_narrative"
                    b["field_spans"]["claimed_source_field"] = clause

                if clause_wait_unavailable:
                    b["explicit_wait_na"] = True
                if clause_no_measurement and b["requests_30m"] is None and b["wait_minutes_exact"] is None and b["wait_minutes_lower_bound"] is None:
                    b["explicit_no_measurement"] = True

    # Finalize observations and run validation (Section 7)
    observations: list[dict] = []
    for key in order:
        b = builders[key]
        obs_warnings: list[str] = list(b["warnings"])
        _add_warning(obs_warnings, FLAG_AREA_BOUNDARY_UNKNOWN)

        if parsed_src_time and b["reported_source_time"] is None:
            b["reported_source_time"] = parsed_src_time
        if raw_src_time and b["reported_source_time_raw"] is None:
            b["reported_source_time_raw"] = raw_src_time
            if parsed_src_time is None:
                # Preserve relative source time display when timezone/date is implicit
                b["reported_source_time"] = raw_src_time

        if b["reported_source_time"] is None:
            _add_warning(obs_warnings, FLAG_SOURCE_TIMESTAMP_UNAVAILABLE)

        if b["wait_minutes_lower_bound"] is not None and b["wait_minutes_exact"] is None:
            _add_warning(obs_warnings, FLAG_WAIT_BUCKET_NOT_EXACT)

        if (b["wait_minutes_exact"] is not None or b["wait_minutes_lower_bound"] is not None) and b["wait_statistic"] == "unknown":
            _add_warning(obs_warnings, FLAG_WAIT_STATISTIC_UNKNOWN)

        if b["claimed_source_field"]:
            _add_warning(obs_warnings, FLAG_UNVERIFIED_BACKEND_FIELD)

        if b["requests_30m"] is None or (b["wait_minutes_exact"] is None and b["wait_minutes_lower_bound"] is None):
            _add_warning(obs_warnings, FLAG_MISSING_METRIC)

        # Check card vs narrative conflicts:
        # Note (T4): exact=49 and lower_bound=30 is NOT a conflict because 49 >= 30.
        # Conflict occurs if exact < lower_bound, or two distinct exact waits, or differing request counts.
        distinct_exact_waits = list(dict.fromkeys(b["narrative_exact_waits"] + b["card_exact_waits"]))
        has_conflict = False
        if (
            b["wait_minutes_exact"] is not None
            and b["wait_minutes_lower_bound"] is not None
            and float(b["wait_minutes_exact"]) < float(b["wait_minutes_lower_bound"])
        ):
            has_conflict = True
        if len(distinct_exact_waits) > 1:
            has_conflict = True
            _add_warning(obs_warnings, FLAG_AMBIGUOUS_WAIT_VALUES)
        if (
            b["card_requests"] is not None
            and b["narrative_requests"] is not None
            and b["card_requests"] != b["narrative_requests"]
        ):
            has_conflict = True
        if has_conflict:
            _add_warning(obs_warnings, FLAG_CARD_NARRATIVE_CONFLICT)

        # Out-of-range / negative checks
        req_val = b["requests_30m"]
        if req_val is not None and (req_val < 0 or req_val > max_requests_30m):
            _add_warning(obs_warnings, FLAG_OUT_OF_RANGE_VALUE)
        for w_check in (b["wait_minutes_exact"], b["wait_minutes_lower_bound"]):
            if w_check is not None and (float(w_check) < 0 or float(w_check) > max_wait_minutes):
                _add_warning(obs_warnings, FLAG_OUT_OF_RANGE_VALUE)
        if b["drive_minutes"] is not None and (float(b["drive_minutes"]) < 0 or float(b["drive_minutes"]) > max_drive_minutes):
            _add_warning(obs_warnings, FLAG_OUT_OF_RANGE_VALUE)

        origins = b["text_origin_set"]
        if "card" in origins and "narrative" in origins:
            text_origin = "both"
            provenance = "both"
        elif "card" in origins:
            text_origin = "card"
            provenance = "ui_card"
        elif "narrative" in origins:
            text_origin = "narrative"
            provenance = "assistant_narrative"
        else:
            text_origin = "unknown"
            provenance = "unknown"

        if has_conflict:
            verification_level = "contradictory"
        elif text_origin == "card" and not b["claimed_source_field"]:
            verification_level = "directly_visible"
        else:
            verification_level = "ai_reported_unverified"

        freshness = "timestamp_known" if b["reported_source_time"] is not None else "capture_time_only"

        metric_semantics: list[str] = []
        if b["requests_30m"] is not None:
            metric_semantics.append(
                "request_count_approx" if b["requests_is_approximate"] else "request_count_reported"
            )
        if b["wait_minutes_lower_bound"] is not None:
            metric_semantics.append("wait_lower_bound")
        if b["wait_minutes_exact"] is not None:
            if b["wait_statistic"] == "p90":
                metric_semantics.append("wait_p90_claimed")
            elif b["wait_statistic"] == "unknown":
                metric_semantics.append("wait_exact_statistic_unknown")
            else:
                metric_semantics.append(f"wait_{b['wait_statistic']}_claimed")

        obs_id = f"obs-{uuid4().hex[:12]}"
        observations.append({
            "id": obs_id,
            "area_label": b["area_label"],
            "area_key": b["area_key"],
            "requests_30m": b["requests_30m"],
            "requests_is_approximate": b["requests_is_approximate"],
            "wait_minutes_exact": b["wait_minutes_exact"],
            "wait_minutes_lower_bound": b["wait_minutes_lower_bound"],
            "candidate_exact_waits": distinct_exact_waits if len(distinct_exact_waits) > 1 else None,
            "wait_statistic": b["wait_statistic"],
            "drive_minutes": b["drive_minutes"],
            "reported_source_time": b["reported_source_time"],
            "reported_source_time_raw": b["reported_source_time_raw"],
            "claimed_source_field": b["claimed_source_field"],
            "claimed_source_field_verified": b["claimed_source_field_verified"],
            "claimed_statistic_hint": b["claimed_statistic_hint"],
            "text_origin": text_origin,
            "provenance": provenance,
            "verification_level": verification_level,
            "freshness": freshness,
            "metric_semantics": metric_semantics,
            "field_evidence": b["field_evidence"],
            "field_spans": b["field_spans"],
            "warnings": obs_warnings,
            "source_span": "\n".join(b["source_spans"]),
            "edited_by_user": False,
            "original_extracted": None,
        })

    if not observations:
        parse_status = "unparsed"
    elif any(FLAG_MISSING_METRIC in o["warnings"] for o in observations):
        parse_status = "partial"
    else:
        parse_status = "parsed"

    return {
        "id": f"imp-{uuid4().hex[:12]}",
        "created_at": now_iso,
        "display_timezone": display_timezone,
        "user_prompt": user_prompt,
        "raw_response": raw,
        "source_app": "uber_assistant_beta",
        "capture_method": "manual_paste",
        "reply_display_time": reply_display_time,
        "reported_source_time": parsed_src_time,
        "reported_source_time_raw": raw_src_time,
        "parser_version": PARSER_VERSION,
        "parse_status": parse_status,
        "consent_confirmed": True,
        "notes": None,
        "fingerprint": fingerprint,
        "warnings": import_warnings,
        "observations": observations,
    }


def recompute_observation_validation(
    obs: dict,
    *,
    max_requests_30m: int = DEFAULT_MAX_REQUESTS_30M,
    max_wait_minutes: float = DEFAULT_MAX_WAIT_MINUTES,
    max_drive_minutes: float = DEFAULT_MAX_DRIVE_MINUTES,
) -> dict:
    """Recompute observation warnings, verification level, and metric semantics after user edits."""
    import math
    updated = copy.deepcopy(obs)
    fe = updated.get("field_evidence") or {}
    wait_resolved = fe.get("wait_minutes_exact") == "user_correction"
    lower_resolved = fe.get("wait_minutes_lower_bound") == "user_correction"
    req_resolved = fe.get("requests_30m") == "user_correction"

    warnings: list[str] = []
    for w in updated.get("warnings") or []:
        if w == FLAG_NON_30M_REQUEST_WINDOW:
            _add_warning(warnings, w)
        elif w == FLAG_AMBIGUOUS_WAIT_VALUES and not wait_resolved:
            _add_warning(warnings, w)
        elif w == FLAG_AMBIGUOUS_REQUEST_VALUES and not req_resolved:
            _add_warning(warnings, w)
    _add_warning(warnings, FLAG_AREA_BOUNDARY_UNKNOWN)
    if updated.get("reported_source_time") is None:
        _add_warning(warnings, FLAG_SOURCE_TIMESTAMP_UNAVAILABLE)

    exact = updated.get("wait_minutes_exact")
    lower = updated.get("wait_minutes_lower_bound")
    drive = updated.get("drive_minutes")
    req = updated.get("requests_30m")
    stat = updated.get("wait_statistic") or "unknown"

    cand_waits = updated.get("candidate_exact_waits") or []
    if len(set(cand_waits)) > 1 and not wait_resolved:
        _add_warning(warnings, FLAG_AMBIGUOUS_WAIT_VALUES)
        _add_warning(warnings, FLAG_CARD_NARRATIVE_CONFLICT)

    if lower is not None and exact is None:
        _add_warning(warnings, FLAG_WAIT_BUCKET_NOT_EXACT)
    if (exact is not None or lower is not None) and stat == "unknown":
        _add_warning(warnings, FLAG_WAIT_STATISTIC_UNKNOWN)
    if updated.get("claimed_source_field"):
        _add_warning(warnings, FLAG_UNVERIFIED_BACKEND_FIELD)
    if req is None or (exact is None and lower is None):
        _add_warning(warnings, FLAG_MISSING_METRIC)
    if exact is not None and lower is not None and float(exact) < float(lower) and not (wait_resolved and lower_resolved):
        _add_warning(warnings, FLAG_CARD_NARRATIVE_CONFLICT)
    if FLAG_AMBIGUOUS_REQUEST_VALUES in warnings:
        _add_warning(warnings, FLAG_CARD_NARRATIVE_CONFLICT)

    out_of_range = False
    if req is not None and (int(req) < 0 or int(req) > max_requests_30m):
        out_of_range = True
    for w_val in (exact, lower):
        if w_val is not None and (not math.isfinite(float(w_val)) or float(w_val) < 0 or float(w_val) > max_wait_minutes):
            out_of_range = True
    if drive is not None and (not math.isfinite(float(drive)) or float(drive) < 0 or float(drive) > max_drive_minutes):
        out_of_range = True
    if out_of_range:
        _add_warning(warnings, FLAG_OUT_OF_RANGE_VALUE)

    if any(w in warnings for w in (FLAG_CARD_NARRATIVE_CONFLICT, FLAG_AMBIGUOUS_WAIT_VALUES, FLAG_AMBIGUOUS_REQUEST_VALUES)):
        updated["verification_level"] = "contradictory"
    elif updated.get("edited_by_user"):
        updated["verification_level"] = "user_confirmed"
    updated["warnings"] = warnings
    return updated


def apply_user_review_edits(import_record: dict, observation_edits: dict[str, dict]) -> dict:
    """Apply transparent user corrections during Review-Before-Save while preserving original_extracted and revalidating."""
    updated = copy.deepcopy(import_record)
    editable_fields = {
        "area_label",
        "requests_30m",
        "requests_is_approximate",
        "wait_minutes_exact",
        "wait_minutes_lower_bound",
        "wait_statistic",
        "drive_minutes",
    }
    any_edited = False
    new_obs_list = []
    for obs in updated.get("observations") or []:
        oid = obs.get("id")
        edit = observation_edits.get(oid) if oid else None
        if edit and edit.get("declined"):
            any_edited = True
            continue
        if edit:
            snapshot_before = obs.get("original_extracted") or {
                k: obs.get(k) for k in editable_fields
            }
            changed = False
            for k in editable_fields:
                if k in edit and edit[k] != obs.get(k):
                    obs[k] = edit[k]
                    obs.setdefault("field_evidence", {})[k] = "user_correction"
                    changed = True
            if changed:
                if "area_label" in edit:
                    obs["area_key"] = _resolve_area_key(str(obs.get("area_label") or ""))
                obs["edited_by_user"] = True
                obs["original_extracted"] = snapshot_before
                if edit.get("user_confirmed"):
                    obs["verification_level"] = "user_confirmed"
                any_edited = True
        obs = recompute_observation_validation(obs)
        new_obs_list.append(obs)
    updated["observations"] = new_obs_list
    if any_edited or updated.get("parse_status") in ("parsed", "partial"):
        updated["parse_status"] = "reviewed"
    return updated


def format_wait_display(obs: dict) -> str:
    """Render an observation's wait with accurate field-level statistic/provenance labels (UIA09)."""
    exact = obs.get("wait_minutes_exact")
    lower = obs.get("wait_minutes_lower_bound")
    stat = obs.get("wait_statistic") or "unknown"
    stat_ev = (obs.get("field_evidence") or {}).get("wait_statistic") or obs.get("provenance") or "unknown"
    stat_prefix = (
        "user-entered"
        if stat_ev == "user_correction"
        else ("card-visible" if stat_ev == "ui_card" else "AI-claimed")
    )
    stat_label = {
        "p90": f"{stat_prefix} P90",
        "p50": f"{stat_prefix} median (P50)",
        "mean": f"{stat_prefix} mean",
        "unknown": "unknown statistic",
    }.get(stat, "unknown statistic")

    lower_ev = (obs.get("field_evidence") or {}).get("wait_minutes_lower_bound") or obs.get("provenance") or "unknown"
    lower_label = {
        "ui_card": "card bucket (lower bound)",
        "assistant_narrative": "narrative bucket (lower bound)",
        "user_correction": "user-entered bucket (lower bound)",
    }.get(lower_ev, "bucket (lower bound)")

    parts = []
    if exact is not None:
        parts.append(f"{exact} min ({stat_label})")
    if lower is not None:
        parts.append(f"{lower}+ min {lower_label}")
    return " · ".join(parts) if parts else "N/A (unavailable)"


def compare_observations(
    earlier_obs: dict,
    later_obs: dict,
    *,
    earlier_created_at: str | None = None,
    later_created_at: str | None = None,
) -> dict:
    """Compare two observations for the same area without conflating incompatible statistics or rolling windows."""
    flags: list[str] = []
    notes: list[str] = []

    earlier_wait_label = format_wait_display(earlier_obs)
    later_wait_label = format_wait_display(later_obs)

    e_exact = earlier_obs.get("wait_minutes_exact")
    l_exact = later_obs.get("wait_minutes_exact")
    e_stat = earlier_obs.get("wait_statistic") or "unknown"
    l_stat = later_obs.get("wait_statistic") or "unknown"

    wait_statistic_mismatch = False
    wait_comparable = False
    wait_delta_minutes: float | None = None

    if e_exact is not None and l_exact is not None:
        if e_stat != l_stat or e_stat == "unknown" or l_stat == "unknown":
            wait_statistic_mismatch = True
            _add_warning(flags, FLAG_CROSS_SNAPSHOT_CHANGE)
            notes.append(
                f"Wait changed from {earlier_wait_label} to {later_wait_label}. "
                f"Because statistic types are not both verified and identical ({e_stat} vs {l_stat}), "
                f"this difference is NOT a verified {abs(float(l_exact) - float(e_exact)):.0f}-minute drop/increase."
            )
        else:
            wait_comparable = True
            wait_delta_minutes = float(l_exact) - float(e_exact)
            if wait_delta_minutes != 0:
                _add_warning(flags, FLAG_CROSS_SNAPSHOT_CHANGE)

    # Check overlapping 30-min rolling request window
    e_req = earlier_obs.get("requests_30m")
    l_req = later_obs.get("requests_30m")
    if e_req is not None and l_req is not None and e_req != l_req:
        _add_warning(flags, FLAG_CROSS_SNAPSHOT_CHANGE)
    if earlier_created_at and later_created_at:
        try:
            dt1 = datetime.fromisoformat(earlier_created_at.replace("Z", "+00:00"))
            dt2 = datetime.fromisoformat(later_created_at.replace("Z", "+00:00"))
            gap_min = abs((dt2 - dt1).total_seconds()) / 60.0
            if gap_min < 30.0:
                _add_warning(flags, FLAG_OVERLAPPING_ROLLING_WINDOW)
                notes.append(
                    f"Samples are {gap_min:.1f} min apart (<30 min); rolling 30-minute request counts "
                    f"overlap and must not be added together."
                )
        except ValueError:
            pass
    else:
        _add_warning(flags, FLAG_OVERLAPPING_ROLLING_WINDOW)

    # Check drive time context
    e_drive = earlier_obs.get("drive_minutes")
    l_drive = later_obs.get("drive_minutes")
    if e_drive is not None and l_drive is not None and e_drive != l_drive:
        _add_warning(flags, FLAG_DRIVE_TIME_CONTEXT_CHANGED)
        notes.append(
            f"Drive time changed from {e_drive} min to {l_drive} min. Drive time depends on the driver's "
            f"starting position and traffic at capture time; do not assume identical origin."
        )

    return {
        "area_label": later_obs.get("area_label") or earlier_obs.get("area_label"),
        "earlier_wait_display": earlier_wait_label,
        "later_wait_display": later_wait_label,
        "wait_statistic_mismatch": wait_statistic_mismatch,
        "wait_comparable": wait_comparable,
        "wait_delta_minutes": wait_delta_minutes,
        "earlier_requests_30m": e_req,
        "later_requests_30m": l_req,
        "earlier_drive_minutes": e_drive,
        "later_drive_minutes": l_drive,
        "flags": flags,
        "notes": notes,
    }


class AssistantObservationRepository:
    """Local-first JSON repository for reviewed Uber Assistant imports.

    Never feeds into production scoring. Supports duplicate detection, delete, delete-all, and export.
    Fails closed on corrupt storage rather than silently overwriting unreadable files (UIA08).
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.last_storage_error: str | None = None
        self.last_corrupt_backup_path: str | None = None

    def _read_store(self, *, fail_closed: bool = False) -> dict:
        if not self.path.exists():
            self.last_storage_error = None
            return {"schema_version": 2, "experimental": True, "imports": []}
        try:
            raw = self.path.read_text(encoding="utf-8")
            if not raw.strip():
                self.last_storage_error = None
                return {"schema_version": 2, "experimental": True, "imports": []}
            payload = json.loads(raw)
            if isinstance(payload, dict) and isinstance(payload.get("imports"), list):
                self.last_storage_error = None
                return payload
            raise ValueError("Store payload missing 'imports' list.")
        except Exception as exc:
            self.last_storage_error = f"Unparseable storage file ({self.path.name}): {exc}"
            try:
                backup = self.path.with_name(f"{self.path.stem}.corrupt-backup.json")
                if not backup.exists():
                    backup.write_bytes(self.path.read_bytes())
                self.last_corrupt_backup_path = str(backup)
            except OSError:
                pass
            if fail_closed:
                raise RuntimeError(self.last_storage_error) from exc
            return {
                "schema_version": 2,
                "experimental": True,
                "storage_corrupt": True,
                "storage_error": self.last_storage_error,
                "corrupt_backup_path": self.last_corrupt_backup_path,
                "imports": [],
            }

    def _write_store(self, store: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(f".{uuid4().hex}.tmp")
        tmp.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def list_imports(self) -> list[dict]:
        store = self._read_store()
        return list(store.get("imports") or [])

    def find_by_fingerprint(self, fingerprint: str) -> dict | None:
        for item in self.list_imports():
            if item.get("fingerprint") == fingerprint:
                return item
        return None

    def save_import(self, import_record: dict, *, allow_duplicate: bool = False) -> dict:
        import math
        store = self._read_store()
        if store.get("storage_corrupt"):
            return {
                "saved": False,
                "duplicate": False,
                "existing_import_id": None,
                "warnings": [FLAG_UNPARSEABLE_STORAGE],
                "error": store.get("storage_error"),
                "corrupt_backup_path": store.get("corrupt_backup_path"),
                "import": import_record,
            }
        for obs in import_record.get("observations") or []:
            for fld in ("requests_30m", "wait_minutes_exact", "wait_minutes_lower_bound", "drive_minutes"):
                val = obs.get(fld)
                if val is not None and (not math.isfinite(float(val)) or float(val) < 0):
                    return {
                        "saved": False,
                        "duplicate": False,
                        "existing_import_id": None,
                        "warnings": [FLAG_OUT_OF_RANGE_VALUE],
                        "error": f"Invalid non-finite or negative value for {fld}: {val}",
                        "import": import_record,
                    }
        imports: list[dict] = list(store.get("imports") or [])
        fp = import_record.get("fingerprint") or compute_fingerprint(import_record.get("raw_response") or "")
        existing = next((item for item in imports if item.get("fingerprint") == fp), None)

        if existing is not None and not allow_duplicate:
            warnings = list(import_record.get("warnings") or [])
            _add_warning(warnings, FLAG_DUPLICATE_IMPORT)
            return {
                "saved": False,
                "duplicate": True,
                "existing_import_id": existing.get("id"),
                "warnings": warnings,
                "import": existing,
            }

        record_to_save = copy.deepcopy(import_record)
        record_to_save["fingerprint"] = fp
        if existing is not None and allow_duplicate:
            record_to_save["id"] = f"imp-{uuid4().hex[:12]}"
            warnings = list(record_to_save.get("warnings") or [])
            _add_warning(warnings, FLAG_DUPLICATE_IMPORT)
            record_to_save["warnings"] = warnings

        revalidated_obs = []
        for obs in record_to_save.get("observations") or []:
            obs = recompute_observation_validation(obs)
            obs["import_id"] = record_to_save["id"]
            revalidated_obs.append(obs)
        record_to_save["observations"] = revalidated_obs

        imports.insert(0, record_to_save)
        store["imports"] = imports
        self._write_store(store)
        return {
            "saved": True,
            "duplicate": existing is not None,
            "existing_import_id": existing.get("id") if existing else None,
            "warnings": list(record_to_save.get("warnings") or []),
            "import": record_to_save,
        }

    def delete_import(self, import_id: str) -> bool:
        store = self._read_store()
        imports = list(store.get("imports") or [])
        filtered = [item for item in imports if item.get("id") != import_id]
        if len(filtered) == len(imports):
            return False
        store["imports"] = filtered
        self._write_store(store)
        return True

    def delete_all_imports(self) -> int:
        store = self._read_store()
        count = len(store.get("imports") or [])
        store["imports"] = []
        self._write_store(store)
        return count

    def export_json(self) -> str:
        store = self._read_store()
        return json.dumps(store, indent=2)
