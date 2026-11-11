"""Coordinate a short Qwen request without taking another application's GPU lease."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from farol.adapters.base import FeedError
from farol.local_models import profile

LEASE_SCRIPT = Path("C:/ProgramData/gpu-lease/gpulease.ps1")
_status_lock = threading.Lock()
_last_cleanup: dict = {}


@dataclass
class SessionOutcome:
    """Resource result, independent of whether the caller validates the model text."""

    inference_state: str = "not_started"
    release_result: dict = field(default_factory=lambda: {"state": "not_required"})
    timings: dict = field(default_factory=dict)

    def public(self) -> dict:
        return {"inference_state": self.inference_state,
                "cleanup": dict(self.release_result), "timings": dict(self.timings)}


def cleanup_status() -> dict:
    with _status_lock:
        return dict(_last_cleanup)


def _record_cleanup(result: dict):
    global _last_cleanup
    with _status_lock:
        _last_cleanup = dict(result)


def failure_status(error: Exception) -> dict:
    from farol.model_queue import ObsoleteRequest, QueueBusy
    from farol.prompt_budget import PromptBudgetExceeded, PromptBudgetUnavailable
    from farol.decision_engine import DecisionValidationError

    if isinstance(error, DecisionValidationError):
        return {"state": "rejected", "code": "decision_validation_failed",
                "detail": f"Qwen response rejected: {error.safe_detail}. Showing the deterministic result."}

    if isinstance(error, (PromptBudgetExceeded, PromptBudgetUnavailable)):
        return {"state": "blocked", "code": error.code, "detail": str(error)}
    if isinstance(error, (QueueBusy, ObsoleteRequest)):
        return {"state": "blocked", "code": error.code, "detail": str(error)}
    if isinstance(error, RestorationBlocked):
        return {"state": "blocked", "code": "restoration_failed",
                "detail": "GPU restoration needs attention. Evidence ranking remains available; new AI reviews are blocked."}
    if isinstance(error, ModelBusy):
        return {"state": "blocked", "code": "gpu_busy",
                "detail": "The GPU coordinator has reserved the model resources. Evidence ranking remains available."}
    return {"state": "unavailable", "code": "model_request_failed",
            "detail": "Local Qwen unavailable. Showing evidence ranking; no AI selection was applied."}


class ModelBusy(FeedError):
    """Another workload owns the GPU. Do not reclaim or stop it."""


class RestorationBlocked(ModelBusy):
    """Coordinator recovery has not completed; no new acquisition is permitted."""


def settings() -> tuple[str, str]:
    from farol.local import local_url

    endpoint = local_url()
    parsed = urlsplit(endpoint)
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or not parsed.path.rstrip("/").endswith("/v1/chat/completions")
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise FeedError("Qwen requires a loopback /v1/chat/completions endpoint")
    alias = os.getenv("FAROL_LOCAL_MODEL", "").strip() or profile("qwen")["alias"]
    if "qwen" not in alias.casefold():
        raise FeedError("Qwen-only mode requires a Qwen model alias")
    return endpoint.rstrip("/"), alias


def model_ready(endpoint: str, alias: str) -> bool:
    """llama-server may ignore request model names: verify the loaded model first."""
    try:
        with urlopen(endpoint.rsplit("/chat/completions", 1)[0] + "/models", timeout=3) as response:
            payload = json.loads(response.read())
    except (URLError, OSError, ValueError) as error:
        raise FeedError("Local Qwen server is unavailable") from error
    return alias in {row.get("id") for row in payload.get("data", []) if isinstance(row, dict)}


def lease_status() -> dict:
    if os.getenv("PYTEST_CURRENT_TEST"):
        raise FeedError("Live GPU management is disabled under tests")
    if not LEASE_SCRIPT.is_file():
        raise FeedError("GPU lease coordinator unavailable; use an existing Qwen server")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-File", str(LEASE_SCRIPT), "status"],
                                capture_output=True, text=True, timeout=15, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        payload = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise FeedError("Cannot verify GPU ownership; no model was changed") from error
    if not payload.get("ok"):
        raise FeedError("Cannot verify GPU ownership; no model was changed")
    return payload


@contextmanager
def session(endpoint: str, alias: str, *, job_kind="local-qwen", valid=None):
    from farol import shift
    from farol.model_queue import ObsoleteRequest, queue

    mode = os.getenv("FAROL_LOCAL_MANAGE", "ondemand").strip().lower()
    if mode not in {"ondemand", "external"}:
        raise FeedError("FAROL_LOCAL_MANAGE must be ondemand or external")
    outcome = SessionOutcome()
    with queue.admit(job_kind, valid), shift.model_lock:
        if valid is not None and not valid():
            raise ObsoleteRequest("Location or evidence changed while waiting for model coordination")
        if mode == "external":
            # Explicit sharing: no process, lease, or model-lifecycle mutations.
            if not model_ready(endpoint, alias):
                raise FeedError("The local server is running a different model; waiting for Qwen")
            outcome.inference_state = "generating"
            try:
                yield outcome
                outcome.inference_state = "completed"
            except BaseException:
                outcome.inference_state = "failed"
                raise
            return
        if shift.control_status().get("state") != "idle":
            raise ModelBusy("A previous model launcher is still being verified; no new model work was started")
        lease = lease_status()
        state = shift.status()
        ours = (lease.get("status") == "valid" and state.get("phase") == "driving"
                and state.get("owner_pid") == os.getpid()
                and (lease.get("lease") or {}).get("owner") == "farol"
                and (lease.get("lease") or {}).get("lease_id") == state.get("lease_id"))
        if ours:
            if not model_ready(endpoint, alias):
                raise FeedError("The driving model does not match Qwen; scores remain available")
            outcome.inference_state = "generating"
            try:
                yield outcome
                outcome.inference_state = "completed"
            except BaseException:
                outcome.inference_state = "failed"
                raise
            return
        # Orphan, expired, stale, and recovery states are not permission to take over.
        if lease.get("status") != "free":
            if lease.get("status") == "restore-failed" and (lease.get("lease") or {}).get("owner") == "farol":
                _record_cleanup({"state": "restoration_failed", "code": "coordinator_restore_failed",
                                 "detail": "Coordinator recovery has not completed."})
                raise RestorationBlocked("GPU restoration needs attention; new AI reviews are blocked")
            owner = (lease.get("lease") or {}).get("owner") or "another application"
            raise ModelBusy(f"Qwen is waiting: the GPU is reserved by {owner}. Scores and feeds remain available.")
        if (cleanup_status().get("state") == "restoration_failed" or state.get("phase") in {"error", "restoring"}):
            raise RestorationBlocked("Coordinator is free but previous restoration still requires verified health")
        if endpoint != "http://127.0.0.1:1234/v1/chat/completions" or alias != profile("qwen")["alias"]:
            raise FeedError("Use external management for a separately hosted Qwen endpoint")
        acquisition_started = time.monotonic()
        started = shift.start(owner_pid=os.getpid(), model_profile="qwen", mode="narrating")
        outcome.timings["acquire_seconds"] = round(time.monotonic() - acquisition_started, 3)
        if not started.get("ok"):
            raise ModelBusy("Qwen could not acquire the GPU; scores and feeds remain available")
        work_started = time.monotonic()
        try:
            if not model_ready(endpoint, alias):
                raise FeedError("The loaded model does not match Qwen; no request was sent")
            outcome.inference_state = "generating"
            yield outcome
            outcome.inference_state = "completed"
        except BaseException:
            outcome.inference_state = "failed"
            raise
        finally:
            outcome.timings["work_seconds"] = round(time.monotonic() - work_started, 3)
            cleanup_started = time.monotonic()
            _record_cleanup({"state": "restoring"})
            try:
                restored = shift.stop()
                success = isinstance(restored, dict) and restored.get("ok") is True
                code = "release_ok" if success else "release_failed"
            except Exception:  # noqa: BLE001 — preserve answer/original error even if cleanup fails
                success, code = False, "release_exception"
            outcome.timings["cleanup_seconds"] = round(time.monotonic() - cleanup_started, 3)
            outcome.release_result = {
                "state": "restored" if success else "restoration_failed", "code": code,
                "detail": ("GPU release completed." if success else
                           "AI work finished, but GPU restoration needs attention. New AI reviews require verified recovery."),
            }
            _record_cleanup(outcome.release_result)
            if not success:
                from farol.recovery import record_failure
                try:
                    record_failure(started.get("lease_id") or shift.status().get("lease_id"))
                except (OSError, ValueError):
                    # Preserve the answer/original exception even if diagnostic
                    # persistence fails. Coordinator ownership still blocks reuse.
                    _record_cleanup({**outcome.release_result, "code": "recovery_record_failed"})
