"""Persist launcher identity; an observation timeout never terminates GPU work."""
from __future__ import annotations

import ctypes
import json
import subprocess
import threading
import uuid
from pathlib import Path


def process_identity(pid: int) -> str | None:
    """Windows creation token. An inspection failure is not proof of exit."""
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return None
        raise OSError("Process identity could not be inspected")
    try:
        created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                      ctypes.byref(system), ctypes.byref(user)):
            raise OSError("Process creation identity unavailable")
        if exited.dwHighDateTime or exited.dwLowDateTime:
            return None
        return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


class LauncherControl:
    def __init__(self, directory: Path, *, spawn=None, identity=None):
        self.directory = directory
        self.path = directory / "launcher.json"
        self.spawn = spawn or subprocess.Popen
        self.identity = identity or process_identity
        self.child = None
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return None
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("verb") not in {"start", "stop", "verify-recovery"}:
                raise ValueError("Invalid launcher record")
            return state
        except (OSError, ValueError):
            return {"verb": "unknown", "phase": "unknown"}

    def _save(self, state):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        temporary.replace(self.path)

    def status(self):
        with self.lock:
            state = self._read()
            if state is None:
                return {"state": "idle"}
            observed = "unknown"
            try:
                if self.child is not None and self.child.pid == state.get("pid"):
                    observed = "running" if self.child.poll() is None else "finished"
                elif state.get("identity") and type(state.get("pid")) is int:
                    observed = "running" if self.identity(state["pid"]) == state["identity"] else "finished"
            except OSError:
                pass
            return {"state": observed, "verb": state["verb"]}

    def acknowledge_finished(self):
        with self.lock:
            if self.status()["state"] != "finished":
                return False
            self.path.unlink()
            self.child = None
            return True

    def run(self, args: list[str], verb: str, cwd: Path, *, timeout=420) -> dict:
        with self.lock:
            if self._read() is not None:
                return {"ok": False, "code": "launcher_pending",
                        "detail": "The previous model launcher still needs verified completion."}
            tag = uuid.uuid4().hex
            out_path = self.directory / f"launcher-{tag}.out.log"
            err_path = self.directory / f"launcher-{tag}.err.log"
            # A crash between spawn and identity persistence must fail closed.
            self._save({"verb": verb, "phase": "launching"})
            try:
                with out_path.open("wb") as stdout, err_path.open("wb") as stderr:
                    self.child = self.spawn(args, stdout=stdout, stderr=stderr, cwd=str(cwd),
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    self._save({"verb": verb, "phase": "running", "pid": self.child.pid,
                                "identity": self.identity(self.child.pid)})
            except OSError:
                return {"ok": False, "code": "launcher_observation_unavailable",
                        "detail": "Model control could not be verified; further changes are blocked."}
        # Do not hold the observation lock while waiting: status must stay responsive.
        try:
            code = self.child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "code": "launcher_pending",
                    "detail": "Model control is still running; its original process remains tracked."}
        except OSError:
            return {"ok": False, "code": "launcher_observation_unavailable",
                    "detail": "Model control could not be verified; further changes are blocked."}
        with self.lock:
            output = out_path.read_text(encoding="utf-8", errors="replace")
            errors = err_path.read_text(encoding="utf-8", errors="replace")
            self.acknowledge_finished()
            try:
                result = json.loads(output.strip().splitlines()[-1])
                if isinstance(result, dict):
                    result.setdefault("ok", code == 0)
                    return result
            except (ValueError, IndexError):
                pass
            return {"ok": code == 0, "exit": code,
                    "detail": (output + errors)[-600:] or f"exit {code}"}
