import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from farol.access import AccessMiddleware
from farol.dashboard import FIXTURES, ROOT, brief_view
from farol.field_test import store as field_test_store
from farol.navigation import (
    command_from_opportunity,
    command_from_replay,
    mailbox,
    remember_brief,
    valid_car_token,
)
from farol.product import NAME
from farol.rideedge_api import page
from farol.rideedge_api import router as rideedge_router
from farol.service_lifecycle import WorkThread
from farol.tonight import tonight_brief
from farol.voice_api import router as voice_router

STATIC = ROOT / "farol" / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import asyncio

    from farol import recovery
    from farol.collect import start
    from farol.radar_api import start as start_radar
    from farol.env import load_env
    from farol.model_queue import queue
    from farol.service_lifecycle import drain
    from farol.shift import resume_heartbeat_if_driving

    if not os.getenv("PYTEST_CURRENT_TEST") and os.getenv("MOCK_FEEDS", "") != "1":
        load_env()
    queue.open()
    start()
    start_radar()
    resume_heartbeat_if_driving()
    recovery.start()
    try:
        yield
    finally:
        await asyncio.to_thread(drain, verify_model=not (
            os.getenv("PYTEST_CURRENT_TEST") or os.getenv("MOCK_FEEDS", "") == "1"))


app = FastAPI(title=NAME, version="0.1.0", lifespan=lifespan)
app.add_middleware(AccessMiddleware)

app.include_router(voice_router)
from farol.radar_api import router as radar_router

app.include_router(radar_router)
from farol.studio import router as studio_router

app.include_router(studio_router)


class FieldTestStart(BaseModel):
    driver_zone: str
    vehicle_cost: float = 0.45
    decision_index: int = 0
    odometer_miles: float | None = None
    latitude: float | None = None
    longitude: float | None = None


class DriverChoice(BaseModel):
    action: str


class FieldEvent(BaseModel):
    event_type: str
    note: str = ""


class FieldTestFinish(BaseModel):
    actual_action: str | None = None
    observable: bool | None = None
    odometer_miles: float | None = None


class PresenceSample(BaseModel):
    latitude: float
    longitude: float
    accuracy_meters: float | None = None


class AwarenessLocation(BaseModel):
    latitude: float
    longitude: float


class ShiftOdometerBookmark(BaseModel):
    odometer_miles: float
    note: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    shift_id: str | None = None
    idempotency_key: str | None = None


class ShiftTripEntry(BaseModel):
    gross_fare: float
    miles: float = 0.0
    shift_id: str | None = None
    note: str = ""
    idempotency_key: str | None = None


class DriverOutcomeEntry(BaseModel):
    status: str
    zone: str = ""
    recommended_action: str = ""
    note: str = ""
    idempotency_key: str | None = None
    recommendation_id: str | None = None
    evidence_version: str | None = None
    recorded_at: str | None = None


class CourseRequestBody(BaseModel):
    area: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    pull_all: bool | None = None
    driver_mode: str | None = None
    vehicle_cost: float | None = None
    minutes_available: int | None = None
    reposition_under_minutes: int | None = None
    finish_near: str | None = None


class AnchorApprovalRequest(BaseModel):
    approval_status: str = "approved"
    label: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    safety_notes: str | None = None


class CustomAnchorRequest(BaseModel):
    zone: str = ""
    label: str
    latitude: float
    longitude: float
    action: str = "WAIT"
    approval_status: str = "approved"
    safety_notes: str = "Driver-saved parked spot."


@app.get("/")
def dashboard():
    return page("index.html")


@app.get("/developer")
def developer_tools():
    return page("developer.html")


@app.get("/app.js")
def javascript() -> FileResponse:
    return FileResponse(STATIC / "app.js", media_type="text/javascript")


@app.get("/tonight.js")
def tonight_javascript() -> FileResponse:
    return FileResponse(STATIC / "tonight.js", media_type="text/javascript")


@app.get("/awareness")
def awareness_page():
    return page("awareness.html")


@app.get("/awareness.js")
def awareness_javascript() -> FileResponse:
    return FileResponse(STATIC / "awareness.js", media_type="text/javascript")


@app.get("/api/awareness")
def get_awareness(scope: str = "metro", area: str = "totem_lake", radius: float = 5,
                  period: str = "all", layer: str = "all") -> dict:
    from farol.awareness import awareness_view

    try:
        return awareness_view(scope=scope, area=area, radius=radius, period=period,
                              layer=layer)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/events")
def community_calendar(response: Response, days: int = 14) -> dict:
    from farol.community_events import catalog

    response.headers["Cache-Control"] = "no-store"
    try:
        return catalog(days=days)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/awareness")
def awareness_at_location(location: AwarenessLocation, response: Response, radius: float = 5,
                          period: str = "all", layer: str = "all") -> dict:
    from farol.awareness import awareness_view

    response.headers["Cache-Control"] = "no-store"
    try:
        return awareness_view(scope="nearby", radius=radius, period=period, layer=layer,
                              latitude=location.latitude, longitude=location.longitude)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/styles.css")
def stylesheet() -> FileResponse:
    return FileResponse(STATIC / "styles.css", media_type="text/css")


@app.get("/api/health")
def health() -> dict:
    from farol.brain import _effective_brain
    from farol.collect import feed_health_view
    from farol.collect import status as collector_status
    from farol.grok import model
    from farol.shift import status as shift_status

    kind = _effective_brain()
    narrator = {}
    if kind == "qwen":
        from farol.local_models import profile
        from farol.qwen import status as qwen_status

        narrator = {"provider": "local", "model": os.getenv("FAROL_LOCAL_MODEL") or profile("qwen")["alias"],
                    "cloud_ai_enabled": False, **qwen_status()}
    return {
        "status": "ok",
        "awareness_available": True,
        "mock_feeds": os.getenv("MOCK_FEEDS", "1") == "1",
        "brain": kind,
        "narrator": narrator,
        "grok_configured": bool(os.getenv("XAI_API_KEY")),
        "grok_model": model(),
        "collector": collector_status(),
        "shift": shift_status(),
        "feeds_health": feed_health_view(),
    }


@app.get("/api/feeds/health")
def get_feeds_health(response: Response) -> dict:
    from farol.collect import feed_health_view
    from farol.radar_api import source_participation

    response.headers["Cache-Control"] = "no-store"
    return {**feed_health_view(), "radar_participation": source_participation()}


@app.get("/api/feeds/{adapter}/detail")
def get_feed_detail(adapter: str, response: Response, snapshot_id: str | None = None) -> dict:
    from farol.collect import feed_detail_view
    from farol.radar_api import source_participation

    response.headers["Cache-Control"] = "no-store"
    try:
        detail = feed_detail_view(adapter)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if snapshot_id is not None and snapshot_id.strip():
        current_snapshot_id = detail.get("snapshot_id")
        if current_snapshot_id != snapshot_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "snapshot_changed",
                    "message": (
                        f"Requested snapshot {snapshot_id} is no longer current "
                        f"(latest is {current_snapshot_id})."
                    ),
                    "requested_snapshot_id": snapshot_id,
                    "current_snapshot_id": current_snapshot_id,
                    "latest_detail": detail,
                },
            )
    participation = source_participation()
    detail["radar_participation"] = {**{k: v for k, v in participation.items() if k != "sources"},
        "source": next((row for row in participation["sources"] if row["adapter"] == adapter), None)}
    return detail


_refresh_lock_holder = {"lock": None}


@app.post("/api/feeds/refresh")
def post_feeds_refresh() -> dict:
    import threading

    from farol.collect import feed_health_view, refresh_once
    from farol.radar_api import source_participation

    if _refresh_lock_holder["lock"] is None:
        _refresh_lock_holder["lock"] = threading.Lock()
    lock: threading.Lock = _refresh_lock_holder["lock"]
    if lock.acquire(blocking=False):
        try:
            refresh_once(include_flightaware=False)
        finally:
            lock.release()
    return {**feed_health_view(), "radar_participation": source_participation()}


@app.get("/api/seatac/forecast")
def get_seatac_forecast(response: Response) -> dict:
    from farol.adapters.flightaware import seatac_6h_forecast

    response.headers["Cache-Control"] = "no-store"
    return seatac_6h_forecast(pull=False)


@app.post("/api/seatac/forecast")
def poll_seatac_forecast(response: Response) -> dict:
    from farol.adapters.flightaware import seatac_6h_forecast

    response.headers["Cache-Control"] = "no-store"
    try:
        return seatac_6h_forecast(pull=True)
    except Exception as error:
        raise HTTPException(status_code=400, detail="SeaTac report could not refresh; check provider configuration and source status.") from error


@app.post("/api/besttime/poll")
def post_besttime_poll(area: str = "Bellevue", max_venues: int = 5, force_live: bool = False) -> dict:
    from farol.besttime_live import poll_besttime_venues

    try:
        return poll_besttime_venues(area=area, max_venues=max_venues, force_live=force_live)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/ask/course")
def get_shift_course(
    area: str = "Bellevue",
    latitude: float | None = None,
    longitude: float | None = None,
    driver_mode: str = "active_working",
    vehicle_cost: float = 0.45,
    minutes_available: int | None = None,
    reposition_under_minutes: int | None = None,
    finish_near: str | None = None,
) -> dict:
    from farol.course import build_6h_shift_course

    try:
        return build_6h_shift_course(
            origin_area=area,
            latitude=latitude,
            longitude=longitude,
            pull_all=False,
            vehicle_cost=vehicle_cost,
            driver_mode=driver_mode,
            minutes_available=minutes_available,
            reposition_under_minutes=reposition_under_minutes,
            finish_near=finish_near,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/ask/course")
def post_shift_course(
    area: str = "Bellevue",
    latitude: float | None = None,
    longitude: float | None = None,
    pull_all: bool = True,
    driver_mode: str = "active_working",
    vehicle_cost: float = 0.45,
    minutes_available: int | None = None,
    reposition_under_minutes: int | None = None,
    finish_near: str | None = None,
    body: CourseRequestBody | None = None,
) -> dict:
    from farol.course import build_6h_shift_course

    eff_area = (body.area if body and body.area else area) or "Bellevue"
    eff_lat = body.latitude if (body and body.latitude is not None) else latitude
    eff_lon = body.longitude if (body and body.longitude is not None) else longitude
    eff_pull = body.pull_all if (body and body.pull_all is not None) else pull_all
    eff_mode = (body.driver_mode if (body and body.driver_mode) else driver_mode) or "active_working"
    eff_cost = float(body.vehicle_cost if (body and body.vehicle_cost is not None) else vehicle_cost)
    eff_mins = (
        body.minutes_available
        if (body and body.minutes_available is not None)
        else minutes_available
    )
    eff_repo = (
        body.reposition_under_minutes
        if (body and body.reposition_under_minutes is not None)
        else reposition_under_minutes
    )
    eff_finish = (
        body.finish_near
        if (body and body.finish_near is not None)
        else finish_near
    )
    try:
        return build_6h_shift_course(
            origin_area=eff_area,
            latitude=eff_lat,
            longitude=eff_lon,
            pull_all=eff_pull,
            vehicle_cost=eff_cost,
            driver_mode=eff_mode,
            minutes_available=eff_mins,
            reposition_under_minutes=eff_repo,
            finish_near=eff_finish,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/brief")
def brief(vehicle_cost: float = 0.45, decision: int | None = None) -> dict:
    if vehicle_cost <= 0:
        raise HTTPException(status_code=400, detail="vehicle_cost must be positive")
    try:
        return brief_view(vehicle_cost, decision)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/history")
def history(vehicle_cost: float = 0.45) -> dict:
    from farol.history import summarize_history
    from farol.trips import load_observed_trips

    if not 0 < vehicle_cost < 10:
        raise HTTPException(status_code=400, detail="vehicle_cost must be between 0 and 10")
    return summarize_history(load_observed_trips(), vehicle_cost)


@app.get("/api/history/shifts")
def list_shift_bookmarks() -> dict:
    from farol.history import active_shift_log, read_driver_outcomes, read_shift_logs

    return {
        "active": active_shift_log(),
        "shifts": read_shift_logs(),
        "outcomes": read_driver_outcomes(limit=25),
    }


@app.post("/api/history/shifts/start")
def start_shift_bookmark(request: ShiftOdometerBookmark) -> dict:
    from farol.history import start_shift_log

    try:
        return start_shift_log(
            request.odometer_miles,
            started_at=request.started_at,
            note=request.note,
            idempotency_key=request.idempotency_key,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/history/shifts/end")
def end_shift_bookmark(request: ShiftOdometerBookmark) -> dict:
    from farol.history import end_shift_log

    try:
        return end_shift_log(
            request.odometer_miles,
            shift_id=request.shift_id,
            ended_at=request.ended_at,
            note=request.note,
            idempotency_key=request.idempotency_key,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/history/shifts/trip")
def log_shift_trip_endpoint(request: ShiftTripEntry) -> dict:
    from farol.history import log_shift_trip

    try:
        return log_shift_trip(
            request.gross_fare,
            request.miles,
            shift_id=request.shift_id,
            note=request.note,
            idempotency_key=request.idempotency_key,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/history/outcomes")
def post_driver_outcome(request: DriverOutcomeEntry) -> dict:
    from farol.history import log_driver_outcome

    try:
        return log_driver_outcome(
            status=request.status,
            zone=request.zone,
            recommended_action=request.recommended_action,
            note=request.note,
            idempotency_key=request.idempotency_key,
            recommendation_id=request.recommendation_id,
            evidence_version=request.evidence_version,
            recorded_at=request.recorded_at,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/history/outcomes")
def get_driver_outcomes(limit: int = 25) -> dict:
    from farol.history import read_driver_outcomes, summarize_zone_outcomes

    return {
        "outcomes": read_driver_outcomes(limit=max(1, min(limit, 200))),
        "zone_summaries": summarize_zone_outcomes(),
    }


@app.get("/api/here")
def get_here(
    at: str,
    vehicle_cost: float = 0.45,
    value_of_time: float = 25.0,
    text: int = 0,
    driver_mode: str = "active_working",
    max_reposition_minutes: float = 20.0,
):
    from farol.here import advise

    if not at.strip():
        raise HTTPException(status_code=400, detail="at is required")
    if vehicle_cost <= 0 or value_of_time <= 0:
        raise HTTPException(status_code=400, detail="cost and value of time must be positive")
    try:
        payload = advise(
            at,
            value_of_time_per_hour=value_of_time,
            vehicle_cost_per_mile=vehicle_cost,
            driver_mode=driver_mode,
            max_reposition_minutes=max_reposition_minutes,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if text:
        return PlainTextResponse(payload["card"])
    return payload


@app.post("/api/here")
def here_at_location(
    location: AwarenessLocation,
    response: Response,
    vehicle_cost: float = 0.45,
    value_of_time: float = 25.0,
    driver_mode: str = "active_working",
    max_reposition_minutes: float = 20.0,
):
    # Device coordinates belong in the body, not the URL/access log.
    response.headers["Cache-Control"] = "no-store"
    payload = get_here(
        f"{location.latitude:.6f}, {location.longitude:.6f}",
        vehicle_cost,
        value_of_time,
        driver_mode=driver_mode,
        max_reposition_minutes=max_reposition_minutes,
    )
    payload["query"] = "Device location"
    payload["place"]["matched"] = "device location"
    return payload


@app.get("/api/shift")
def get_shift() -> dict:
    from farol.shift import status as shift_status

    return shift_status()


@app.post("/api/shift/start")
def start_shift(model: str | None = None) -> dict:
    from farol.grok import brain_name
    from farol.local_models import profile
    from farol.shift import start as start_driving
    from farol.shift import status as shift_status

    current = shift_status()
    if current.get("phase") in {"driving", "acquiring"}:
        return current
    try:
        if brain_name() == "qwen" and model not in {None, "qwen"}:
            raise ValueError("Farol is configured for Qwen-only AI")
        if brain_name() == "qwen":
            model = "qwen"
        selected = profile(model)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    WorkThread(
        target=start_driving,
        kwargs={"owner_pid": os.getpid(), "model_profile": selected["id"]},
        daemon=True,
    ).start()
    return {
        "ok": True,
        "phase": "acquiring",
        "detail": f"Requesting the GPU lease and loading {selected['label']}.",
    }


@app.post("/api/shift/stop")
def stop_shift() -> dict:
    from farol.shift import status as shift_status
    from farol.shift import stop as stop_driving

    current = shift_status()
    if current.get("phase") == "idle":
        return current
    WorkThread(target=stop_driving, daemon=True).start()
    return {
        "ok": True,
        "phase": "restoring",
        "detail": "Shift ending. Unloading the local narrator and restoring Cydonia/Companion.",
    }


@app.get("/api/tonight")
def get_tonight_brief(
    hours: float = 6,
    vehicle_cost: float = 0.45,
    value_of_time: float = 22.0,
) -> dict:
    if not 1 <= hours <= 12:
        raise HTTPException(status_code=400, detail="hours must be between 1 and 12")
    if vehicle_cost <= 0 or value_of_time <= 0:
        raise HTTPException(status_code=400, detail="cost and value of time must be positive")
    brief = tonight_brief(
        hours=hours,
        vehicle_cost_per_mile=vehicle_cost,
        value_of_time_per_hour=value_of_time,
    )
    remember_brief(brief)
    return brief


@app.get("/api/replay/friday")
def friday_replay() -> FileResponse:
    return FileResponse(FIXTURES / "friday_debrief.json", media_type="application/json")


@app.post("/api/field-tests")
def start_field_test(request: FieldTestStart) -> dict:
    try:
        return field_test_store.start(
            driver_zone=request.driver_zone,
            vehicle_cost=request.vehicle_cost,
            decision_index=request.decision_index,
            odometer_miles=request.odometer_miles,
            latitude=request.latitude,
            longitude=request.longitude,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/field-tests/{session_id}/choice")
def record_driver_choice(session_id: str, request: DriverChoice) -> dict:
    try:
        return field_test_store.choose(session_id, request.action)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/field-tests/{session_id}/events")
def record_field_event(session_id: str, request: FieldEvent) -> dict:
    try:
        return field_test_store.add_event(session_id, request.event_type, request.note)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/field-tests/{session_id}/presence")
def record_presence(session_id: str, request: PresenceSample) -> dict:
    try:
        return field_test_store.add_presence(
            session_id,
            latitude=request.latitude,
            longitude=request.longitude,
            accuracy_meters=request.accuracy_meters,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/field-tests/{session_id}/finish")
def finish_field_test(session_id: str, request: FieldTestFinish) -> dict:
    try:
        return field_test_store.finish(
            session_id,
            actual_action=request.actual_action,
            observable=request.observable,
            odometer_miles=request.odometer_miles,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/anchors")
def list_anchors() -> dict:
    from farol.signals import load_anchors, public_record

    anchors = load_anchors(FIXTURES / "anchors.json")
    return {"anchors": [public_record(item) for item in anchors]}


@app.post("/api/anchors/custom")
def create_custom_anchor(request: CustomAnchorRequest, response: Response) -> dict:
    from farol.here import resolve
    from farol.signals import public_record, save_custom_anchor

    response.headers["Cache-Control"] = "no-store"
    try:
        zone = request.zone.strip()
        if not zone:
            zone = resolve(f"{request.latitude:.6f}, {request.longitude:.6f}")["zone"]
        created = save_custom_anchor(
            zone=zone,
            label=request.label,
            latitude=request.latitude,
            longitude=request.longitude,
            action=request.action,
            approval_status=request.approval_status,  # type: ignore[arg-type]
            safety_notes=request.safety_notes,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return public_record(created)


@app.post("/api/anchors/{anchor_id}/approve")
def approve_anchor(anchor_id: str, request: AnchorApprovalRequest, response: Response) -> dict:
    from farol.signals import public_record, save_anchor_override

    response.headers["Cache-Control"] = "no-store"
    try:
        updated = save_anchor_override(
            anchor_id,
            approval_status=request.approval_status,  # type: ignore[arg-type]
            label=request.label,
            latitude=request.latitude,
            longitude=request.longitude,
            safety_notes=request.safety_notes,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return public_record(updated)


@app.post("/api/navigation/demo")
def publish_demo_navigation(vehicle_cost: float = 0.45, decision: int = 9) -> dict:
    try:
        command = command_from_replay(vehicle_cost, decision)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    mailbox.publish(command)
    return command.public()


@app.post("/api/navigation/opportunity/{opportunity_id}")
def publish_opportunity_navigation(opportunity_id: str, vehicle_cost: float = 0.45) -> dict:
    try:
        command = command_from_opportunity(opportunity_id, vehicle_cost)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    mailbox.publish(command)
    return command.public()


@app.get("/api/navigation/current", response_model=None)
def current_navigation(x_farol_car_token: str | None = Header(default=None)) -> dict | Response:
    if not valid_car_token(x_farol_car_token):
        raise HTTPException(status_code=401, detail="invalid car pairing token")
    command = mailbox.current()
    if command is None:
        return Response(status_code=204)
    return command.public()


app.include_router(rideedge_router)


def main() -> None:
    from farol.env import load_env
    from farol.service_control import serve

    load_env()
    serve()


if __name__ == "__main__":
    main()
