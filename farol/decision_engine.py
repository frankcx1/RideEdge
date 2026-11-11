"""Arrival-aligned, cited local review. No provider calls, trip ledger or AI imports.

The legacy radar remains an unchanged control. This first wave retains its
discovery threshold, catalog and contribution scale; it does not claim a new
population model or a calibrated area-demand score.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta

from farol import radar, decision_policy, positioning_fallback

REASONS = {"activity": "Available activity evidence supports this option.",
           "event_exit": "The departure window overlaps estimated arrival.",
           "closing_window": "A closing departure window overlaps estimated arrival.",
           "travel": "The model favored this supported option's travel trade-off.",
           "insufficient_support": "No supported choice was selected for this window.",
           "positioning_fallback": "Area to consider · current activity and opening hours unverified. Shorter travel preferred."}


class DecisionValidationError(ValueError):
    """The model responded, but Python rejected its decision contract."""

    @property
    def safe_detail(self):
        allowed = {
            "Model must return all six outlook windows", "Review expired before validation",
            "Invalid review fields", "Invalid supporting evidence contract",
            "Abstention cannot claim supporting evidence", "Unknown or unsupported choice",
            "Evidence does not support this choice and window", "Reason not supported by cited family",
            "Contextual positioning cannot be described as supported activity",
            "Contextual positioning cannot displace a supported opportunity",
            "Opportunity expired during inference", "Contextual positioning route is infeasible",
            "Cited opportunity expired during inference", "Choice outside Now scope",
        }
        return str(self) if str(self) in allowed else "Invalid decision contract"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:20]


def normalize(snapshot):
    """Only merge verified identity or exact venue/title/time matches; retain receipts."""
    out = copy.deepcopy(snapshot)
    groups = {}
    rejected = []
    for sig in sorted(out.get("signals") or [], key=lambda s: (str(s.get("source")), str(s.get("id")))):
        details = sig.get("details") or {}
        source = str(sig.get("source") or "")
        if source.startswith(("openclaw", "grok", "eastside_doctrine", "situational")):
            rejected.append({"id": sig.get("id"), "reason": "import_or_authored_context"})
            continue
        if sig.get("basis") == "assumed" or details.get("context_only"):
            rejected.append({"id": sig.get("id"), "reason": "assumption_or_context"})
            continue
        # Titles are used only as exact identity keys, never supplied to the model.
        identity = details.get("canonical_event_id")
        if identity:
            key = ("verified", str(identity))
        elif sig.get("kind") == "event_exit" and details.get("venue") and details.get("title"):
            key = ("exact", str(details["venue"]).casefold(), str(details["title"]).casefold(),
                   sig.get("zone"), sig.get("starts_at"), sig.get("ends_at"))
        else:
            key = ("record", source, sig.get("id"))
        receipt = {"source": source, "record_id": sig.get("id"), "raw_hash": digest(sig)}
        if key in groups:
            groups[key]["details"]["decision_provenance"].append(receipt)
            # Do not silently merge conflicting verified mappings into one usable event.
            if any(groups[key].get(k) != sig.get(k) for k in ("zone", "starts_at", "ends_at")):
                groups[key]["details"]["context_only"] = True
                rejected.append({"id": sig.get("id"), "reason": "conflicting_duplicate"})
        else:
            sig["details"] = {**details, "decision_provenance": [receipt]}
            groups[key] = sig
    out["signals"] = list(groups.values())
    return out, rejected


def arrival(row, at, route):
    """Revalidate normalized support, including at serving time after inference."""
    row = copy.deepcopy(row)
    when = at + timedelta(minutes=route["minutes"])
    row["arrival_at"] = when.isoformat()
    supports = []
    for e in row["evidence"]:
        start, end = radar.stamp(e.get("eligible_start")), radar.stamp(e.get("eligible_end"))
        expiry = radar.stamp(e.get("expires_at"))
        margin = e.get("remaining_minutes", 0)
        fallback = (row.get("decision_class") == "contextual_fallback" and e.get("family") == "positioning_context"
                    and e.get("role") == "context" and e.get("basis") == "best guess"
                    and row.get("fallback_catalog_id") and expiry is not None)
        relevant = ((e.get("role") == "opportunity" or fallback) and
                    (start is None or start <= when) and
                    (end is None or when + timedelta(minutes=margin) < end) and
                    (expiry is None or at < expiry))
        e["arrival_relevant"] = relevant
        if relevant:
            supports.append(e)
    row["arrival_eligible"] = bool(supports)
    # Strongest contribution per candidate: duplicate feeds cannot amplify a gathering.
    row["activity_weight"] = max((e.get("activity_weight", 0) for e in supports), default=0)
    row["score"] = round(row["activity_weight"] - min(route["minutes"] * .45, 30), 2)
    row["route"] = route
    row["reachable"] = bool(supports)
    deadlines = [radar.stamp(e["eligible_end"]) - timedelta(minutes=e.get("remaining_minutes", 0))
                 for e in supports if e.get("eligible_end")]
    row["ends_at"] = max(deadlines).isoformat() if deadlines else None
    return row


def _prepare(row, raw, policy, at, generated):
    row = copy.deepcopy(row)
    row["decision_policy"] = policy["version"]
    row["decision_class"] = "supported_opportunity"
    for e in row["evidence"]:
        sig = raw.get(e["id"], {})
        kind = sig.get("kind")
        details = sig.get("details") or {}
        family = ("event_exit" if kind == "event_exit" else "closing_window" if kind == "closing_wave"
                  else "patronage" if e.get("source") == "BestTime" else "context")
        e["family"] = family
        e["remaining_minutes"] = 0
        e["eligible_start"], e["eligible_end"] = e.get("starts_at"), e.get("ends_at")
        e["role"] = "context" if family == "context" else "opportunity"
        if e.get("basis") not in {"scheduled", "live", "live venue activity", "typical weekly activity", "best guess"}:
            e["role"] = "context"
        if family == "event_exit":
            start = radar.stamp(e.get("starts_at"))
            if start:
                e["eligible_start"] = (start - timedelta(minutes=policy["event_preposition_minutes"])).isoformat()
            e["anchor_basis"] = "provider_exit_window_with_labeled_duration_assumptions"
        elif family == "closing_window":
            close = radar.stamp(details.get("close_at"))
            if close:
                e["eligible_start"] = (close - timedelta(minutes=policy["closing_tail_minutes"])).isoformat()
                # Never extend past the source's validity/end merely because policy allows it.
                end = min(close + timedelta(minutes=policy["closing_tail_minutes"]), radar.stamp(e["ends_at"]))
                e["eligible_end"] = end.isoformat()
            e["anchor_basis"] = "catalog_hours_not_observed_last_call"
        elif family == "patronage":
            fetched = radar.stamp(e.get("fetched_at"))
            live = e.get("basis") == "live venue activity"
            e["expires_at"] = (fetched + timedelta(minutes=60 if live else 14*24*60)).isoformat() if fetched else generated.isoformat()
            # A pattern applies to this specific provider hour, not the entire future shift.
            e["eligible_start"] = at.replace(minute=0, second=0, microsecond=0).isoformat()
            e["eligible_end"] = (radar.stamp(e["eligible_start"]) + timedelta(hours=1)).isoformat()
            e["id"] += ":hour:" + e["eligible_start"]
            e["anchor_basis"] = "hourly_activity_not_verified_opening_hours"
            closes = [radar.stamp((s.get("details") or {}).get("close_at")) for s in raw.values()
                      if s.get("kind") == "closing_wave" and
                      "venue:" + str((s.get("details") or {}).get("venue_id")) == row["id"]]
            close = min((c for c in closes if c and c >= at), default=None)
            if close:
                e["eligible_end"] = min(radar.stamp(e["eligible_end"]), close-timedelta(minutes=policy["continuous_remaining_minutes"])).isoformat()
                e["anchor_basis"] = "hourly_activity_with_catalog_close_guard"
        e["provenance"] = details.get("decision_provenance") or [{"source": e.get("source"), "record_id": e["id"],
                                                                  "raw_hash": digest(e)}]
    if not any(e.get("role") == "opportunity" for e in row["evidence"]):
        row["decision_class"] = "context_only"
    return row


def build(origin, snapshot, besttime, *, now=None, routes=None, policy=None, control=None):
    policy = policy or decision_policy.load()
    now = now or datetime.now(UTC)
    control = control or radar.build(origin, snapshot, besttime, now=now, routes=routes, _policy=False)
    normalized, rejected = normalize(snapshot)
    raw = {s["id"]: s for s in normalized.get("signals", [])}
    view = copy.deepcopy(control)
    view["version"] = "departure-radar-v1"
    view["decision_policy"] = policy["version"]
    view["policy_hash"] = policy["sha256"]
    view["plan_mode"] = "independent_outlook"
    view["now_route_limit"] = policy["now_route_minutes"]
    view["positioning_fallback_enabled"] = policy["positioning_fallback_enabled"]
    view["next_refresh_at"] = (now + timedelta(minutes=policy["review_interval_minutes"])).isoformat()
    view["plan"] = []
    for i in range(6):
        at = now + timedelta(hours=i)
        prepared_rows = {}
        for sample_at in ([at, at+timedelta(minutes=30)] if i else [at]):
            rows, _ = radar.candidates(normalized, besttime, sample_at, now)
            for original in rows:
                prepared = _prepare(original, raw, policy, sample_at, now)
                if i == 0 and policy["positioning_fallback_enabled"]:
                    prepared = positioning_fallback.prepare(prepared, sample_at, now) or prepared
                if prepared["id"] in prepared_rows:
                    previous = prepared_rows[prepared["id"]]
                    previous["evidence"] = list({e["id"]: e for e in previous["evidence"]+prepared["evidence"]}.values())
                else:
                    prepared_rows[prepared["id"]] = prepared
        evaluated = []
        for prepared in prepared_rows.values():
            route = (routes or {}).get(prepared["id"]) if i == 0 else None
            if not route or not radar.fresh(route.get("fetched_at"), now, 10):
                route = radar.estimate_route(origin, prepared)
            if (not radar.number(route.get("minutes")) or route["minutes"] < 0 or
                    route.get("feasible") is False or route.get("status") in {"unreachable", "no_route"}):
                continue
            if i:
                starts = [radar.stamp(e.get("eligible_start")) for e in prepared["evidence"] if e.get("role") == "opportunity"]
                assessments = sorted({at, *(s for s in starts if s and at <= s < at+timedelta(hours=1))})
                choices = [(arrival(prepared, t, {**route, "minutes": 0}), t) for t in assessments]
                row, assessment = max(choices, key=lambda pair: (pair[0]["activity_weight"], -pair[1].timestamp()))
                row["route"] = route  # Reference only, not a fictional future journey.
                row["assessment_at"] = assessment.isoformat()
                if assessment >= at+timedelta(hours=1):
                    row["arrival_eligible"] = False
            else:
                row = arrival(prepared, at, route)
            miles = radar.distance(origin["latitude"], origin["longitude"], row["latitude"], row["longitude"])
            row.update(radius_miles=round(miles, 2), within_now_radius=miles <= 5,
                       route_reference="current_origin_reference", context_only=not row["arrival_eligible"])
            if miles <= 20:
                evaluated.append(row)
        eligible = [r for r in evaluated if r["arrival_eligible"] and
                    r.get("decision_class") != "contextual_fallback" and
                    (i > 0 or (r["within_now_radius"] and r["route"]["minutes"] <= policy["now_route_minutes"]))]
        eligible.sort(key=lambda r: (-r["score"] if i == 0 else -r["activity_weight"], r["id"]))
        if i == 0:
            fallback = sorted([r for r in evaluated if positioning_fallback.feasible(r, r["route"])],
                              key=positioning_fallback.sort_key)
            if not eligible:
                eligible = [r for r in fallback if r["within_now_radius"] and r["route"]["minutes"] <= policy["now_route_minutes"]]
            view["nearby"] = [r for r in evaluated if r["within_now_radius"]]
            view["further"] = [r for r in evaluated if r["arrival_eligible"] and r.get("decision_class") != "contextual_fallback" and
                               (not r["within_now_radius"] or r["route"]["minutes"] > policy["now_route_minutes"])]
            if not view["further"]:
                view["further"] = [r for r in fallback if not r["within_now_radius"] or r["route"]["minutes"] > policy["now_route_minutes"]]
            view["now"] = copy.deepcopy(eligible[:3])
        view["plan"].append({"starts_at": at.isoformat(), "ends_at": (at+timedelta(hours=1)).isoformat(),
            "options": sorted(eligible, key=lambda r: r["id"]), "selected_id": eligible[0]["id"] if eligible else None,
            "selection_basis": ("Contextual positioning · shortest travel" if eligible and eligible[0].get("decision_class") == "contextual_fallback"
                                else "Departure-aware evidence ranking"), "route_reference": "current_origin_reference",
            "repeat_area": bool(i and eligible and eligible[0]["id"] == view["plan"][-1]["selected_id"]),
            "outlook_note": "Independent opportunity outlook. Routes are reference estimates from your current location, not a chained shift route."})
    view["algorithm_plan"] = copy.deepcopy(view["plan"])
    view["snapshot_id"] = digest([control["snapshot_id"], policy["sha256"], view["plan"]])
    view["decision_audit"] = {"policy_version": policy["version"], "policy_hash": policy["sha256"],
        "mode": policy["mode"], "compiler": "typed-candidate-dossiers-v1", "legacy_control": [s["selected_id"] for s in control["plan"]],
        "algorithm": [s["selected_id"] for s in view["plan"]], "model": None,
        "validation": "algorithm_only", "excluded_imports_or_assumptions": len(rejected),
        "deduplicated_records": len(snapshot.get("signals") or []) - len(normalized.get("signals") or []) - len(rejected),
        "coverage": {"known_candidates": len({r["id"] for r in view["nearby"]+view["further"]}), "catalog_population": None,
                     "eligible_by_window": [len(s["options"]) for s in view["plan"]]},
        "limits": ["Existing discovery threshold retained; not a complete venue census.",
                   "Demographic weights zero; driver supply and Uber demand unobserved.",
                   "Capacity weighting, fuzzy entity merging and six-hour trajectory optimization are deferred.",
                   "Closing guard applies where a catalog venue identity matches; otherwise remaining opening time is unknown."]}
    from farol import besttime_control
    from farol.besttime_cache import coverage
    bt = besttime_control.status()
    view["venue_coverage"] = {**coverage(besttime.get("venues") or [], now, now), "collection_paused": not bt.get("enabled")}
    bases = {e.get("basis") for r in view["nearby"]+view["further"] for e in r["evidence"] if e.get("arrival_relevant")}
    activity = "current readings" if "live venue activity" in bases else "cached typical patterns" if "typical weekly activity" in bases else "no usable venue readings"
    view["activity_coverage"] = f"Venue activity: {activity}. BestTime collection {'enabled' if bt.get('enabled') else 'paused'}."
    view["decision_state"] = (view["now"][0].get("decision_class", "supported_opportunity") if view["now"] else "none_supported")
    for r in view["now"]+view["nearby"]+view["further"]:
        r["activity_coverage"] = view["activity_coverage"]
    # Source reports must describe this engine's pool, not the legacy control.
    audit_pool = {r["id"]: r for r in view["nearby"]+view["further"]}
    view["_candidate_audit"] = [{"id": r["id"], "name": r["name"], "radius_miles": r["radius_miles"],
        "route": r["route"], "disposition": "context_only" if not r["arrival_eligible"] else
        "now_pool" if r["within_now_radius"] and r["route"]["minutes"] <= policy["now_route_minutes"] else "further_option",
        "evidence": [{k: e.get(k) for k in ("id", "source", "basis", "role", "arrival_relevant")} for e in r["evidence"]]}
        for r in audit_pool.values()]
    return radar.compare_plans(view)


def compile_request(view):
    """No names, descriptions, coordinates, scores, authored rules or imported prose."""
    catalog, evidence, windows, references = {}, {}, [], {}
    aliases = {key: f"p{i}" for i, key in enumerate(sorted({r["id"] for s in view["plan"] for r in s["options"]}))}
    for i, slot in enumerate(view["plan"]):
        candidates = []
        for row in sorted(slot["options"], key=lambda r: r["id"]):
            cid = aliases[row["id"]]
            catalog[cid] = row["id"]
            support = []
            for e in row["evidence"]:
                if not e.get("arrival_relevant") or (e.get("role") != "opportunity" and
                        not (row.get("decision_class") == "contextual_fallback" and e.get("family") == "positioning_context")):
                    continue
                eid = f"e{len(evidence)}"
                references[eid] = e["id"]
                evidence[eid] = {"candidate": cid, "window": i, "family": e["family"],
                    "basis": e.get("basis"), "value_own_peak": e.get("value"),
                    "window_start_from_arrival_minutes": _offset(e.get("eligible_start"), row["arrival_at"]),
                    "window_end_from_arrival_minutes": _offset(e.get("eligible_end"), row["arrival_at"]),
                    "measurement_time_known": bool(e.get("measurement_time")),
                    "source_ref": "s" + digest(e.get("source"))[:6]}
                support.append(eid)
            candidates.append({"id": cid, "area": row["zone"], "category": row["category"], "drive_minutes_from_current_origin": row["route"]["minutes"],
                               "route_basis": row["route"]["basis"], "support_ids": support})
        windows.append({"window": i, "candidates": candidates})
    def selection(ids, reasons, abstain=False):
        return {"type": "object", "additionalProperties": False,
            "properties": {"support_ids": {"type": "array", "items": {"type": "string", "maxLength": 16},
                                            "minItems": 0 if abstain else 1, "maxItems": 0 if abstain else 3},
                           "reason_code": {"type": "string", "enum": reasons},
                           "choice_id": {"type": "string", "enum": ids}},
            "required": ["support_ids", "reason_code", "choice_id"]}
    # Enforce the evidence/context/abstention distinction during decoding as well
    # as in Python. A shared unrestricted reason enum let Qwen call a catalog
    # guess "activity", rejecting an otherwise usable six-window response.
    groups = {"context": set(), "supported": set()}
    window_groups = []
    for slot in view["plan"]:
        kinds = set()
        for row in slot["options"]:
            kind = "context" if row.get("decision_class") == "contextual_fallback" else "supported"
            groups[kind].add(aliases[row["id"]]); kinds.add(kind)
        window_groups.append(kinds)
    definitions = {"abstention": selection(["none_supported"], ["insufficient_support"], True)}
    for kind, ids in groups.items():
        if ids:
            reasons = ["positioning_fallback"] if kind == "context" else ["activity", "event_exit", "closing_window", "travel"]
            definitions[kind] = selection(sorted(ids), reasons)
    # Python still enforces each window's exact ID set and evidence ownership/time.
    props = {f"window_{i}": {"anyOf": [{"$ref": f"#/$defs/{kind}"}
             for kind in ["abstention", *sorted(kinds)]]} for i, kinds in enumerate(window_groups)}
    schema = {"type": "object", "$defs": definitions, "properties": props,
              "required": list(props), "additionalProperties": False}
    return {"windows": windows, "evidence": evidence, "coverage": view["decision_audit"]["coverage"],
            "uncertainty": "pickup_demand_unobserved", "_references": references}, schema, catalog


def pack_request(request):
    """Lossless table encoding, not score pruning. Every eligible candidate survives."""
    # Factor invariant fields once; per-window evidence retains Python's offsets.
    candidates, bases, base_ids, evidence = {}, {}, {}, {}
    for key, value in request["evidence"].items():
        base = [value[k] for k in ("family", "basis", "value_own_peak", "measurement_time_known", "source_ref")]
        marker = json.dumps(base)
        bid = base_ids.setdefault(marker, f"b{len(base_ids)}")
        bases[bid] = base
        evidence[key] = [value["candidate"], value["window"], bid,
                         value["window_start_from_arrival_minutes"], value["window_end_from_arrival_minutes"]]
    windows = []
    for w in request["windows"]:
        rows = []
        for c in w["candidates"]:
            candidates[c["id"]] = [c[k] for k in ("area", "category", "drive_minutes_from_current_origin", "route_basis")]
            rows.append([c["id"], c["support_ids"]])
        windows.append([w["window"], rows])
    return {"candidate_columns": ["area", "category", "reference_drive_minutes", "route_basis"],
            "candidates": candidates,
            "basis_columns": ["family", "basis", "own_peak_percent", "measurement_time_known", "source_ref"],
            "bases": bases,
            "evidence_columns": ["candidate", "window", "basis_ref", "start_from_assessment_minutes", "end_from_assessment_minutes"],
            "evidence": evidence, "windows": windows,
            "window_row_columns": ["candidate", "support_ids"],
            "coverage": request["coverage"], "uncertainty": request["uncertainty"],
            **({"driver_question_untrusted": request["driver_question_untrusted"]} if request.get("driver_question_untrusted") else {})}



def _offset(value, arrival_at):
    dt = radar.stamp(value)
    return round((dt-radar.stamp(arrival_at)).total_seconds()/60, 1) if dt else None


def apply(view, parsed, request, catalog, *, now=None):
    try:
        return _apply(view, parsed, request, catalog, now=now)
    except (ValueError, TypeError, KeyError) as error:
        raise DecisionValidationError(str(error) if isinstance(error, ValueError) else "Invalid decision contract") from error


def _apply(view, parsed, request, catalog, *, now=None):
    if not isinstance(parsed, dict) or set(parsed) != {f"window_{i}" for i in range(6)}:
        raise ValueError("Model must return all six outlook windows")
    out = copy.deepcopy(view)
    clock = now or datetime.now(UTC)
    if not radar.fresh(view["generated_at"], clock, 20):
        raise ValueError("Review expired before validation")
    for i, slot in enumerate(out["plan"]):
        result = parsed[f"window_{i}"]
        if not isinstance(result, dict) or set(result) != {"choice_id", "reason_code", "support_ids"}:
            raise ValueError("Invalid review fields")
        choice, reason, refs = (result[k] for k in ("choice_id", "reason_code", "support_ids"))
        if reason not in REASONS or not isinstance(refs, list) or len(refs) > 3 or any(not isinstance(r, str) for r in refs):
            raise ValueError("Invalid supporting evidence contract")
        if choice == "none_supported":
            if refs or reason != "insufficient_support":
                raise ValueError("Abstention cannot claim supporting evidence")
            selected = None
        else:
            selected = next((r for r in slot["options"] if r["id"] == catalog.get(choice)), None)
            if not selected or not refs or reason == "insufficient_support":
                raise ValueError("Unknown or unsupported choice")
            for ref in refs:
                e = request["evidence"].get(ref)
                if not e or e["candidate"] != choice or e["window"] != i:
                    raise ValueError("Evidence does not support this choice and window")
            if reason in {"event_exit", "closing_window"} and not any(request["evidence"][r]["family"] == reason for r in refs):
                raise ValueError("Reason not supported by cited family")
            is_fallback = selected.get("decision_class") == "contextual_fallback"
            if is_fallback != (reason == "positioning_fallback"):
                raise ValueError("Contextual positioning cannot be described as supported activity")
            if is_fallback and any(r.get("decision_class") != "contextual_fallback" for r in slot["options"]):
                raise ValueError("Contextual positioning cannot displace a supported opportunity")
            checked = arrival(selected, clock if i == 0 else radar.stamp(selected["assessment_at"]),
                              selected["route"] if i == 0 else {**selected["route"], "minutes": 0})
            if not checked["arrival_eligible"]:
                raise ValueError("Opportunity expired during inference")
            if is_fallback and not positioning_fallback.feasible(checked, selected["route"]):
                raise ValueError("Contextual positioning route is infeasible")
            valid_evidence = {e["id"] for e in checked["evidence"] if e.get("arrival_relevant")}
            if any(request["_references"].get(ref) not in valid_evidence for ref in refs):
                raise ValueError("Cited opportunity expired during inference")
            if i == 0 and (not selected["within_now_radius"] or selected["route"]["minutes"] > view["now_route_limit"]):
                raise ValueError("Choice outside Now scope")
            selected["qwen_reason"] = REASONS[reason]
        slot.update(selected_id=selected["id"] if selected else None, selection_basis="Local Qwen / validated evidence",
                    qwen_reason=REASONS[reason], support_ids=refs)
    first = out["plan"][0]
    primary = next((r for r in first["options"] if r["id"] == first["selected_id"]), None)
    if primary:
        primary["activity_coverage"] = view["activity_coverage"]
    out["now"] = [primary, *[r for r in first["options"] if r["id"] != primary["id"]][:2]] if primary else []
    out["decision_audit"].update(validation="passed", model=[s["selected_id"] for s in out["plan"]],
                                cited_support_count=sum(len(s["support_ids"]) for s in out["plan"]))
    # A valid "no supported move" answer must not erase separately labeled
    # positioning alternatives. Preserve the model's actual abstention in audit;
    # Python, not Qwen, owns this contextual display choice.
    if primary is None and view.get("positioning_fallback_enabled"):
        alternatives = []
        for row in first["options"]:
            if row.get("decision_class") != "contextual_fallback":
                continue
            checked = arrival(row, clock, row["route"])
            if (positioning_fallback.feasible(checked, checked["route"]) and checked["within_now_radius"] and
                    checked["route"]["minutes"] <= view["now_route_limit"]):
                checked["activity_coverage"] = view["activity_coverage"]
                checked["qwen_reason"] = "Qwen selected no supported move. This is a Python-checked area to consider; current activity and hours remain unverified."
                alternatives.append(checked)
        alternatives.sort(key=positioning_fallback.sort_key)
        if alternatives:
            out["now"] = alternatives[:3]
            first.update(selected_id=alternatives[0]["id"], selection_basis="Contextual positioning · no supported Qwen choice",
                         qwen_reason=alternatives[0]["qwen_reason"])
            out["decision_audit"]["contextual_alternatives_after_abstention"] = True
    out["decision_state"] = out["now"][0].get("decision_class", "supported_opportunity") if out["now"] else "none_supported"
    return out


def ask_model(view, *, valid=None, job_kind="radar-plan", question=None, **_):
    from farol import local, local_runtime
    policy = decision_policy.load()
    if policy["sha256"] != view["policy_hash"]:
        raise ValueError("Decision policy changed; rebuild evidence before inference")
    request, schema, catalog = compile_request(view)
    if question:
        request["driver_question_untrusted"] = str(question)[:700]
    endpoint, alias = local_runtime.settings()
    with local_runtime.session(endpoint, alias, job_kind=job_kind, valid=valid) as session:
        payload, _, _ = local.complete(system=policy["system_instruction"], user=json.dumps(pack_request(request), separators=(",", ":")),
            cache_key=view["snapshot_id"], endpoint=endpoint, model_name=alias, model_profile="qwen",
            response_schema=schema, enable_thinking=False, max_tokens=policy["model_output_tokens"],
            timeout=policy["model_timeout_seconds"], metric_workload="departure-review",
            input_token_ceiling=policy["input_token_ceiling"])
        if valid and not valid():
            raise ValueError("Location or review context changed during inference")
        out = apply(view, local.narration_from_payload(payload), request, catalog)
    detail = ("Qwen selected no supported immediate move. Python retained separately labeled contextual areas to consider."
              if out["decision_audit"].get("contextual_alternatives_after_abstention") else
              "Local Qwen reviewed the supplied options; Python validated its selections and abstentions.")
    out["qwen"] = {"state": "ready", "model": alias, "detail": detail,
                   "prompt_budget": payload.get("rideedge_prompt_budget")}
    if session is not None:
        out["runtime"] = session.public()
    return radar.compare_plans(out)


def stabilize(view, previous, policy):
    """Retain only a still-supported incumbent under the same origin and policy."""
    if not previous or previous.get("policy_hash") != view.get("policy_hash") or not previous.get("now") or not view.get("now"):
        return view
    if radar.distance(view["origin"]["latitude"], view["origin"]["longitude"],
                      previous["origin"]["latitude"], previous["origin"]["longitude"]) > .1:
        return view
    incumbent = next((r for r in view["plan"][0]["options"] if r["id"] == previous["now"][0]["id"]), None)
    winner = view["now"][0]
    if (incumbent and incumbent.get("decision_class") != "contextual_fallback" and winner.get("decision_class") != "contextual_fallback"
            and winner["id"] != incumbent["id"] and 0 <= winner["score"]-incumbent["score"] < policy["hysteresis_points"]):
        view["plan"][0]["selected_id"] = incumbent["id"]
        view["plan"][0]["selection_basis"] = "Supported incumbent retained"
        view["plan"][0]["qwen_reason"] = "Python retained the supported incumbent because the new option was only a near-tie."
        incumbent["qwen_reason"] = view["plan"][0]["qwen_reason"]
        view["now"] = [incumbent, *[r for r in view["now"] if r["id"] != incumbent["id"]][:2]]
        view["decision_audit"]["stability"] = "Near-tie; retained supported incumbent. Model choice remains in audit."
    return radar.compare_plans(view)
