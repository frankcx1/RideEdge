"""Driving-shift overlay: Companion parks, the selected local model narrates Farol.

The GPU lease library owns stop/restore of Cydonia. This module reads the
shift state file the PowerShell mutator writes, and heartbeats the lease
while Farol is the owner. Scoring stays in Python.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading

from farol.dashboard import ROOT

STATE_PATH = ROOT / "beast" / "shift.json"
SCRIPT = ROOT / "beast" / "farol-shift.ps1"
_lock = threading.Lock()
model_lock = threading.RLock()
_hb_stop = threading.Event()
_hb_thread: threading.Thread | None = None
_control = None


def _read() -> dict:
    if not STATE_PATH.is_file():
        return {"phase": "idle", "detail": "Companion on Cydonia; Farol has no GPU lease"}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"phase": "error", "detail": "shift.json unreadable"}


def _write(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def status() -> dict:
    state = _read()
    state.setdefault("phase", "idle")
    return state


def active() -> bool:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return os.getenv("FAROL_SHIFT_ACTIVE", "") == "1"
    state = _read()
    return state.get("phase") == "driving"


def _run_script(verb: str, extra: list[str] | None = None) -> dict:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return {"ok": False, "detail": "shift script disabled under pytest"}
    if not SCRIPT.is_file():
        return {"ok": False, "detail": f"missing {SCRIPT}"}
    args = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        verb,
        *(extra or []),
    ]
    if verb in {"start", "stop", "verify-recovery"}:
        return _launcher().run(args, verb, ROOT)
    # Renewal/status do not launch service controllers or change model processes.
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=20, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return {"ok": False, "detail": "Lease observation or renewal unavailable"}


def _launcher():
    global _control
    from farol.process_control import LauncherControl

    if _control is None:
        _control = LauncherControl(ROOT / ".cache" / "runtime")
    return _control


def control_status() -> dict:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return {"state": "idle"}
    return _launcher().status()


def acknowledge_recovery(lease_id: str) -> bool:
    """Only after read-only coordinator/model/bot verification under model_lock."""
    state = status()
    if state.get("phase") == "idle" and state.get("last_released_lease_id") == lease_id:
        return True
    if state.get("lease_id") != lease_id or state.get("phase") not in {"error", "restoring"}:
        return False
    _write({"phase": "idle", "last_released_lease_id": lease_id, "companion_away": False,
            "detail": "Coordinator and restored service health verified."})
    return True


def reconcile_control() -> bool:
    """Called under model_lock; settle late starts only after the controller exits."""
    control = _launcher()
    observed = control.status()
    if observed["state"] == "idle":
        return True
    if observed["state"] != "finished":
        return False
    verb = observed["verb"]
    if not control.acknowledge_finished():
        return False
    # An acquisition that outlived its request has no consumer. The stop script
    # verifies lease and process start identity before touching its narrator.
    if verb == "start" and status().get("phase") in {"narrating", "loading", "acquiring", "driving"}:
        result = stop()
        return result.get("ok") is True
    return True


def start(owner_pid: int | None = None, model_profile: str | None = None,
          *, mode: str = "driving") -> dict:
    from farol.local_models import profile

    selected = profile(model_profile)
    extra = ["-Model", selected["id"]]
    if owner_pid:
        extra.extend(["-FarolPid", str(owner_pid)])
    if mode != "driving":
        extra.extend(["-Mode", mode])
    with model_lock:
        result = _run_script("start", extra)
    if result.get("ok"):
        _start_heartbeat()
    return result


def stop() -> dict:
    with model_lock:
        _stop_heartbeat()
        return _run_script("stop")


def renew() -> dict:
    state = _read()
    lease_id = state.get("lease_id")
    owner = state.get("owner") or "farol"
    if not lease_id or state.get("phase") not in {"driving", "narrating"}:
        return {"ok": False, "detail": "no active lease"}
    return _run_script("renew", ["-LeaseId", str(lease_id), "-Owner", str(owner)])


def _heartbeat_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(60):
        if status().get("phase") not in {"driving", "narrating"}:
            break
        try:
            renew()
        except (OSError, ValueError) as error:
            logging.getLogger(__name__).warning("GPU lease renewal failed: %s", error)


def _start_heartbeat() -> None:
    global _hb_thread, _hb_stop
    with _lock:
        if _hb_thread is not None and _hb_thread.is_alive() and not _hb_stop.is_set():
            return
        _hb_stop = threading.Event()
        _hb_thread = threading.Thread(target=_heartbeat_loop, args=(_hb_stop,),
                                      name="farol-lease-hb", daemon=True)
        _hb_thread.start()


def _stop_heartbeat() -> None:
    _hb_stop.set()


def resume_heartbeat_if_driving() -> None:
    if active() and not os.getenv("PYTEST_CURRENT_TEST"):
        _start_heartbeat()
