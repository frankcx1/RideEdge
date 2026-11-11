"""Nonblocking, single-request Qwen narration for browsing and driving.

Scores render immediately. A short GPU loan is restored after idle narration;
another application's lease produces a visible busy result, never cloud fallback.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from datetime import UTC, datetime

from farol import local, local_runtime
from farol.adapters.base import FeedError, read_cache, write_cache
from farol.grok import ttl_seconds
from farol.service_lifecycle import WorkThread

_lock = threading.Lock()
_running: str | None = None
_retry_until = 0.0
_failures: dict[str, dict] = {}
_last: dict = {"mode": "idle", "detail": "Qwen prepares briefs on demand"}
RETRY_SECONDS = 90


def status() -> dict:
    with _lock:
        return dict(_last)


def _metadata(alias: str, mode: str, detail: str, **extra) -> dict:
    return {"provider": "local", "model": alias, "mode": mode, "detail": detail, **extra}


def _attach(brief: dict, cached: dict, alias: str) -> dict:
    from farol.brain import constrain_narration, parse_narration

    narration = constrain_narration(brief, parse_narration(cached["payload"]))
    brief["brain"] = _metadata(alias, "cache", "Local Qwen · connected feed evidence · no cloud AI",
                               fetched_at=cached["fetched_at"])
    brief["brain"]["cleanup"] = local_runtime.cleanup_status()
    brief["narration"] = narration
    for item in brief.get("opportunities", []):
        note = narration["opportunity_notes"].get(item["id"])
        if note:
            item["note"] = note
    return brief


def _work(brief: dict, key: str, endpoint: str, alias: str):
    global _running, _last, _retry_until
    from farol.brain import LOCAL_SYSTEM_PROMPT, _public_brief, parse_narration

    result = _metadata(alias, "error", "Qwen request interrupted; scores remain available")
    try:
        with local_runtime.session(endpoint, alias, job_kind="brief") as model_session:
            payload, _, _ = local.complete(
                system=LOCAL_SYSTEM_PROMPT, user=json.dumps(_public_brief(brief, local=True), default=str),
                cache_key=key, endpoint=endpoint, model_name=alias, model_profile="qwen")
            # Reject malformed output before saving a successful cache entry.
            parse_narration(payload)
        write_cache(key, payload, url=endpoint)
        result = _metadata(alias, "ready", "Qwen brief is ready")
        if model_session is not None:
            result["runtime"] = model_session.public()
    except Exception as error:  # noqa: BLE001 — keep the worker and GPU restoration observable
        mode = "busy" if isinstance(error, local_runtime.ModelBusy) else "error"
        detail = str(error) if isinstance(error, FeedError) else "Qwen could not prepare a valid brief; scores remain available"
        result = _metadata(alias, mode, detail, retry_after_seconds=RETRY_SECONDS)
        with _lock:
            _retry_until = time.monotonic() + RETRY_SECONDS
            _failures[key] = {"until": _retry_until, "brain": result}
    finally:
        with _lock:
            _running = None
            _last = result
            if result["mode"] == "ready":
                _retry_until = 0


def apply(brief: dict) -> dict:
    global _running, _last
    from farol.brain import _cache_key

    brief["narration"] = None
    try:
        endpoint, alias = local_runtime.settings()
    except FeedError as error:
        brief["brain"] = _metadata("Qwen", "error", str(error))
        return brief
    identity = hashlib.sha256(f"{endpoint}|{alias}".encode()).hexdigest()[:12]
    key = f"qwen_v1_{identity}_{_cache_key(brief)}"
    cached = read_cache(key)
    if cached:
        try:
            age = (datetime.now(UTC) - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
            if 0 <= age < ttl_seconds():
                return _attach(brief, cached, alias)
        except (KeyError, ValueError, TypeError):
            pass
    with _lock:
        now = time.monotonic()
        for old in [old for old, failure in _failures.items() if failure["until"] <= now]:
            del _failures[old]
        if key in _failures:
            brief["brain"] = dict(_failures[key]["brain"])
        elif now < _retry_until:
            # Different browser filters/clock windows must not evade the GPU backoff.
            brief["brain"] = dict(_last)
        elif _running:
            brief["brain"] = _metadata(alias, "warming", "Qwen is preparing a brief; scores and feeds are ready")
        else:
            _running = key
            _last = _metadata(alias, "warming", "Qwen is preparing your brief; scores and feeds are ready")
            brief["brain"] = dict(_last)
            WorkThread(target=_work, args=(copy.deepcopy(brief), key, endpoint, alias),
                             name="farol-qwen", daemon=True).start()
    return brief
