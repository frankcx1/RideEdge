"""Phone installation, isolated demo, and local asynchronous Ask endpoints."""
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from farol import ask
from farol.dashboard import ROOT
from farol.product import NAME, TAGLINE
from farol.rideedge import Constraints, compare

router = APIRouter()
STATIC = ROOT / "farol" / "static"
NO_STORE = {"Cache-Control":"no-store"}


def page(name):
    return HTMLResponse((STATIC / name).read_text(encoding="utf-8").replace("__PRODUCT_NAME__", NAME), headers=NO_STORE)


@router.get("/demo")
def demo():
    return RedirectResponse("/?demo=1#working")


@router.get("/podcast")
def podcast_page():
    return page("podcast.html")


@router.get("/api/podcast")
def podcast_plan(response: Response):
    from farol.podcast import recording_plan

    response.headers.update(NO_STORE)
    try:
        return recording_plan()
    except (OSError, ValueError) as error:
        raise HTTPException(503, "Recording transcript is unavailable or its cue phrases changed.") from error


@router.get("/product.js")
def product():
    return Response("window.RIDEEDGE_PRODUCT=" + json.dumps({"name":NAME, "tagline":TAGLINE}) + ";", media_type="text/javascript")


@router.get("/manifest.webmanifest")
def manifest():
    return Response(json.dumps({"id":"/rideedge", "name":NAME, "short_name":NAME, "description":TAGLINE,
        "start_url":"/?app=1", "scope":"/", "display":"standalone", "background_color":"#101413", "theme_color":"#101413",
        "icons":[{"src":f"/rideedge-icon-{size}.png", "sizes":f"{size}x{size}", "type":"image/png", "purpose":"any maskable"} for size in (192, 512)],
        "shortcuts":[{"name":"Working", "url":"/?app=1#working"}, {"name":"Around you", "url":"/awareness"}]}), media_type="application/manifest+json")


@router.get("/{asset}")
def asset_file(asset: str):
    # Registered after all normal API routes: exact allowlist, never a path join on arbitrary input.
    files = {"ask.js":"text/javascript", "location.js":"text/javascript", "pwa.js":"text/javascript", "service-worker.js":"text/javascript",
             "podcast.js":"text/javascript", "podcast.css":"text/css",
             "offline.html":"text/html", "rideedge-icon-192.png":"image/png", "rideedge-icon-512.png":"image/png"}
    if asset not in files:
        raise HTTPException(404)
    headers = {"Cache-Control":"no-cache"} if asset == "service-worker.js" else {}
    return FileResponse(STATIC / asset, media_type=files[asset], headers=headers)


@router.get("/api/ask/context")
def get_context(response: Response, mode: Literal["demo", "live"] = "demo", step: int = Query(0, ge=0, le=2), area: str = "bellevue_core"):
    response.headers.update(NO_STORE)
    try:
        ctx = ask.context(mode, step, area)
        return {"context":ctx, "comparison":compare(ctx, Constraints())}
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str = Field(max_length=50)
    constraints: Constraints = Field(default_factory=Constraints)


class AskRequest(ComparisonRequest):
    question: str = Field(min_length=1, max_length=700)
    fresh: bool = False


@router.post("/api/ask/compare")
def compare_context(body: ComparisonRequest):
    with ask._lock:
        ctx = ask._contexts.get(body.snapshot_id)
    if ctx is None:
        raise HTTPException(409, "Refresh this comparison first.")
    return Response(json.dumps(compare(ctx, body.constraints)), media_type="application/json", headers=NO_STORE)


@router.post("/api/ask")
def ask_question(body: AskRequest, response: Response):
    response.headers.update(NO_STORE)
    try:
        return ask.submit(body.snapshot_id, body.question, body.constraints, body.fresh)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(400, str(error)) from error


@router.get("/api/ask/jobs/{request_id}")
def ask_job(request_id: str, response: Response):
    response.headers.update(NO_STORE)
    return ask.job(request_id)


@router.get("/api/changes")
def changes(response: Response, area: str | None = None):
    from farol.changes import latest
    response.headers.update(NO_STORE)
    return latest(area)


@router.get("/api/usage")
def usage(response: Response):
    from farol.collect import status
    response.headers.update(NO_STORE)
    return status().get("last_run_usage") or {"providers":{}, "detail":"No measured collector run yet.", "dollar_cost":"unknown"}


@router.get("/api/demo/evidence")
def recorded_evidence(response: Response):
    """Allowlisted public fields from one existing capture; no fresh provider spend."""
    response.headers.update(NO_STORE)
    folder = ROOT / ".cache" / "simulations" / "20260918T043953Z"
    try:
        saved = json.loads((folder / "feed-cache" / "wsdot_alerts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"available":False, "detail":"Recorded public API evidence is not installed. The synthetic scenario works independently."}
    payload = saved.get("payload")
    from farol.adapters.wsdot import parse_alerts
    from farol.dashboard import FIXTURES
    from farol.signals import load_anchors
    from farol.tonight import ScoringSnapshot, score_window
    start = datetime.fromisoformat(saved["fetched_at"])
    parsed = parse_alerts(payload, start, start + timedelta(hours=3), fetched_at=saved["fetched_at"])
    ids = {row.id.split("-")[2] for row in parsed[:3]}
    excerpt = [{key:row.get(key) for key in ("AlertID", "HeadlineDescription", "StartTime", "EndTime", "Priority", "EventCategory") if key in row}
               for row in (payload if isinstance(payload, list) else []) if str(row.get("AlertID")) in ids][:2]
    signals = [asdict(row) for row in parsed[:3]]
    normalized = [{key:row.get(key) for key in ("id", "kind", "zone", "source", "fetched_at", "magnitude", "basis")} for row in signals]
    scored = score_window(current=start, hours=3, vehicle_cost_per_mile=.45, origin_zone="bellevue_core", origin_lat=47.6101, origin_lon=-122.2015,
        include_llm=False, snapshot=ScoringSnapshot(parsed, [], load_anchors(FIXTURES / "anchors.json"), {}))
    return {"available":True, "label":"Recorded real API response", "provider":"WSDOT", "adapter":"wsdot_traffic",
            "captured_at":saved.get("fetched_at"), "excerpt":excerpt, "normalized":normalized,
            "calculation":{"normalizer":"wsdot.parse_alerts", "scorer":"tonight.score_window", "normalized_count":len(parsed), "opportunity_count":len(scored["opportunities"]),
                           "explanation":"Traffic cautions alone do not create a pickup opportunity. This is the same scorer used by the synthetic scenario."},
            "detail":"Public corridor data from an earlier capture, not current traffic. Whitelisted fields only; no URL, credentials, or private coordinates.",
            "external_data_calls":0, "earlier_capture_cost":"unknown"}
