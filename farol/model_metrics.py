"""Bounded numeric inference receipts; never stores prompts, answers or locations."""
import json
import math
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from farol.dashboard import ROOT


def path():
    return Path(os.getenv("RIDEEDGE_MODEL_METRICS_FILE", str(ROOT / ".cache/runtime/model-metrics.sqlite3")))


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def receipt(payload, seconds, model, workload="application"):
    timings = payload.get("timings") if isinstance(payload.get("timings"), dict) else {}
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    def rate(prefix):
        reported = number(timings.get(prefix + "_per_second"))
        if reported is not None:
            return reported
        count, ms = number(timings.get(prefix + "_n")), number(timings.get(prefix + "_ms"))
        return count * 1000 / ms if count is not None and ms and ms > 0 else None
    return {"observed_at": datetime.now(UTC).isoformat(), "model": str(model)[:100],
            "workload": workload if workload in {"diagnostic", "departure-review"} else "application",
            "request_seconds": number(seconds), "generation_tokens_per_second": rate("predicted"),
            "prompt_tokens_per_second": rate("prompt"), "prompt_tokens": number(usage.get("prompt_tokens")),
            "completion_tokens": number(usage.get("completion_tokens")),
            "processed_prompt_tokens": number(timings.get("prompt_n")), "cached_tokens": number(timings.get("cache_n")),
            "generation_seconds": (number(timings.get("predicted_ms")) / 1000) if number(timings.get("predicted_ms")) is not None else None,
            "prompt_seconds": (number(timings.get("prompt_ms")) / 1000) if number(timings.get("prompt_ms")) is not None else None,
            "basis": "Inference server timings and usage; HTTP duration measured by RideEdge"}


def record(payload, seconds, model, workload="application"):
    try:
        row = receipt(payload, seconds, model, workload)
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(target, timeout=.2)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS samples (id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("INSERT INTO samples(data) VALUES (?)", (json.dumps(row, allow_nan=False),))
            db.execute("DELETE FROM samples WHERE id NOT IN (SELECT id FROM samples ORDER BY id DESC LIMIT 100)")
    except (OSError, ValueError, TypeError, AttributeError, sqlite3.Error):
        # Observability must never change a successful model response.
        pass


def snapshot():
    if not path().exists():
        return {"samples": [], "retained_count": 0}
    try:
        with closing(sqlite3.connect(path(), timeout=.2)) as db:
            rows = [json.loads(row[0]) for row in db.execute("SELECT data FROM samples ORDER BY id DESC LIMIT 100")]
        return {"samples": rows[:12], "retained_count": len(rows)}
    except (OSError, ValueError, sqlite3.Error):
        return {"samples": [], "retained_count": 0, "state": "unavailable"}
