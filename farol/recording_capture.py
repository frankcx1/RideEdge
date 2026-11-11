"""Explicit local recording receipts. Ordinary inference retains no prompt text."""
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import hashlib
import json
from pathlib import Path

_sink = ContextVar("recording_capture", default=None)


@contextmanager
def observe_inference():
    receipts = []
    token = _sink.set(receipts)
    try:
        yield receipts
    finally:
        _sink.reset(token)


def retain(request, response, metric):
    sink = _sink.get()
    if sink is not None:
        sink.append(copy.deepcopy({"request": request, "response": response, "metric": metric}))


def seal(payload):
    result = copy.deepcopy(payload)
    result.pop("sha256", None)
    result["sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False,
                                                allow_nan=False).encode()).hexdigest()
    return result


def load_capture(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("kind") != "captured_session" or value.get("schema_version") != 1:
        raise ValueError("Not a captured evaluation")
    if value.get("sha256") != seal(value)["sha256"]:
        raise ValueError("Captured evaluation checksum mismatch")
    from farol.radar_contract import RadarView
    for stage in value["stages"]:
        RadarView.model_validate(stage["radar"])
    if not value["stages"]:
        raise ValueError("Capture has no evaluation")
    return value
