"""Local-file cooperative stop protocol for the supported Windows launcher.

The random instance and Windows process creation token prevent a stale stop
request from reaching a replacement PID. No network administration endpoint is
exposed. Files inherit the existing local operator trust boundary.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import uuid
from pathlib import Path

from farol.process_control import process_identity


class ServiceControl:
    def __init__(self, directory: Path, *, identity=process_identity):
        self.directory = directory
        self.identity = identity
        self.path = directory / "farol-service.json"
        self.request_path = directory / "farol-stop.json"
        self.record = {
            "protocol": 1, "pid": os.getpid(), "creation_token": identity(os.getpid()),
            "executable": str(Path(sys.executable).resolve()), "instance": uuid.uuid4().hex,
            "state": "starting",
        }
        if not self.record["creation_token"]:
            raise RuntimeError("Cannot establish this API process identity")
        self.stopped = threading.Event()
        self.thread = None

    def publish(self, state):
        if self.path.exists():
            try:
                previous = json.loads(self.path.read_text(encoding="utf-8-sig"))
                if previous.get("instance") != self.record["instance"]:
                    if type(previous.get("pid")) is not int or not previous.get("creation_token"):
                        raise RuntimeError("Existing API identity cannot be verified")
                    if self.identity(previous["pid"]) == previous["creation_token"]:
                        raise RuntimeError("Another API instance still owns the service record")
            except (OSError, ValueError, AttributeError) as error:
                raise RuntimeError("Existing API identity cannot be verified") from error
        self.record["state"] = state
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.record), encoding="utf-8")
        temporary.replace(self.path)

    def requested(self):
        try:
            request = json.loads(self.request_path.read_text(encoding="utf-8-sig"))
            return all(request.get(key) == self.record[key] for key in (
                "protocol", "pid", "creation_token", "instance"
            )) and request.get("action") == "stop"
        except (OSError, ValueError, AttributeError):
            return False

    def watch(self, server, begin_drain):
        self.publish("starting")

        def monitor():
            while not self.stopped.wait(0.25):
                if self.requested():
                    self.publish("draining")
                    begin_drain()
                    server.should_exit = True
                    return
                if server.started and self.record["state"] == "starting":
                    self.publish("running")

        self.thread = threading.Thread(target=monitor, name="rideedge-service-control", daemon=True)
        self.thread.start()

    def close(self):
        self.stopped.set()
        if self.thread:
            self.thread.join()
        # Never remove a newer instance's record/request.
        for path in (self.path, self.request_path):
            try:
                saved = json.loads(path.read_text(encoding="utf-8-sig"))
                if saved.get("instance") == self.record["instance"]:
                    path.unlink()
            except (OSError, ValueError, AttributeError):
                pass


def serve():
    import uvicorn

    from farol.dashboard import ROOT
    from farol.env import bind_host, bind_port
    from farol.service_lifecycle import begin_drain

    # Explicitly keep graceful shutdown unbounded: an operator observation
    # timeout cannot become cancellation of a model finally/cleanup block.
    server = uvicorn.Server(uvicorn.Config(
        "farol.api:app", host=bind_host(), port=bind_port(), reload=False,
        timeout_graceful_shutdown=None, access_log=False, proxy_headers=False,
    ))
    # Claim the listener before lifespan starts collectors/model supervision.
    # A direct duplicate invocation must fail before publishing an identity or
    # starting background work, even when it bypasses the PowerShell launcher.
    listener = socket.socket(socket.AF_INET6 if ":" in bind_host() else socket.AF_INET)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    control = None
    try:
        listener.bind((bind_host(), bind_port()))
        listener.setblocking(False)
        control = ServiceControl(ROOT / "beast" / "logs")
        control.watch(server, begin_drain)
        server.run(sockets=[listener])
    finally:
        if control:
            control.close()
        listener.close()
