"""Persistent, bounded supervision of owned GPU recovery.

Timeout is an observation boundary, never evidence that a child stopped. Live
recovery handles remain tracked and prevent another attempt after the deadline.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from farol.dashboard import ROOT
from farol.process_control import process_identity

DIRECTORY = ROOT / ".cache" / "runtime"
MAX_ATTEMPTS = 10
WINDOW_SECONDS = 600
COOLDOWN_SECONDS = 60


class RecoveryRunner:
    def __init__(self, directory: Path):
        self.directory = directory
        self._children = {}

    def start(self, lease_id: str, seconds: int) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", lease_id):
            raise ValueError("Invalid lease identity")
        self.directory.mkdir(parents=True, exist_ok=True)
        tag = uuid.uuid4().hex
        output = self.directory / f"restore-{tag}.out.json"
        errors = self.directory / f"restore-{tag}.err.log"
        with output.open("wb") as stdout, errors.open("wb") as stderr:
            child = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-File", str(ROOT / "beast/farol-recover.ps1"),
                 "-ExpectedLeaseId", lease_id, "-DeadlineSeconds", str(max(5, seconds))],
                stdout=stdout, stderr=stderr, cwd=ROOT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        self._children[child.pid] = child
        return {"pid": child.pid, "identity": process_identity(child.pid), "output": output.name}

    def alive(self, handle: dict) -> bool:
        child = self._children.get(handle["pid"])
        if child is not None:
            if child.poll() is None:
                return True
            self._children.pop(handle["pid"], None)
            return False
        if not handle.get("identity"):
            raise OSError("Recovery process identity was not saved")
        return process_identity(handle["pid"]) == handle["identity"]


class RecoverySupervisor:
    def __init__(self, directory: Path, probe, acknowledge, runner=None, *, wall=time.time, mono=time.monotonic):
        self.directory, self.probe, self.acknowledge = directory, probe, acknowledge
        self.runner = runner or RecoveryRunner(directory)
        self.wall, self.mono = wall, mono
        self.path = directory / "recovery.json"
        self.lock = threading.RLock()
        self.last_mono = mono()
        self.state = None
        if self.path.exists():
            try:
                self.state = json.loads(self.path.read_text(encoding="utf-8"))
                required = {"lease_id", "attempts", "remaining", "cooldown", "last_seen", "phase"}
                if not isinstance(self.state, dict) or not required <= self.state.keys():
                    raise ValueError("Invalid saved recovery state")
                for key in ("attempts", "remaining", "cooldown", "last_seen"):
                    value = self.state[key]
                    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                        raise ValueError("Invalid saved recovery budget")
                if self.state["remaining"] > WINDOW_SECONDS or self.state["attempts"] > MAX_ATTEMPTS:
                    raise ValueError("Invalid saved recovery bounds")
            except (OSError, ValueError):
                self.state = {"lease_id": None, "attempts": MAX_ATTEMPTS, "remaining": 0,
                              "cooldown": 0, "last_seen": wall(), "phase": "manual",
                              "code": "saved_recovery_state_unreadable"}

    def _save(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state), encoding="utf-8")
        temporary.replace(self.path)

    def record(self, lease_id: str):
        if not lease_id:
            return
        with self.lock:
            if self.state and self.state.get("phase") != "restored":
                return  # Observing the same failure cannot reset its budget.
            self.state = {"lease_id": lease_id, "attempts": 0, "remaining": WINDOW_SECONDS,
                          "cooldown": COOLDOWN_SECONDS, "last_seen": self.wall(),
                          "phase": "waiting", "code": "restoration_failed"}
            self.last_mono = self.mono()
            self._save()

    def status(self) -> dict:
        with self.lock:
            if not self.state:
                return {}
            s = self.state
            return {"state": "restored" if s["phase"] == "restored" else "restoration_failed",
                    "recovery_state": s["phase"], "attempts": s["attempts"],
                    "remaining_seconds": max(0, round(s["remaining"])), "code": s.get("code"),
                    "next_retry_seconds": max(0, round(s["cooldown"])) if s["phase"] == "waiting" else None,
                    "detail": ("Coordinator and restored service health verified." if s["phase"] == "restored" else
                               "GPU restoration is unresolved. Evidence ranking remains available; new AI work is blocked.")}

    def tick(self):
        with self.lock:
            s = self.state
            if not s or s["phase"] == "restored":
                return
            now, monotonic = self.wall(), self.mono()
            delta = max(0, now - s["last_seen"], monotonic - self.last_mono)
            if now < s["last_seen"]:
                s["remaining"] = 0  # Wall-clock rollback cannot replenish a saved budget.
            s["remaining"] = max(0, s["remaining"] - delta)
            s["cooldown"] = max(0, s["cooldown"] - delta)
            s["last_seen"], self.last_mono = now, monotonic
            running = s.get("running")
            if running:
                try:
                    alive = self.runner.alive(running)
                except (OSError, ValueError):
                    s["code"] = "recovery_observation_unavailable"
                    self._save()
                    return
                if alive:
                    s["phase"] = "running" if s["remaining"] else "deadline_with_live_operation"
                    self._save()
                    return
                s.pop("running")
                s["cooldown"] = COOLDOWN_SECONDS  # At least 60 s AFTER confirmed completion.
            elif s["phase"] == "launching":
                # Crash between spawning and saving the identity is not evidence
                # the child stopped. Do not spawn another operation.
                s["phase"] = "manual"
                s["code"] = "recovery_handle_not_saved"
            try:
                lease = self.probe()
                if s["lease_id"] and lease.get("status") == "free" and self.acknowledge(s["lease_id"]):
                    s["phase"], s["code"] = "restored", "restored_health_verified"
                    self._save()
                    return
            except (OSError, ValueError, RuntimeError):
                s["code"] = "coordinator_verification_unavailable"
                self._save()
                return
            identity = lease.get("lease") or {}
            if (lease.get("status") != "restore-failed" or lease.get("operation_alive") or
                identity.get("operation_id") or identity.get("owner") != "farol" or
                identity.get("lease_id") != s["lease_id"]):
                s["code"] = "ownership_or_operation_conflict"
            elif s["phase"] != "manual" and s["remaining"] >= 5 and s["attempts"] < MAX_ATTEMPTS:
                s["phase"] = "waiting"
                if s["cooldown"] <= 0:
                    s["attempts"] += 1
                    s["phase"] = "launching"
                    self._save()  # Budget committed before any process is launched.
                    try:
                        s["running"] = self.runner.start(s["lease_id"], int(s["remaining"]))
                        s["phase"] = "running"
                    except (OSError, ValueError):
                        # Child may have started before identity capture failed.
                        s["phase"], s["code"] = "manual", "recovery_launch_unverified"
            elif s["phase"] != "manual":
                s["phase"], s["code"] = "exhausted", "recovery_budget_exhausted"
            self._save()


_supervisor = None
_thread = None
_stop = threading.Event()


def acknowledge_verified_release(lease_id):
    """Read-only reconciliation after an operator recovered and later used Qwen.

    A later owned release can supersede the single shift record while the old
    persisted supervisor warning remains. Verify that exact current release and
    restored services; never rewrite shift identity to match the old warning.
    """
    from farol import shift

    result = shift._run_script("check-recovery", ["-LeaseId", lease_id])
    if result.get("ok") is True:
        return shift.acknowledge_recovery(lease_id)
    current = shift.status()
    released = current.get("last_released_lease_id")
    if current.get("phase") != "idle" or not isinstance(released, str) or not released or released == lease_id:
        return False
    try:
        stopped = datetime.fromisoformat(current.get("stopped_at") or "")
        if not stopped.tzinfo or stopped > datetime.now(UTC) + timedelta(minutes=5):
            return False
    except (TypeError, ValueError):
        return False
    if shift.control_status().get("state") != "idle":
        return False
    # This script checks a free coordinator before/after, expected Cydonia health
    # and bot process identity. It neither starts nor stops services.
    verified = shift._run_script("check-recovery", ["-LeaseId", released])
    after = shift.status()
    return (verified.get("ok") is True and shift.control_status().get("state") == "idle"
            and all(after.get(k) == current.get(k) for k in ("phase", "last_released_lease_id", "stopped_at")))


def _get():
    global _supervisor
    if _supervisor is None:
        from farol import local_runtime

        _supervisor = RecoverySupervisor(DIRECTORY, local_runtime.lease_status, acknowledge_verified_release)
    return _supervisor


def record_failure(lease_id):
    if not os.getenv("PYTEST_CURRENT_TEST"):
        _get().record(lease_id)


def status():
    return _supervisor.status() if _supervisor else {}


def operation_status():
    """Read-only child observation for shutdown; never launches another retry."""
    supervisor = _get()
    with supervisor.lock:
        state = supervisor.state or {}
        if state.get("running"):
            try:
                return {"state": "running" if supervisor.runner.alive(state["running"]) else "idle"}
            except (OSError, ValueError, KeyError):
                return {"state": "unknown"}
        if state.get("phase") in {"launching", "running", "deadline_with_live_operation"} or state.get("code") in {
            "recovery_handle_not_saved", "recovery_launch_unverified", "saved_recovery_state_unreadable"
        }:
            return {"state": "unknown"}
        return {"state": "idle"}


def _loop():
    from farol import local_runtime, shift

    while not _stop.is_set():
        if shift.model_lock.acquire(blocking=False):
            try:
                supervisor = _get()
                if shift.reconcile_control():
                    state = shift.status()
                    if state.get("phase") in {"error", "restoring"} and state.get("owner") == "farol":
                        supervisor.record(state.get("lease_id"))
                    supervisor.tick()
                    if supervisor.status():
                        local_runtime._record_cleanup(supervisor.status())
            except (OSError, ValueError, RuntimeError):
                pass  # Retain the failure; a transient observation cannot imply recovery.
            finally:
                shift.model_lock.release()
        _stop.wait(5)


def start():
    global _thread
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("MOCK_FEEDS", "") == "1":
        return
    if _thread is None or not _thread.is_alive():
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="rideedge-recovery", daemon=True)
        _thread.start()


def stop():
    _stop.set()  # An owned child is not killed; its saved identity survives restart.
