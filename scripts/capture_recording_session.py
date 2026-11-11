"""Capture a real, current evaluation once; never invent a shift or redate evidence.

Run with python -m scripts.capture_recording_session. Outputs stay local in .cache.
BestTime is paused in finally, including collection failure. No phone GPS is read.
"""
import argparse
import copy
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from farol.dashboard import ROOT
from farol.recording_capture import load_capture, observe_inference, seal


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def capture(area, besttime_requests=0):
    from farol import besttime_control, collect, decision_policy, radar, radar_api, studio, studio_monitor
    from farol.adapters.flightaware import seatac_6h_forecast
    from farol.besttime_live import poll_besttime_venues
    from farol.radar_contract import project, RadarView

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    folder = ROOT / ".cache/recording" / run_id
    folder.mkdir(parents=True)
    collection = {}
    try:
        if besttime_requests:
            besttime_control.configure(minutes=5, requests=besttime_requests)
            collection["besttime"] = poll_besttime_venues(area, max_venues=3)
        print("Refreshing configured source caches once", flush=True)
        collect.refresh_once()
    finally:
        collection["besttime_allowance_after"] = besttime_control.status()
        besttime_control.configure()
        write(folder / "collection.json", collection)
    snapshot, besttime = radar_api.read_inputs()
    write(folder / "evidence.json", {"awareness": snapshot, "besttime": besttime})
    origin = radar.origin(area)
    if origin["mode"] != "selected_area":
        raise ValueError("Recording capture requires an explicitly selected public area")
    view = radar.build(origin, snapshot, besttime)
    try:
        routes = radar_api._routes(view)
    except Exception as error:
        routes = {}
        collection["route_error_type"] = type(error).__name__
    view = radar.build(origin, snapshot, besttime, routes=routes)
    write(folder / "deterministic.json", view)
    write(folder / "routes.json", routes)
    print("Evaluating the real evidence with local Qwen", flush=True)
    with observe_inference() as receipts:
        try:
            answer = radar.ask_model(view)
        finally:
            write(folder / "inference.json", receipts)
    if answer.get("qwen", {}).get("state") != "ready":
        raise ValueError("No validated model result; incomplete receipts retained, no replay published")
    write(folder / "answer.json", answer)
    at = datetime.now(UTC)
    public = project(answer, at)
    public["scheduler"] = {"state": "preview", "next_review_at": None, "session_expires_at": None}
    public["refreshing"] = False
    RadarView.model_validate(public)
    health = collect.feed_health_view(at)
    for feed in health.get("feeds", []):
        feed["role"] = studio.SOURCE_ROLES.get(feed["adapter"], "Additional source context")
    details = {f["adapter"]: collect.feed_detail_view(f["adapter"], at) for f in health["feeds"]}
    airport = seatac_6h_forecast(pull=False)
    runtime = studio_monitor.snapshot()
    runtime["performance"] = {"samples": [r["metric"] for r in reversed(receipts)], "retained_count": len(receipts)}
    runtime["telemetry_scope"] = "Recorded capture process; model samples belong to this evaluation. Scheduler is not the live service."
    dashboard = studio.studio_data()
    dashboard.update(mode="captured", observed_at=at.isoformat(), runtime=runtime, health=health,
                     capture_id=run_id, snapshot_id=public["snapshot_id"])
    dashboard["decision"].update(audit=answer.get("decision_audit"), activity_coverage=answer.get("activity_coverage"),
                                generated_at=answer["generated_at"], scope="Captured evaluation; original timestamps retained")
    status = {"backend": "recorded", "qwen": answer["qwen"], "evidence_generated_at": answer["generated_at"],
              "qwen_loaded": runtime["model"].get("loaded"), "model_server_reachable": runtime["model"].get("reachable"),
              "collector": runtime["collector"], "recorded_at": at.isoformat()}
    cues = [{"scene": 0, "shot": shot, "title": title, "seconds": 20} for shot, title in [
        ("now", "The next move"), ("why", "Evidence behind the recommendation"),
        ("alternatives", "Compare supported options"), ("nearby", "Nearby activity"),
        ("plan", "Six-hour outlook"), ("comparison", "Actual algorithm and Qwen comparison"),
        ("sources", "Source coverage"), ("source_detail", "Retained source observations")]]
    stage = {"radar": public, "health": health, "status": status, "seatac": airport, "source_details": details,
             "short_title": area + " · recorded evaluation", "title": "Captured evaluation", "story": ""}
    package = seal({"schema_version": 1, "kind": "captured_session", "capture_id": run_id,
                    "captured_at": at.isoformat(), "synthetic": False, "title": "RideEdge feature walkthrough",
                    "provenance": {"kind": "captured_session", "live_inference": True,
                                   "location_basis": "Selected public area; not a recorded trip",
                                   "policy_sha256": decision_policy.load()["sha256"]},
                    "stages": [stage], "cues": cues, "studio": dashboard})
    write(folder / "captured-session.json", package)
    load_capture(folder / "captured-session.json")
    write(ROOT / ".cache/recording/selected.json", {"capture_id": run_id})
    print(json.dumps({"capture_id": run_id, "path": str(folder / "captured-session.json"),
                      "snapshot_id": public["snapshot_id"], "validation": answer.get("decision_audit", {}).get("validation"),
                      "now": [p["name"] for p in public["now"]], "besttime": besttime_control.status()["state"]}), flush=True)
    return folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--area", default="Kirkland")
    parser.add_argument("--besttime-requests", type=int, choices=range(0, 13), default=0)
    args = parser.parse_args()
    from farol.env import load_env
    load_env()
    capture(args.area, args.besttime_requests)
