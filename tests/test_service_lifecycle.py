import json
import shutil
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

from farol.model_queue import ModelQueue, QueueBusy
from farol.service_control import ServiceControl
from farol.service_lifecycle import WorkThread, wait_for_model_control, wait_for_workers


def test_drain_waits_for_worker_cleanup_and_nested_work():
    started, release, cleanup, child_release = (threading.Event() for _ in range(4))

    def work():
        started.set()
        try:
            release.wait(3)
        finally:
            WorkThread(target=lambda: child_release.wait(3), daemon=True).start()
            cleanup.set()

    job = WorkThread(target=work, daemon=True)
    job.start()
    assert started.wait(1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        drained = pool.submit(wait_for_workers)
        assert not drained.done()
        release.set()
        assert cleanup.wait(1)
        assert not drained.done()  # Child remains owned after parent finishes.
        child_release.set()
        drained.result(timeout=2)
    job.join(1)


def test_closed_model_queue_rejects_pending_but_does_not_interrupt_active():
    queue = ModelQueue()
    attempted = threading.Event()

    def pending():
        attempted.set()
        with pytest.raises(QueueBusy), queue.admit():
            pytest.fail("A draining queue admitted a request")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with queue.admit("radar-plan"):
            waiter = pool.submit(pending)
            assert attempted.wait(1)
            queue.close()
            waiter.result(timeout=2)
            assert queue.status()["active"] == "radar-plan"
        with pytest.raises(QueueBusy), queue.admit():
            pytest.fail("A closed queue accepted new work")
    assert queue.status()["active"] is None
    queue.open()
    with queue.admit():
        pass


def test_stop_request_is_instance_bound_and_preserves_newer_files(tmp_path):
    control = ServiceControl(tmp_path, identity=lambda _: "123456789")
    control.publish("running")
    request = {**control.record, "action": "stop"}
    for key, wrong in (("instance", "a" * 32), ("pid", -1), ("creation_token", "old"), ("protocol", 0)):
        control.request_path.write_text(json.dumps({**request, key: wrong}))
        assert not control.requested()
    control.request_path.write_text(json.dumps(request))
    assert control.requested()
    server = SimpleNamespace(started=True, should_exit=False)
    drained = threading.Event()
    control.watch(server, drained.set)
    assert drained.wait(2)
    control.thread.join(1)
    assert server.should_exit
    assert json.loads(control.path.read_text())["state"] == "draining"
    newer = {**request, "instance": "b" * 32}
    control.path.write_text(json.dumps(newer))
    control.request_path.write_text(json.dumps(newer))
    control.close()
    assert json.loads(control.path.read_text()) == newer
    assert control.request_path.exists()


def test_service_record_cannot_replace_a_live_or_unverifiable_owner(tmp_path):
    control = ServiceControl(tmp_path, identity=lambda _: "123456789")
    live = {**control.record, "instance": "c" * 32}
    control.path.write_text(json.dumps(live))
    with pytest.raises(RuntimeError, match="Another API instance"):
        control.publish("starting")
    assert json.loads(control.path.read_text()) == live
    control.path.write_text("bad json")
    with pytest.raises(RuntimeError, match="cannot be verified"):
        control.publish("starting")
    control.path.write_text(json.dumps({**live, "creation_token": "expired"}))
    control.publish("starting")
    assert json.loads(control.path.read_text())["instance"] == control.record["instance"]
    control.close()


def test_drain_waits_through_busy_unknown_failed_probe_and_running_recovery():
    observed = []
    cases = iter([
        ({"state": "running"}, {"state": "idle"}, {"ok": True, "status": "free", "operation_alive": None}),
        ({"state": "idle"}, {"state": "running"}, {"ok": True, "status": "free", "operation_alive": None}),
        ({"state": "unknown"}, {"state": "idle"}, {"ok": True, "status": "free", "operation_alive": None}),
        ({"state": "idle"}, {"state": "idle"}, {"ok": True, "status": "valid", "operation_alive": None}),
        ({"state": "idle"}, {"state": "idle"}, RuntimeError("temporary probe timeout")),
        ({"state": "idle"}, {"state": "idle"}, {"ok": True, "status": "restore-failed", "operation_alive": True}),
        ({"state": "idle"}, {"state": "idle"}, {"ok": True, "status": "restore-failed", "operation_alive": None,
                                                "lease": {"operation_id": "still-recorded"}}),
        ({"state": "finished"}, {"state": "idle"}, {"ok": True, "status": "restore-failed", "operation_alive": None}),
    ])
    current = next(cases)

    def lease():
        if isinstance(current[2], Exception):
            raise current[2]
        return current[2]

    def advance(seconds):
        nonlocal current
        observed.append(seconds)
        current = next(cases)

    wait_for_model_control(lambda: current[0], lambda: current[1], lease, advance)
    assert len(observed) == 7


def test_recovery_shutdown_probe_observes_child_without_retry_or_budget_change(monkeypatch):
    from farol import recovery

    state = {"running": {"pid": 42}, "phase": "deadline_with_live_operation", "attempts": 10}
    supervisor = SimpleNamespace(lock=threading.RLock(), state=state,
                                 runner=SimpleNamespace(alive=lambda _: True))
    monkeypatch.setattr(recovery, "_supervisor", supervisor)
    assert recovery.operation_status() == {"state": "running"}
    supervisor.runner.alive = lambda _: False
    assert recovery.operation_status() == {"state": "idle"}
    assert state["attempts"] == 10 and state["running"] == {"pid": 42}
    supervisor.state = {"phase": "manual", "code": "recovery_handle_not_saved"}
    assert recovery.operation_status() == {"state": "unknown"}


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="Windows launcher guards")
def test_launcher_refuses_unhealthy_restart_stale_pid_and_timed_out_stop(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/test_server_safety.ps1"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-File", str(script), "-TestDirectory", str(tmp_path)],
        capture_output=True, text=True, timeout=20, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "7 launcher guard cases passed" in result.stdout


def test_uvicorn_cooperative_stop_waits_for_background_finally(tmp_path):
    import asyncio
    from contextlib import asynccontextmanager

    import uvicorn
    from fastapi import FastAPI

    worker_started, release, cleaned = (threading.Event() for _ in range(3))

    def work():
        try:
            worker_started.set()
            release.wait(10)
        finally:
            cleaned.set()

    @asynccontextmanager
    async def lifespan(_):
        yield
        await asyncio.to_thread(wait_for_workers)

    app = FastAPI(lifespan=lifespan)

    @app.post("/fixture-work")
    def start_work():
        WorkThread(target=work, daemon=True).start()
        return {"accepted": True}

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False,
                                              timeout_graceful_shutdown=None))
        control = ServiceControl(tmp_path, identity=lambda _: "fixture-creation")
        drain_requested = threading.Event()
        control.watch(server, drain_requested.set)
        serving = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        serving.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and time.monotonic() < deadline:
                time.sleep(.01)
            assert server.started
            with urlopen(Request(f"http://127.0.0.1:{port}/fixture-work", method="POST"), timeout=2) as response:
                assert response.status == 200
            assert worker_started.wait(1)
            control.request_path.write_text(json.dumps({**control.record, "action": "stop"}))
            assert drain_requested.wait(2)
            serving.join(.3)
            assert serving.is_alive() and not cleaned.is_set()
            release.set()
            serving.join(3)
            assert not serving.is_alive() and cleaned.is_set()
        finally:
            release.set()
            server.should_exit = True
            serving.join(3)
            control.close()


def test_duplicate_server_cannot_start_lifespan_or_replace_identity(monkeypatch):
    from farol import service_control

    with socket.socket() as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        monkeypatch.setenv("FAROL_HOST", "127.0.0.1")
        monkeypatch.setenv("FAROL_PORT", str(listener.getsockname()[1]))

        def forbidden(*args, **kwargs):
            pytest.fail("Duplicate server published an instance before owning its listener")

        monkeypatch.setattr(service_control, "ServiceControl", forbidden)
        with pytest.raises(OSError):
            service_control.serve()
