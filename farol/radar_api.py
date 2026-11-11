"""Single-driver, in-memory radar session and bounded 15-minute local AI refresh."""
from __future__ import annotations

import copy
import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from farol import radar, decision_policy
from farol.radar_contract import RadarView, project
from farol.service_lifecycle import WorkThread

router = APIRouter(prefix="/api/radar")
_lock = threading.RLock()
_wake = threading.Event()
_stop = threading.Event()
_thread = None
_context = None
_view = None
_generation = 0
_last_touch = 0.0
_next_run = 0.0
_last_provider_pull = 0.0
_refreshing = False
_heartbeat_at = None
_snapshots = {}
_ask_jobs = {}
SESSION_SECONDS = 6 * 3600


def _clear_session_locked():
    """Invalidate late workers; their own finally blocks still release resources."""
    global _context, _view, _generation, _last_touch, _next_run
    _generation += 1
    _context = _view = None
    _last_touch = _next_run = 0.0
    _snapshots.clear()
    _ask_jobs.clear()


def prune_private_state():
    """Bound retained origin/question data without extending a session on reads."""
    now = datetime.now(UTC)
    expired = False
    with _lock:
        if _context is not None and time.monotonic() - _last_touch > SESSION_SECONDS:
            _clear_session_locked()
            expired = True
        for key, snapshot in list(_snapshots.items()):
            if not radar.fresh(snapshot.get("generated_at"), now, 20):
                _snapshots.pop(key, None)
        for key, job in list(_ask_jobs.items()):
            if job.get("answer") and not radar.fresh(job["answer"].get("generated_at"), now, 20):
                _ask_jobs.pop(key, None)
    if expired:
        from farol.adapters.routes import clear_private_cache
        clear_private_cache()


class ContextRequest(BaseModel):
    area: str = Field(default="Home", max_length=120)
    latitude: float | None = None
    longitude: float | None = None
    fix_at: str | None = None
    accuracy_meters: float | None = None


class AskRequest(BaseModel):
    snapshot_id: str = Field(max_length=40)
    question: str = Field(min_length=1, max_length=700)


def _start_ask_work(work):
    WorkThread(target=work, name="rideedge-radar-question", daemon=True).start()


def read_inputs():
    from farol.adapters.base import cache_dir
    from farol.besttime_live import _active_dir, _read_json

    return (_read_json(cache_dir()/"awareness_snapshot.json") or {},
            _read_json(_active_dir()/"report.json") or {})


def source_participation():
    from farol.radar_sources import participation

    prune_private_state()
    with _lock:
        view = copy.deepcopy(_view) if _view and _view.get("context_generation", _generation) == _generation else None
        if view and _context:
            view["origin"] = copy.deepcopy(_context)
    return participation(view, datetime.now(UTC))


@router.get("/status")
def service_status(response: Response):
    import json
    from urllib.request import urlopen

    from farol import collect, local_runtime, shift
    from farol.model_queue import queue

    response.headers["Cache-Control"] = "no-store"
    prune_private_state()
    loaded = []
    reachable = False
    try:
        endpoint, alias = local_runtime.settings()
        with urlopen(endpoint.rsplit("/chat/completions", 1)[0]+"/models", timeout=3) as result:
            loaded = [row.get("id") for row in json.load(result).get("data", [])]
        reachable = True
    except Exception:  # noqa: BLE001 — health must survive a stopped model server
        alias = "Qwen"
    with _lock:
        last = copy.deepcopy((_view or {}).get("qwen"))
        generated = (_view or {}).get("generated_at")
        refreshing = _refreshing
    return {"backend": "ready", "collector": collect.status(), "model_server_reachable": reachable,
            "qwen_loaded": alias in loaded, "loaded_models": loaded, "qwen": last,
            "evidence_generated_at": generated, "refreshing": refreshing, "gpu_phase": shift.status().get("phase"),
            "cleanup": local_runtime.cleanup_status(),
            "model_queue": queue.status(),
            "model_control": shift.control_status(),
            "model_note": "Qwen loads on demand through the GPU coordinator and restores the previous model after a request."}


def _remember(view):
    now = datetime.now(UTC)
    for key, snapshot in list(_snapshots.items()):
        if not radar.fresh(snapshot.get("generated_at"), now, 20):
            _snapshots.pop(key, None)
    view["context_generation"] = _generation
    _snapshots[view["snapshot_id"]] = copy.deepcopy(view)
    while len(_snapshots) > 12:
        _snapshots.pop(next(iter(_snapshots)))


def _public(view, *, preview=False):
    from farol.local_runtime import cleanup_status

    now = datetime.now(UTC)
    out = project(view, now)
    cleanup = cleanup_status()
    if cleanup:
        out.setdefault("runtime", {})["cleanup"] = cleanup
    out["refreshing"] = _refreshing and not preview
    remaining_session = max(0, SESSION_SECONDS - (time.monotonic() - _last_touch))
    state = ("preview" if preview else "no_session" if _context is None else
             "expired" if not remaining_session else "reviewing" if _refreshing else
             "blocked" if cleanup.get("state") == "restoration_failed" else "scheduled")
    next_review = ((now + timedelta(seconds=max(0, _next_run-time.monotonic()))).isoformat()
                   if state == "scheduled" else None)
    out["scheduler"] = {"state": state, "next_review_at": next_review,
                        "session_expires_at": (now + timedelta(seconds=remaining_session)).isoformat()
                        if not preview and _context is not None else None}
    out["next_refresh_at"] = next_review
    out["location_note"] = (
        "Location is old. Update your location for Now; Plan is based on your last reported position."
        if out["location_stale"] else "Current location only; no trip trace is recorded."
        if out["origin"]["mode"] == "device" else "Planning from your selected area.")
    return out


def _validated_context(body):
    ctx = radar.origin(body.area, body.latitude, body.longitude)
    if ctx["mode"] == "device":
        if not radar.fresh(body.fix_at, datetime.now(UTC), 5):
            raise ValueError("Request a fresh phone location")
        if not radar.number(body.accuracy_meters) or not 0 <= body.accuracy_meters <= 200:
            raise ValueError("Phone location is too approximate; select an area instead")
        ctx.update(fix_at=body.fix_at, accuracy_meters=body.accuracy_meters)
    return ctx


@router.post("/context", response_model=RadarView)
def set_context(body: ContextRequest, response: Response):
    global _context, _view, _generation, _last_touch, _next_run
    response.headers["Cache-Control"] = "no-store"
    try:
        ctx = _validated_context(body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    prune_private_state()
    with _lock:
        changed = (_context is None or ctx["mode"] != _context["mode"] or
                   radar.distance(ctx["latitude"], ctx["longitude"], _context["latitude"], _context["longitude"]) > .25)
        _last_touch = time.monotonic()
        _context = ctx
        if changed or _view is None:
            _generation += 1
            _snapshots.clear()
            _ask_jobs.clear()
            snap, bt = read_inputs()
            _view = radar.build(ctx, snap, bt)
            _remember(_view)
            _next_run = 0
            _wake.set()
        else:
            _view["origin"] = ctx
        result = _public(_view)
    start()
    return result


@router.get("", response_model=RadarView)
def get_radar(response: Response):
    response.headers["Cache-Control"] = "no-store"
    prune_private_state()
    with _lock:
        if _view is None:
            raise HTTPException(409, "Choose a location first")
        return _public(_view)


@router.post("/preview", response_model=RadarView)
def preview(body: ContextRequest, response: Response):
    """Exploring Nearby never changes the driver's active location or background plan."""
    response.headers["Cache-Control"] = "no-store"
    try:
        ctx = _validated_context(body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    snap, bt = read_inputs()
    result = radar.build(ctx, snap, bt)
    result["qwen"] = {"state": "preview", "detail": "Exploring this area; your Now location is unchanged."}
    return _public(result, preview=True)


@router.post("/refresh")
def refresh():
    global _next_run
    prune_private_state()
    with _lock:
        if _context is None:
            raise HTTPException(409, "Choose a location first")
        # Repeated refresh taps do not create parallel workers or provider bursts.
        if not _refreshing:
            _next_run = 0
            _wake.set()
    start()
    return {"queued": True}


@router.post("/ask")
def ask(body: AskRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    prune_private_state()
    with _lock:
        view = copy.deepcopy(_snapshots.get(body.snapshot_id))
        generation = (view or {}).get("context_generation", _generation)
        if generation != _generation:
            raise HTTPException(409, "Your location changed; ask from the current view")
        if view is not None and _context is not None:
            # A newer fix within the same location generation is not a new
            # candidate snapshot, but its age and origin govern this request.
            view["origin"] = copy.deepcopy(_context)
    if view is None or not radar.fresh(view["generated_at"], datetime.now(UTC), 15):
        raise HTTPException(409, "Refresh the activity evidence before asking Qwen")
    if _public(view)["evidence_stale"]:
        raise HTTPException(409, "This opportunity has expired; refresh before asking Qwen")
    if view["origin"]["mode"] == "device" and not radar.fresh(view["origin"].get("fix_at"), datetime.now(UTC), 5):
        raise HTTPException(409, "Update your phone location before asking Qwen")
    prune_private_state()
    with _lock:
        if generation != _generation:
            raise HTTPException(409, "Your session changed; refresh before asking Qwen")
        if any(job["state"] == "running" for job in _ask_jobs.values()):
            raise HTTPException(409, "Qwen is still answering the previous question")
        job_id = uuid.uuid4().hex
        _ask_jobs[job_id] = {"state": "running", "job_id": job_id}
        while len(_ask_jobs) > 4:
            _ask_jobs.pop(next(iter(_ask_jobs)))

    def work():
        def current():
            prune_private_state()
            with _lock:
                if generation != _generation or not radar.fresh(view["generated_at"], datetime.now(UTC), 15):
                    return False
                check = copy.deepcopy(view)
                if _context is not None:
                    check["origin"] = copy.deepcopy(_context)
                public = _public(check)
                return not public["location_stale"] and not public["evidence_stale"]
        try:
            answer = radar.ask_model(view, body.question, valid=current, job_kind="radar-question")
            if not current():
                raise ValueError("Location or evidence changed during the question")
            answer["question"] = body.question
            with _lock:
                if _context is not None:
                    answer["origin"] = copy.deepcopy(_context)
            result = {"state": "ready", "job_id": job_id, "answer": answer, "context_generation": generation}
        except Exception:  # noqa: BLE001 — source-ranked options survive model failures
            result = {"state": "failed", "job_id": job_id,
                      "detail": "Local Qwen is unavailable or returned an unsupported choice. Activity options remain available."}
        prune_private_state()
        with _lock:
            if generation == _generation and job_id in _ask_jobs:
                _ask_jobs[job_id] = result

    _start_ask_work(work)
    response.status_code = 202
    return {"state": "running", "job_id": job_id}


@router.get("/ask/jobs/{job_id}")
def ask_job(job_id: str, response: Response):
    response.headers["Cache-Control"] = "no-store"
    prune_private_state()
    with _lock:
        result = copy.deepcopy(_ask_jobs.get(job_id))
    if result is None:
        raise HTTPException(404, "Question not found; ask again")
    if result.get("context_generation", _generation) != _generation:
        return {"state": "failed", "job_id": job_id, "detail": "Your location changed; ask from the current view."}
    if result.get("answer"):
        result["answer"] = _public(result["answer"])
    return result


def _routes(view):
    from farol.adapters.routes import SOURCE, matrix
    from farol.signals import Anchor

    selected = [*view["nearby"][:8], *view["further"][:4]]
    anchors = [Anchor(r["id"], r["zone"], r["name"], r["latitude"], r["longitude"],
                      "WATCH", "pending", "Area reference only") for r in selected]
    ctx = view["origin"]
    estimates, _ = matrix(ctx["zone"], ctx["latitude"], ctx["longitude"], anchors, .45, view["generated_at"])
    return {key: {"minutes": r.traffic_minutes, "miles": r.distance_miles,
                  "basis": "live traffic", "fetched_at": r.fetched_at, "source": SOURCE}
            for key, r in estimates.items() if r.basis == "live"}


def run_once():
    global _view, _refreshing, _next_run, _last_provider_pull
    prune_private_state()
    with _lock:
        if _context is None or _refreshing or time.monotonic()-_last_touch > SESSION_SECONDS:
            return
        ctx, generation = copy.deepcopy(_context), _generation
        previous = copy.deepcopy(_view)
        _refreshing = True
    errors = []
    try:
        # Collector already refreshes all configured non-cloud sources. Reuse TTLs;
        # venue polling adds bounded area-wide radar and at most eight venue checks.
        if time.monotonic()-_last_provider_pull >= 15*60:
            _last_provider_pull = time.monotonic()
            from farol.besttime_live import poll_besttime_venues
            from farol.collect import refresh_once, status

            if not radar.fresh(status().get("last_run_at"), datetime.now(UTC), 15):
                try:
                    refresh_once()
                except Exception:  # noqa: BLE001 — isolate independent source failures
                    errors.append("Some shared feeds could not refresh")
            try:
                poll_besttime_venues(ctx["zone"], max_venues=8, force_live=False)
            except Exception:  # noqa: BLE001 — saved evidence remains usable
                errors.append("BestTime refresh unavailable; checking saved readings")
        snap, bt = read_inputs()
        view = radar.build(ctx, snap, bt)
        try:
            routes = _routes(view)
            view = radar.build(ctx, snap, bt, routes=routes)
        except Exception:  # noqa: BLE001 — routes may fall back to labeled estimates
            errors.append("Traffic routes unavailable; travel times are estimates")
        prune_private_state()
        with _lock:
            if generation != _generation:
                return
            _view = view
            _remember(view)
        try:
            def current():
                prune_private_state()
                with _lock:
                    return generation == _generation and radar.fresh(view["generated_at"], datetime.now(UTC), 20)
            view = radar.ask_model(view, valid=current)
        except Exception as error:  # noqa: BLE001 — never replace evidence with unvalidated AI output
            from farol.local_runtime import failure_status
            view["qwen"] = failure_status(error)
            if view.get("decision_audit"):
                view["decision_audit"]["validation"] = "model_rejected_or_unavailable_algorithm_retained"
        if view.get("decision_policy"):
            from farol.decision_engine import stabilize
            view = stabilize(view, previous, decision_policy.load())
        view["refresh_notes"] = errors
        prune_private_state()
        with _lock:
            if generation == _generation:
                # Preserve the latest fix timestamp without replacing a newer position.
                view["origin"] = copy.deepcopy(_context)
                _view = view
                _remember(view)
    finally:
        with _lock:
            _refreshing = False
            if generation == _generation:
                _next_run = time.monotonic()+decision_policy.interval_seconds()


def _loop():
    global _next_run, _heartbeat_at
    while not _stop.is_set():
        with _lock:
            _heartbeat_at = datetime.now(UTC).isoformat()
        prune_private_state()
        from farol.adapters.routes import expire_private_cache
        expire_private_cache()
        with _lock:
            due = _context is not None and time.monotonic() >= _next_run and time.monotonic()-_last_touch <= SESSION_SECONDS
        if due:
            try:
                run_once()
            except Exception:  # noqa: BLE001 — keep the bounded background worker alive
                # Do not spin or destroy the last inspectable snapshot on a bad provider row.
                with _lock:
                    _next_run = time.monotonic()+decision_policy.interval_seconds()
        _wake.wait(15)
        _wake.clear()


def start():
    global _thread
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("MOCK_FEEDS", "1") == "1":
        return
    with _lock:
        if _thread is None or not _thread.is_alive():
            _stop.clear()
            _thread = threading.Thread(target=_loop, name="rideedge-radar", daemon=True)
            _thread.start()


def stop():
    from farol.adapters.routes import clear_private_cache
    _stop.set()
    _wake.set()
    with _lock:
        _clear_session_locked()
    clear_private_cache()
