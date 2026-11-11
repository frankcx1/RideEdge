"""Offline GGUF/tokenizer receipt for full radar pools; no inference/provider/GPU calls."""
import argparse
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from farol import local, local_runtime, prompt_budget, radar


def capture_request(view):
    captured = []

    class Captured(Exception):
        pass

    def complete(**kwargs):
        captured.append(kwargs)
        raise Captured

    with patch.object(local_runtime, "session", return_value=nullcontext()), \
            patch.object(local, "complete", side_effect=complete):
        try:
            radar.ask_model(view)
        except Captured:
            pass
    assert len(captured) == 1
    return captured[0]


def request(distinct_hours: bool):
    now = datetime(2026, 10, 25, 2, 30, tzinfo=UTC)
    origin = radar.origin("Seattle")

    def candidates(snapshot, besttime, at, current):
        hour = int((at - current).total_seconds() / 3600) if distinct_hours else 0
        rows = []
        for index in range(8):
            rows.append({
                "id": f"fixture-{hour}-{index}", "name": f"Synthetic venue {hour}-{index}",
                "zone": "seattle_core", "category": "Events", "strength": "Scheduled activity",
                "latitude": origin["latitude"] + index * .001,
                "longitude": origin["longitude"], "activity_weight": 40 - index,
                "ends_at": (now + timedelta(hours=7)).isoformat(), "maps_url": "",
                "pin_basis": "synthetic venue", "evidence": [
                    {"id": f"fixture:{hour}:{index}:{source}",
                     "source": f"fixture:source-{hour}-{index}-{source}", "basis": "scheduled",
                     "starts_at": now.isoformat(), "role": "opportunity", "activity_weight": (40-index)/2,
                     "fetched_at": now.isoformat(), "ends_at": (now + timedelta(hours=7)).isoformat(),
                     "text": (f"Synthetic evidence for venue {hour}-{index}, source {source}. " +
                              "Scheduled activity is an estimate, not observed riders. " * 4)[:160]}
                    for source in range(2)
                ],
            })
        return rows, []

    with patch.object(radar, "candidates", side_effect=candidates):
        view = radar.build(origin, {}, {}, now=now)
    return capture_request(view)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retained", action="store_true", help="Measure saved inputs at public Seattle Center instead of synthetic cases")
    parser.add_argument("--area", default="Seattle Center", help="Named origin for the retained-input check; no device location is read")
    args = parser.parse_args()
    if args.retained:
        from farol.radar_api import read_inputs

        snapshot, venues = read_inputs()
        view = radar.build(radar.origin(args.area), snapshot, venues, now=datetime.now(UTC))
        cases = [("Retained inputs; named-area origin", capture_request(view))]
    else:
        cases = [("48-distinct-place stress pool" if distinct else "8-place full recurring pool", request(distinct))
                 for distinct in (False, True)]
    results = []
    for case, payload in cases:
        messages = [{"role": "system", "content": payload["system"]},
                    {"role": "user", "content": payload["user"]}]
        data = json.loads(payload["user"])
        counts = {"places": len(data["places"]), "evidence": len(data["evidence"]),
                  "pool_sizes": [len(s["options"]) for s in data["intervals"]]}
        try:
            receipt = prompt_budget.enforce(messages, payload["response_schema"],
                                            thinking=False, output_tokens=payload["max_tokens"])
            results.append({"case": case, **counts, "result": "fits", **receipt})
        except prompt_budget.PromptBudgetExceeded as error:
            results.append({"case": case, **counts, "result": "explicit fallback; no truncation", "detail": str(error)})
    print(json.dumps({"gpu_used": False, "inference_calls": 0, "provider_calls": 0, "cases": results}, indent=2))


if __name__ == "__main__":
    main()
