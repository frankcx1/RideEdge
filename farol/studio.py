"""Read-only infrastructure dashboard. Viewing this page never collects or infers."""
import copy
import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import HTMLResponse

from farol.dashboard import ROOT
from farol import studio_monitor

router = APIRouter()


def demo_scenes():
    return json.loads((ROOT / "fixtures/contracts/recording-demo.json").read_text(encoding="utf-8"))["stages"]


def demo_scene(step):
    scenes = demo_scenes()
    if not 0 <= step < len(scenes):
        raise HTTPException(422, "Unknown replay scene")
    return scenes[step]


@router.get("/studio", response_class=HTMLResponse)
def studio_page():
    return HTMLResponse((ROOT / "farol/static/studio.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store"})


@router.get("/studio/story", response_class=HTMLResponse)
def studio_story_page():
    """Presentation of the same read-only evidence, paced for the podcast."""
    return HTMLResponse((ROOT / "farol/static/studio-story.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store"})


SOURCE_ROLES = {
    "google_places_closing": "Venue identity and opening hours anchor activity to real places.",
    "besttime_busyness": "Relative venue activity adds time-sensitive evidence; paid requests stay budget-gated.",
    "flightaware_sea": "Flight arrivals provide airport timing context; fetched only on demand.",
    "google_routes_traffic": "Travel estimates constrain whether a proposed move is reachable.",
    "wsdot_traffic": "Road and bridge alerts add operational constraints.",
    "nws_hourly": "Forecast conditions provide context for future operating windows.",
    "nws_live_observation": "Observed weather supplies current environmental context.",
    "wsf_colman_ferries": "Ferry arrival windows describe recurring passenger flows.",
    "amtrak_king_street": "Train arrivals provide time and place anchors for activity.",
    "onebusaway_transit": "Transit information adds local movement context.",
    "ticketmaster_events": "Event locations and schedules anchor potential departure windows.",
    "seatgeek_events": "A complementary event catalog broadens scheduled-event coverage.",
    "espn_seattle": "Sports schedules and game state provide event timing context.",
    "mlb_schedule": "Baseball schedules contribute stadium activity windows.",
    "nhl_schedule": "Hockey schedules contribute arena activity windows.",
    "seattle_special_events": "City event listings supply local geographic and timing context.",
    "seattle_community_events": "Community listings supplement large ticketed events.",
    "sea_fifo": "Airport operating context informs guidance; it does not predict dispatch.",
    "cruise_schedule": "Cruise schedules supply terminal activity windows.",
    "venue_hours": "A standing venue catalog supplies opening/closing context and scheduled closing windows; it is not a live crowd measurement.",
    "situational_demand_waves": "Local timing rules add explicitly assumed activity context.",
    "eastside_doctrine": "Local area knowledge complements observations without becoming a live measurement.",
    "openclaw_drop": "Locally supplied evidence retains its own provenance and freshness.",
}


@router.get("/api/studio")
def studio_data(mode: Literal["replay", "live", "captured"] = "live", step: int = Query(0, ge=0)):
    from farol import besttime_control, collect, decision_policy, radar_api, token_costs

    if mode == "captured":
        import re
        from farol.recording_capture import load_capture
        try:
            base = ROOT / ".cache/recording"
            selected = json.loads((base / "selected.json").read_text(encoding="utf-8"))["capture_id"]
            if not isinstance(selected, str) or not re.fullmatch(r"\d{8}T\d{6}Z-[a-f0-9]{8}", selected):
                raise ValueError("Invalid capture identity")
            return load_capture(base / selected / "captured-session.json")["studio"]
        except (OSError, ValueError, KeyError) as error:
            raise HTTPException(409, "No verified captured evaluation is selected") from error

    if mode == "replay":
        # Recording reference supplies source examples, never counterfeit host telemetry.
        health = copy.deepcopy(demo_scene(step)["health"])
        runtime = None
    else:
        health = collect.feed_health_view()
        runtime = studio_monitor.snapshot()
    for feed in health.get("feeds", []):
        feed["role"] = SOURCE_ROLES.get(feed["adapter"], "Additional source context with its own freshness and coverage.")
        aid = feed["adapter"]
        feed["measurement_group"] = ("Authored rule" if aid in {"sea_fifo", "situational_demand_waves", "eastside_doctrine"}
                                     else "Local catalog" if aid == "venue_hours" else "Imported evidence" if aid == "openclaw_drop" else "Dynamic source")
    with radar_api._lock:
        view = (radar_api._view or {}) if mode == "live" else {}
        from farol.radar_contract import project
        projected = project(view, datetime.now(UTC)) if view else {}
        audit = copy.deepcopy(view.get("decision_audit"))
        coverage = view.get("activity_coverage")
        generated = view.get("generated_at")
        venue_coverage = copy.deepcopy(view.get("venue_coverage"))
        from collections import Counter
        exclusions = dict(Counter(e.get("code") for e in view.get("excluded", [])))
    return {"mode": mode, "observed_at": datetime.now(UTC).isoformat(),
            "runtime": runtime, "besttime": besttime_control.status(), "health": health,
            "decision": {"policy": decision_policy.status(), "audit": audit, "activity_coverage": coverage,
                         "decision_state": projected.get("decision_state"), "decision_message": projected.get("decision_message"),
                         "location_stale": projected.get("location_stale"), "evidence_stale": projected.get("evidence_stale"),
                         "venue_coverage": venue_coverage, "exclusions": exclusions,
                         "model_review": projected.get("qwen"),
                         "generated_at": generated, "scope": "Latest retained session only; no provider/model work triggered by this page"},
            "token_costs": token_costs.rate_cards(),
            "boundary": "External providers supply evidence. Context, rules and Qwen inference run on workstation. Phone and Android Auto consume the same service; navigation is handed to Maps."}
