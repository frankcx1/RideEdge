"""Read-only participation in a specific radar decision, separate from feed health."""
from datetime import datetime

from farol.adapters import ADAPTERS
from farol.collect import ADAPTER_SOURCE_PREFIXES, FEED_CATALOG
from farol.radar_contract import project


def adapter_for(source):
    source = str(source or "").casefold()
    # The legacy inventory has historical aliases. Current adapter constants are
    # authoritative too (e.g. NWS "SEW", WSDOT Traveler Information, SEA FIFO).
    for adapter in ADAPTERS:
        prefix = getattr(adapter, "SOURCE", None)
        name = getattr(adapter, "NAME", None)
        if name in FEED_CATALOG and isinstance(prefix, str) and prefix and source.startswith(prefix.casefold()):
            return name
    for adapter, prefixes in ADAPTER_SOURCE_PREFIXES.items():
        if any(source.startswith(prefix.casefold()) for prefix in prefixes):
            return adapter
    if source.startswith("local "):
        return "local_catalogs"
    return "unmapped_sources"


def participation(view, now: datetime):
    """No provider, model or cache reads; report what the retained decision used.

    Presence in a selected candidate's evidence is not causal attribution of a
    model's choice, agreement between methods, or proof of demand.
    """
    if not view:
        return {"state": "no_decision", "sources": [],
                "note": "No retained radar decision. Open Now to establish a planning context."}
    current = project(view, now)
    labels = {key: label for key, (label, _) in FEED_CATALOG.items()}
    labels.update(local_catalogs="Local commercial-area catalogs", unmapped_sources="Other retained sources")
    rows = {key: {"adapter": key, "label": label, "candidate_records": [], "exclusions": [],
                  "selected_now_opportunities": [], "selected_now_context": [], "selected_now_travel": [], "plan_intervals": []}
            for key, label in labels.items()}

    def group(evidence):
        return rows[adapter_for(evidence.get("source"))]

    for candidate in view.get("_candidate_audit", []):
        grouped = {}
        for evidence in candidate["evidence"]:
            grouped.setdefault(adapter_for(evidence.get("source")), []).append(evidence)
        route = candidate.get("route", {})
        if route.get("source"):
            grouped.setdefault(adapter_for(route["source"]), []).append({**route, "role": "travel"})
        for adapter, evidence in grouped.items():
            rows[adapter]["candidate_records"].append({**{k: v for k, v in candidate.items() if k != "evidence"},
                                                       "evidence": evidence})
    for record in view.get("excluded", []):
        group(record)["exclusions"].append(record)
    for candidate in current.get("now", [])[:1]:
        route = candidate["route"]
        if route.get("source"):
            group(route)["selected_now_travel"].append({"place": candidate["name"], **route})
        for evidence in candidate["evidence"]:
            if not evidence.get("arrival_relevant", True):
                continue
            field = "selected_now_context" if evidence.get("role") == "context" else "selected_now_opportunities"
            group(evidence)[field].append({"id": evidence["id"], "source": evidence["source"], "basis": evidence["basis"]})
    for slot in view["plan"]:
        selected = next((r for r in slot["options"] if r["id"] == slot["selected_id"]), None)
        if selected is None:
            continue
        seen = set()
        route_evidence = [selected["route"]] if selected["route"].get("source") else []
        for evidence in selected["evidence"] + route_evidence:
            if not evidence.get("arrival_relevant", True):
                continue
            key = adapter_for(evidence.get("source"))
            if key not in seen:
                rows[key]["plan_intervals"].append({"starts_at": slot["starts_at"], "place": selected["name"],
                                                  "selection_basis": slot["selection_basis"]})
                seen.add(key)
    for row in rows.values():
        row.update(candidate_count=len(row["candidate_records"]), exclusion_count=len(row["exclusions"]),
                   now_opportunity_count=len(row["selected_now_opportunities"]), now_context_count=len(row["selected_now_context"]),
                   now_travel_count=len(row["selected_now_travel"]),
                   plan_interval_count=len(row["plan_intervals"]))
    return {"state": "stale" if current["evidence_stale"] or current["location_stale"] else "reviewed",
            "snapshot_id": view["snapshot_id"], "source_snapshot_id": view.get("source_snapshot_id"),
            "reviewed_at": view["generated_at"], "origin_label": view["origin"]["label"],
            "sources": list(rows.values()), "exclusion_scope": view.get("exclusion_scope"),
            "note": "Participation in the retained radar review, separate from source availability. "
                "Counts describe evidence attached to choices, not proven reasons Qwen chose them or measured rider demand. "
                "Future Plan use does not mean the opportunity is useful now; retained source reports may be newer than this review."}
