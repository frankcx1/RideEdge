"""Read-only infrastructure observations. No collection, inference or GPU leases."""
from __future__ import annotations

import copy
import csv
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError
from urllib.request import urlopen

STARTED_AT = datetime.now(UTC).isoformat()
_started = time.monotonic()
_probe_lock = threading.Lock()
_probe_cache = None
_probe_at = 0.0


def probe_model():
    from farol.local_runtime import settings
    result = {"state": "unavailable", "reachable": False, "loaded": False, "loaded_models": [],
              "checked_at": datetime.now(UTC).isoformat()}
    try:
        endpoint, alias = settings()
        base = endpoint.rsplit("/v1/chat/completions", 1)[0]
        with urlopen(base + "/v1/models", timeout=1.5) as response:
            rows = json.loads(response.read(65536)).get("data", [])
        loaded = [r["id"][:160] for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)]
        result.update(reachable=True, loaded_models=loaded)
        if alias not in loaded:
            result["state"] = "different_model"
        else:
            try:
                with urlopen(base + "/health", timeout=1.5) as response:
                    ready = response.status == 200
                result.update(state="ready" if ready else "loading", loaded=ready)
            except HTTPError as error:
                result["state"] = "loading" if error.code == 503 else "reported_unverified"
            except (OSError, ValueError):
                result["state"] = "reported_unverified"
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
        pass
    return result


def probe_gpus():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {"state": "unavailable", "devices": []}
    try:
        result = subprocess.run([exe, "--query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                                 "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=2,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
        devices = []
        for row in csv.reader(result.stdout.splitlines()):
            index, name, used, total, utilization, temperature = [s.strip() for s in row]
            def number(value):
                try:
                    return float(value)
                except ValueError:
                    return None
            devices.append({"index": index, "name": name, "memory_used_mb": number(used),
                            "memory_total_mb": number(total), "utilization_percent": number(utilization),
                            "temperature_c": number(temperature)})
        return {"state": "observed", "devices": devices, "checked_at": datetime.now(UTC).isoformat()}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"state": "unavailable", "devices": []}


def probes():
    global _probe_cache, _probe_at
    with _probe_lock:
        if _probe_cache is None or time.monotonic() - _probe_at >= 15:
            _probe_cache = {"model": probe_model(), "hardware": probe_gpus()}
            _probe_at = time.monotonic()
        return copy.deepcopy(_probe_cache)


def snapshot():
    from farol import collect, local_runtime, radar_api, shift
    from farol.local_models import profile
    from farol.model_queue import queue
    from farol.model_metrics import snapshot as performance

    now, mono = datetime.now(UTC), time.monotonic()
    cleanup = local_runtime.cleanup_status()
    with radar_api._lock:
        has_context = radar_api._context is not None
        remaining = max(0, radar_api.SESSION_SECONDS - (mono - radar_api._last_touch)) if has_context else 0
        alive = bool(radar_api._thread and radar_api._thread.is_alive() and not radar_api._stop.is_set())
        state = ("stopped" if not alive else "waiting_for_context" if not has_context else
                 "session_expired" if not remaining else "reviewing" if radar_api._refreshing else
                 "blocked" if cleanup.get("state") == "restoration_failed" else "scheduled")
        view = radar_api._view or {}
        review = view.get("qwen") or {}
        scheduler = {"state": state, "worker_alive": alive, "heartbeat_at": radar_api._heartbeat_at,
                     "check_seconds": 15, "review_interval_seconds": radar_api.decision_policy.interval_seconds(),
                     "next_review_at": (now + timedelta(seconds=max(0, radar_api._next_run - mono))).isoformat()
                     if state == "scheduled" else None,
                     "session_expires_at": (now + timedelta(seconds=remaining)).isoformat() if has_context else None,
                     "last_evidence_at": view.get("generated_at"), "last_review_state": review.get("state", "none"),
                     "last_review_code": review.get("code"),
                     "timings": {k: v for k, v in ((view.get("runtime") or {}).get("timings") or {}).items()
                                 if k in {"acquire_seconds", "work_seconds", "cleanup_seconds"} and isinstance(v, (float, int))}}
    collector = collect.status()
    collector["worker_alive"] = bool(collect._thread and collect._thread.is_alive() and not collect._stop.is_set())
    collector["configured_interval_seconds"] = collect.interval_seconds()
    observed = probes()
    configured = profile("qwen")
    lease = shift.status()
    return {"backend": {"state": "ready", "started_at": STARTED_AT, "uptime_seconds": round(mono - _started)},
            "model": {**observed["model"], "configured": configured["label"], "alias": configured["alias"],
                      "context_size": configured["context_size"], "management": os.getenv("FAROL_LOCAL_MANAGE", "ondemand")},
            "hardware": observed["hardware"], "performance": performance(), "scheduler": scheduler, "collector": collector,
            "queue": queue.status(), "gpu": {"phase": lease.get("phase", "unknown"),
                "lease_heartbeat_seconds": 60,
                "lease_heartbeat_active": bool(shift._hb_thread and shift._hb_thread.is_alive() and not shift._hb_stop.is_set()),
                "cleanup_state": cleanup.get("state", "none")},
            "telemetry_scope": "Current backend process only; counters reset on restart. Model job completion is separate from answer validation."}
