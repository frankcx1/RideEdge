"""Cooperative API drain: retain all owned workers until their work finishes.

No process termination, lease mutation, or model recovery happens here. Uvicorn
first drains HTTP requests; lifespan then waits for background work and tracked
controllers. A timeout in the operator's observer never cancels this drain.
"""
from __future__ import annotations

import threading
import time

_condition = threading.Condition()
_workers: set[threading.Thread] = set()


class WorkThread(threading.Thread):
    """Register before start so shutdown cannot miss a not-yet-scheduled job."""

    def start(self):
        with _condition:
            if self in _workers:
                raise RuntimeError("Worker already started")
            _workers.add(self)
            try:
                super().start()
            except BaseException:
                _workers.discard(self)
                _condition.notify_all()
                raise

    def run(self):
        try:
            super().run()
        finally:
            with _condition:
                _workers.discard(self)
                _condition.notify_all()


def wait_for_workers():
    with _condition:
        while _workers:
            _condition.wait(0.5)


def wait_for_model_control(control_status, recovery_status, lease_status, sleep=time.sleep):
    """Read-only wait. Unverifiable ownership/operation state fails closed.

    Persisted, quiescent restoration failures may survive restart. Active leases
    and operations may not be abandoned by a planned API shutdown.
    """
    while True:
        try:
            control = control_status()
            recovery = recovery_status()
            lease = lease_status()
        except (OSError, ValueError, RuntimeError):
            sleep(5)
            continue
        safe_control = control.get("state") in {"idle", "finished"}
        safe_recovery = recovery.get("state") == "idle"
        identity = lease.get("lease") or {}
        # Coordinator v3 explicitly emits null for non-transient statuses.
        safe_lease = (lease.get("ok") is True and lease.get("status") in {"free", "restore-failed"}
                      and "operation_alive" in lease and lease["operation_alive"] in (False, None)
                      and not identity.get("operation_id"))
        if safe_control and safe_recovery and safe_lease:
            return
        sleep(5)


def begin_drain():
    from farol import collect, radar_api, recovery
    from farol.model_queue import queue

    queue.close()
    collect.stop(wait=False)
    radar_api.stop()
    recovery.stop()


def drain(*, verify_model=True):
    from farol import collect, local_runtime, radar_api, recovery, shift
    from farol.adapters.routes import clear_private_cache
    # Signal every scheduler before waiting on any one of them. Existing jobs
    # finish their finally blocks; no signal or exception interrupts inference.
    begin_drain()
    for thread in (collect._thread, radar_api._thread, recovery._thread):
        if thread is not None and thread is not threading.current_thread():
            thread.join()
    wait_for_workers()
    # Keep heartbeat alive while an explicit legacy driving lease still exists.
    # Its operator must end the lease through the supported shift procedure;
    # draining never silently ends a resident session or resets recovery state.
    if verify_model:
        wait_for_model_control(shift.control_status, recovery.operation_status, local_runtime.lease_status)
    shift._stop_heartbeat()
    if shift._hb_thread is not None:
        shift._hb_thread.join()
    clear_private_cache()
