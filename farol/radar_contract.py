"""Version-one phone/car contract and request-time eligibility projection."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from farol import radar

Finite = Annotated[float, Field(allow_inf_nan=False)]


class ContractModel(BaseModel):
    # Additive provider/diagnostic fields survive; required fields still validate.
    model_config = ConfigDict(extra="allow")


class RadarOrigin(ContractModel):
    label: str
    zone: str
    mode: Literal["device", "selected_area"]
    latitude: Annotated[Finite, Field(ge=47, le=48.2)]
    longitude: Annotated[Finite, Field(ge=-123, le=-121.5)]
    fix_at: AwareDatetime | None = None
    accuracy_meters: Annotated[Finite, Field(ge=0)] | None = None


class RadarEvidence(ContractModel):
    id: str
    source: str
    basis: str
    text: str
    fetched_at: AwareDatetime | None = None
    measurement_time: AwareDatetime | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    value: Finite | None = None
    timing_note: str | None = None
    role: Literal["opportunity", "context"] | None = None
    arrival_relevant: bool | None = None


class RadarRoute(ContractModel):
    minutes: Annotated[Finite, Field(ge=0)]
    miles: Annotated[Finite, Field(ge=0)]
    basis: str
    fetched_at: AwareDatetime | None = None


class RadarPlace(ContractModel):
    id: str
    name: str
    zone: str
    latitude: Annotated[Finite, Field(ge=47, le=48.2)]
    longitude: Annotated[Finite, Field(ge=-123, le=-121.5)]
    radius_miles: Annotated[Finite, Field(ge=0)]
    within_now_radius: bool
    route: RadarRoute
    evidence: list[RadarEvidence]
    strength: str
    category: str
    pin_basis: str
    maps_url: str
    navigation_note: str
    decision_class: Literal["supported_opportunity", "contextual_fallback", "context_only"] | None = None
    hours_status: Literal["unknown", "open", "closed"] | None = None
    ends_at: AwareDatetime | None = None
    busyness: Finite | None = None
    busyness_basis: str | None = None
    context_only: bool = False
    reachable: bool | None = None
    arrival_at: AwareDatetime | None = None
    arrival_eligible: bool | None = None
    actionable: bool = False
    valid_until: AwareDatetime | None = None
    unavailable_reason: str | None = None


class RadarPlanInterval(ContractModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    selected_id: str | None
    selection_basis: str
    options: list[RadarPlace]
    repeat_area: bool = False
    outlook_note: str = ""

    @model_validator(mode="after")
    def selection_and_interval(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Plan interval must have positive elapsed duration")
        if self.selected_id is not None and self.selected_id not in {r.id for r in self.options}:
            raise ValueError("Plan selection must reference an available option")
        return self


class RadarModelState(ContractModel):
    state: str
    detail: str = ""
    code: str | None = None


class RadarScheduler(ContractModel):
    state: Literal["preview", "no_session", "expired", "reviewing", "scheduled", "blocked"]
    next_review_at: AwareDatetime | None = None
    session_expires_at: AwareDatetime | None = None


class RadarView(ContractModel):
    schema_version: Literal[1]
    version: str
    snapshot_id: str
    source_snapshot_id: str
    decision_revision: str
    location_generation: int
    generated_at: AwareDatetime
    server_time: AwareDatetime
    valid_until: AwareDatetime
    origin: RadarOrigin
    radius_miles: Finite
    now: list[RadarPlace]
    nearby: list[RadarPlace]
    further: list[RadarPlace]
    plan: Annotated[list[RadarPlanInterval], Field(min_length=6, max_length=6)]
    algorithm_plan: Annotated[list[RadarPlanInterval], Field(min_length=6, max_length=6)]
    qwen: RadarModelState
    scheduler: RadarScheduler
    evidence_stale: bool
    location_stale: bool
    refreshing: bool = False
    decision_state: Literal["supported_opportunity", "contextual_fallback", "none_supported"] = "none_supported"
    decision_message: str = ""

    @field_validator("schema_version", mode="before")
    @classmethod
    def version_type(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value

    @model_validator(mode="after")
    def consistent_decision(self):
        for plan in (self.plan, self.algorithm_plan):
            if any((slot.ends_at - slot.starts_at).total_seconds() != 3600 for slot in plan):
                raise ValueError("Plan uses six elapsed one-hour intervals")
            if any(left.ends_at != right.starts_at for left, right in pairwise(plan)):
                raise ValueError("Plan intervals must be contiguous")
        if self.now and self.now[0].id != self.plan[0].selected_id:
            raise ValueError("Now and Plan must share the immediate decision")
        return self


def source_identity(snapshot, besttime):
    data = json.dumps([snapshot, besttime], sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:20]


def decision_identity(view):
    # Runtime status and GPS fix timestamps are not new decisions.
    data = [view["snapshot_id"], view.get("qwen", {}).get("state"),
            [s.get("selected_id") for s in view["plan"]],
            [r["id"] for r in view.get("now", [])]]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:20]


def project(view, now: datetime):
    """Copy every time; never retain a projection keyed only by snapshot ID."""
    out = copy.deepcopy(view)
    # A selected option can be the same dict in Now and Plan. Deepcopy preserves
    # aliases: marking future-plan rows inspect-only must not disable Now.
    for collection in ("now", "nearby", "further", "plan", "algorithm_plan"):
        out[collection] = copy.deepcopy(view[collection])
    out.update(schema_version=1, server_time=now.isoformat(),
               decision_revision=decision_identity(view),
               location_generation=view.get("context_generation", 0))
    origin = out["origin"]
    expires = radar.stamp(out["generated_at"]) + timedelta(minutes=20)
    out["location_stale"] = origin["mode"] == "device" and not radar.fresh(origin.get("fix_at"), now, 5)
    if origin["mode"] == "device":
        fix = radar.stamp(origin.get("fix_at"))
        expires = min(expires, fix + timedelta(minutes=5) if fix else now)
    out["valid_until"] = expires.isoformat()
    out["evidence_stale"] = not radar.fresh(out["generated_at"], now, 20)

    def decorate(row):
        miles = radar.distance(origin["latitude"], origin["longitude"], row["latitude"], row["longitude"])
        # Never present a route from the previous origin as current live traffic.
        original = view.get("decision_origin", view["origin"])
        moved = radar.distance(origin["latitude"], origin["longitude"], original["latitude"], original["longitude"]) > .01
        route = row["route"]
        if moved or (route["basis"] != "estimated" and not radar.fresh(route.get("fetched_at"), now, 10)):
            row["route"] = radar.estimate_route(origin, row)
        row["radius_miles"] = round(miles, 2)
        row["within_now_radius"] = miles <= radar.RADIUS_MILES
        deadline = expires
        if radar.stamp(row.get("ends_at")):
            margin = 0 if row.get("decision_policy") else 10
            deadline = min(deadline, radar.stamp(row["ends_at"]) - timedelta(minutes=row["route"]["minutes"] + margin))
        for evidence in row["evidence"]:
            expires_at = radar.stamp(evidence.get("expires_at"))
            if expires_at:
                deadline = min(deadline, expires_at)
            basis = evidence.get("basis")
            if basis != "best guess":
                minutes = (60 if basis == "live venue activity" else 14*24*60
                           if basis == "typical weekly activity" else 45 if basis == "live" else 48*60)
                fetched = radar.stamp(evidence.get("fetched_at"))
                deadline = min(deadline, fetched + timedelta(minutes=minutes) if fetched else now)
        row["valid_until"] = deadline.isoformat()
        if row.get("decision_policy"):
            from farol.decision_engine import arrival as reassess
            arrival = reassess(row, now, row["route"])
        else:
            arrival = radar.on_arrival(row, now, row["route"])
        row["arrival_at"] = arrival["arrival_at"]
        row["arrival_eligible"] = arrival["arrival_eligible"]
        row["evidence"] = arrival.get("evidence", row["evidence"])
        if row.get("decision_class") == "contextual_fallback":
            from farol.positioning_fallback import feasible
            row["arrival_eligible"] = bool(out.get("positioning_fallback_enabled") and feasible(arrival, row["route"]))
        reason = ("location_stale" if out["location_stale"] else
                  "evidence_stale" if out["evidence_stale"] or deadline <= now else
                  "context_only" if row.get("context_only") else
                  "opportunity_not_active_on_arrival" if not row["arrival_eligible"] else
                  "outside_supported_range" if miles > radar.FURTHER_MILES else None)
        row["actionable"], row["unavailable_reason"] = reason is None, reason
        return row

    for key in ("now", "nearby", "further"):
        out[key] = [decorate(row) for row in out[key]]
    old_primary = out["now"][:1]
    # Do not silently promote an alternative and contradict Plan's selected ID.
    primary_ok = bool(old_primary and old_primary[0]["actionable"] and old_primary[0]["within_now_radius"]
                      and old_primary[0]["route"]["minutes"] <= out.get("now_route_limit", float("inf")))
    if old_primary and not primary_ok and not out["location_stale"]:
        out["evidence_stale"] = True
    out["now"] = [r for r in out["now"] if r["actionable"] and r["within_now_radius"]] if primary_ok else []
    out["further"] = [r for r in out["further"] if r["actionable"] and
                      (not r["within_now_radius"] or r["route"]["minutes"] > out.get("now_route_limit", float("inf")))]
    if out["evidence_stale"]:
        out["now"], out["further"] = [], []
        out["qwen"] = {"state": "stale", "detail": "This outlook needs a refresh before you act on it."}
    out["decision_state"] = (out["now"][0].get("decision_class", "supported_opportunity") if out["now"] else "none_supported")
    out["decision_message"] = (
        "Location is stale. Refresh location to see current options." if out["location_stale"] else
        "This review has expired. Refresh to check current options." if out["evidence_stale"] else
        "Area to consider · current activity and opening hours unverified. Shorter travel preferred." if out["decision_state"] == "contextual_fallback" else
        "No supported immediate move. Nearby, Plan and reports remain available." if out["decision_state"] == "none_supported" else
        "Current evidence supports an immediate positioning option.")
    # Plan remains inspectable. Future legs are not immediate navigation actions.
    for key in ("plan", "algorithm_plan"):
        for slot in out[key]:
            for row in slot["options"]:
                row["actionable"] = False
    out.pop("decision_origin", None)  # Internal calculation anchor, not a second device location.
    out.pop("_candidate_audit", None)  # Detailed participation belongs to the source report.
    return out
