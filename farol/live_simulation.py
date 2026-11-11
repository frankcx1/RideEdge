"""Seattle location simulations: capture real feeds once, replay offline, evaluate locally.

py -3.11 -m farol.live_simulation capture
py -3.11 -m farol.live_simulation replay --snapshot PATH
Use beast/test-local-model.ps1 -SimulationSnapshot PATH to borrow/restore Gemma.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import inspect
import json
import os
import re
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from time import perf_counter
from urllib.request import urlopen

from farol.adapters import gather_signals
from farol.adapters import routes as google_routes
from farol.brain import LOCAL_SYSTEM_PROMPT, _public_brief, constrain_narration
from farol.dashboard import FIXTURES, ROOT
from farol.env import load_env
from farol.eval_local import grade, models_url
from farol.here import advise, resolve
from farol.local import DEFAULT_URL, complete, generation_settings
from farol.local_models import profile
from farol.narration_contract import narration_issues
from farol.signals import Anchor, RouteEstimate, Signal, load_anchors
from farol.tonight import ScoringSnapshot, brief_from_scored, score_window

POINTS = [
    ("sodo", "SODO / WAMU district", "47.5914,-122.3325"),
    ("sodo_edge", "South edge of stadium district", "47.5810,-122.3340"),
    ("capitol_hill", "Capitol Hill", "47.6230,-122.3200"),
    ("seattle_center", "Seattle Center", "47.6220,-122.3540"),
    ("downtown", "Downtown Seattle", "47.6100,-122.3370"),
    ("fremont", "Fremont / Ballard reference point", "47.6620,-122.3500"),
    ("uw", "UW / Montlake", "47.6504,-122.3015"),
    ("bellevue", "Bellevue comparison", "47.6150,-122.2010"),
    ("sea", "SEA airport comparison", "47.4500,-122.3090"),
]
SCOPE = (
    "Simulated public locations, captured real feeds, production Python scoring and HERE. "
    "The selected local model narrates the top three opportunities using the production prompt and guard. "
    "HERE itself remains deterministic; this does not enable model narration in the running dashboard. "
    "No rides, driver supply, request rate, dispatch matches, or future profit are simulated. "
    "Reference coordinates are not approved pickup or parking locations."
)


def safe_text(value: str) -> str:
    """Defense in depth for adapter errors and URLs before saving reports/prompts."""
    for name, secret in os.environ.items():
        if len(secret) >= 8 and re.search(r"KEY|TOKEN|SECRET|PASSWORD|ACCESSCODE", name, re.IGNORECASE):
            value = value.replace(secret, "REDACTED")
    return re.sub(
        r"([?&](?:key|api_?key|accesscode|token|client_secret|client_id)=)[^&\s\"<>]+",
        r"\1REDACTED", value, flags=re.IGNORECASE,
    )


def save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(safe_text(json.dumps(payload, indent=2, ensure_ascii=False)) + "\n", encoding="utf-8")


def capture(directory: Path) -> Path:
    """One bounded collection, including the normally on-demand airport source."""
    load_env()
    directory.mkdir(parents=True, exist_ok=False)
    settings = {"MOCK_FEEDS": "0", "FAROL_GROK_BLOCK": "1",
                "FAROL_CACHE_DIR": str((directory / "feed-cache").resolve())}
    previous = {key: os.environ.get(key) for key in settings}
    os.environ.update(settings)
    started = datetime.now().astimezone()
    path = directory / "snapshot.json"
    try:
        print("Capturing all configured adapters, including public research and SEA arrivals...", flush=True)
        signals, feeds = gather_signals(started, started + timedelta(hours=3),
                                       include_llm=True, include_on_demand=True)
        anchors = load_anchors(FIXTURES / "anchors.json")
        snapshot = {
            "version": 1, "capture_started_at": started.isoformat(),
            "capture_finished_at": None, "as_of": started.isoformat(), "hours": 3,
            "vehicle_cost_per_mile": 0.45, "scope": SCOPE,
            "signals": [asdict(row) for row in signals], "feeds": feeds,
            "anchors": [asdict(row) for row in anchors], "locations": [],
            "route_elements_requested": len(POINTS) * len(anchors),
        }
        save(path, snapshot)
        for feed in feeds:
            print(json.dumps({key: feed.get(key) for key in ("adapter", "mode", "signal_count")}), flush=True)
        for ident, label, pin in POINTS:
            place = resolve(pin)
            routes, status = google_routes.matrix(
                place["zone"], place["latitude"], place["longitude"], anchors,
                snapshot["vehicle_cost_per_mile"], started.isoformat(),
            )
            snapshot["locations"].append({
                "id": ident, "label": label, "pin": pin, "place": place,
                "routes": {key: asdict(value) for key, value in routes.items()},
                "route_status": status.public(),
            })
            save(path, snapshot)
            print(f"Routes {ident}: {status.mode}, {len(routes)}/{len(anchors)} legs", flush=True)
        snapshot["capture_finished_at"] = datetime.now().astimezone().isoformat()
        save(path, snapshot)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return path


def build_cases(snapshot: dict) -> list[dict]:
    """All replay paths inject captured inputs; no feed or routing API is called."""
    if snapshot.get("version") != 1 or not snapshot.get("capture_finished_at"):
        raise ValueError("A complete version-1 snapshot is required")
    current = datetime.fromisoformat(snapshot["as_of"])
    signals = [Signal(**row) for row in snapshot["signals"]]
    anchors = [Anchor(**row) for row in snapshot["anchors"]]
    cases = []
    for location in snapshot["locations"]:
        cases.append(_case(snapshot, location, signals, anchors, "baseline", current))
    # Controlled faults affect captured inputs, never the production cache.
    for variant in ("traffic_outage", "all_sources_outage", "missed_windows"):
        cases.append(_case(snapshot, snapshot["locations"][0], signals, anchors, variant, current))
    return cases


def _case(snapshot: dict, location: dict, signals: list[Signal], anchors: list[Anchor],
          variant: str, current: datetime) -> dict:
    routes = {key: RouteEstimate(**row) for key, row in location["routes"].items()}
    feeds = [*snapshot["feeds"], location["route_status"]]
    changes = "Only location is simulated. Feed timestamps and traffic are captured observations."
    if variant == "traffic_outage":
        routes = {}
        feeds = [*snapshot["feeds"], {**location["route_status"], "mode": "error",
                 "signal_count": 0, "detail": "SIMULATED traffic API outage"}]
        changes = "Controlled fault: remove all traffic legs; production falls back to assumed distance estimates."
    elif variant == "all_sources_outage":
        signals, routes = [], {}
        feeds = [{**row, "mode": "error", "signal_count": 0,
                  "detail": "SIMULATED complete source outage"} for row in feeds]
        changes = "Controlled fault: remove every signal and traffic leg; this is not tonight's observed state."
    elif variant == "missed_windows":
        signals = [replace(row, starts_at=(current - timedelta(minutes=45)).isoformat(),
                           ends_at=(current - timedelta(minutes=1)).isoformat(),
                           expires_at=(current - timedelta(minutes=1)).isoformat(),
                           basis="assumed") for row in signals]
        changes = "Controlled fault: every signal window is moved into the past; original titles are retained as test data."
    place = location["place"]
    scored = score_window(
        current=current, hours=snapshot["hours"],
        vehicle_cost_per_mile=snapshot["vehicle_cost_per_mile"],
        origin_zone=place["zone"], origin_lat=place["latitude"], origin_lon=place["longitude"],
        snapshot=ScoringSnapshot(signals, feeds, anchors, routes),
    )
    # Fixed empty receipt cohort makes replay portable and avoids persisting driver history.
    here = advise(location["pin"], now=current, trips=[], scored_window=scored)
    brief = brief_from_scored(scored, include_personal=False)
    full_opportunities = brief["opportunities"]
    top = scored["ranked"][:3]
    brief["opportunities"] = top
    brief["ranked_opportunity_ids"] = [row["id"] for row in top]
    brief["watch"] = brief["watch"][:3]
    brief["warnings"] += [
        f"Location simulation: {location['label']} ({place['zone']}). {changes}",
        (f"Narration shows the top {len(top)} of {len(full_opportunities)} opportunities. "
         "HERE street/airport filtering is separate from this signal briefing."),
        "No private receipt history is used in this replay; the HERE receipt board has zero samples.",
    ]
    payload = _public_brief(brief, local=True)
    required = []
    if variant == "traffic_outage":
        required = [r"(?:traffic|travel|route|drive).{0,60}(?:unknown|estimated|assumed|unavailable)|(?:estimated|assumed|unknown).{0,60}(?:traffic|travel|route|drive)"]
    elif variant == "all_sources_outage":
        required = [r"unavailable|outage|missing"]
    elif variant == "missed_windows":
        required = [r"passed|expired|missed|ended|after.*window"]
    if place["zone"] == "sea_airport":
        required += [r"queue|FIFO", r"unknown|unavailable|cannot|can't"]
    return {
        "id": f"{location['id']}-{variant}", "label": location["label"], "variant": variant,
        "pin": location["pin"], "zone": place["zone"], "changes": changes,
        "brief": brief, "required_any": required, "check_claim_contract": True, "here": here,
        "all_opportunities": full_opportunities,
        "prompt_payload": payload,
        "prompt_characters": len(json.dumps(payload)),
        "engine_checks": {
            "unique_opportunity_ids": len({row['id'] for row in full_opportunities}) == len(full_opportunities),
            "no_unapproved_navigation": all(
                not row["navigation_available"] or row["anchor"]["approval_status"] == "approved"
                for row in full_opportunities),
            "no_hourly_forecasts": all(row["expected_net_per_hour"] is None for row in full_opportunities),
            "expired_windows_avoided": all(
                row["action"] == "AVOID" for row in full_opportunities
                if datetime.fromisoformat(row["ends_at"]) < current),
        },
    }


def replay(path: Path) -> dict:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    return {
        "scope": SCOPE, "snapshot": str(path.resolve()),
        "snapshot_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "capture_started_at": snapshot["capture_started_at"],
        "capture_finished_at": snapshot["capture_finished_at"],
        "capture_updates": snapshot.get("capture_updates", []),
        "code_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                        for name in ("farol/live_simulation.py", "farol/tonight.py", "farol/here.py",
                                     "farol/brain.py", "farol/eval_local.py", "farol/narration_contract.py")},
        "feeds": snapshot["feeds"], "route_elements_requested": snapshot["route_elements_requested"],
        "cases": build_cases(snapshot), "results": [],
    }


def select_case(report: dict, case_id: str) -> dict:
    cases = [case for case in report["cases"] if case["id"] == case_id]
    if not cases:
        raise ValueError(f"Unknown simulation case: {case_id}")
    return {**report, "cases": cases, "case_filter": case_id}


def evaluate(report: dict, name: str, endpoint: str, repeats: int, output: Path) -> dict:
    selected = profile(name)
    with urlopen(models_url(endpoint), timeout=5) as response:
        loaded = json.load(response)
    if selected["alias"] not in [row["id"] for row in loaded.get("data", [])]:
        raise ValueError(f"Expected {selected['alias']}; the expected model is not loaded")
    report.update({
        "profile": selected, "evaluated_at": datetime.now(UTC).isoformat(),
        "generation_settings": generation_settings(name),
        "prompt_sha256": hashlib.sha256(LOCAL_SYSTEM_PROMPT.encode()).hexdigest(),
        "grader_sha256": hashlib.sha256(inspect.getsource(grade).encode()).hexdigest(),
        "timing_basis": "Full HTTP response wall time; warm server and prompt caching may affect timings.",
    })
    for repeat in range(repeats):
        for case in report["cases"]:
            start = perf_counter()
            row = {"case": case["id"], "repeat": repeat + 1}
            try:
                payload, _, _ = complete(
                    system=LOCAL_SYSTEM_PROMPT, user=safe_text(json.dumps(case["prompt_payload"])),
                    cache_key="location-simulation-no-cache", endpoint=endpoint,
                    model_name=selected["alias"], model_profile=name,
                )
                choice = payload["choices"][0]
                raw = choice["message"]["content"]
                row.update({"raw_content": raw, "finish_reason": choice.get("finish_reason"),
                            "usage": payload.get("usage"), "timings": payload.get("timings"),
                            "reasoning_present": bool(choice["message"].get("reasoning_content") or choice["message"].get("reasoning")),
                            "reasoning_characters": len(choice["message"].get("reasoning_content") or choice["message"].get("reasoning") or "")})
                blob = json.loads(raw)
                row["errors"] = grade(case, blob, choice.get("finish_reason", "unknown"))
                if isinstance(blob, dict):
                    row["semantic_errors"] = narration_issues(case["brief"], blob)
                    row["guarded"] = constrain_narration(case["brief"], blob)
                    row["guarded_errors"] = grade(case, row["guarded"])
                    row["guard_changed_fields"] = [key for key in row["guarded"]
                                                   if row["guarded"][key] != blob.get(key)]
            except Exception as error:  # noqa: BLE001 — retain failures and proceed to restoration
                row["errors"] = [safe_text(f"{type(error).__name__}: {error}")]
            row["seconds"] = round(perf_counter() - start, 3)
            row["passed"] = not row["errors"]
            report["results"].append(row)
            save(output, report)
            print(json.dumps({key: row[key] for key in ("case", "repeat", "seconds", "passed", "errors")}), flush=True)
    times = [row["seconds"] for row in report["results"]]
    report["summary"] = {
        "passed": sum(row["passed"] for row in report["results"]), "total": len(times),
        "median_seconds": round(median(times), 3), "max_seconds": max(times),
        "guarded_passed": sum(not row.get("guarded_errors", ["no guarded result"]) for row in report["results"]),
        "guard_interventions": sum(bool(row.get("guard_changed_fields")) for row in report["results"]),
        "engine_check_failures": [case["id"] + ": " + key for case in report["cases"]
                                  for key, passed in case["engine_checks"].items() if not passed],
    }
    save(output, report)
    return report


def render(report: dict, output: Path) -> None:
    """Self-contained, escaped HTML: no CDNs, model HTML, keys, or network calls."""
    esc = lambda value: html.escape(safe_text(str(value)), quote=True)
    feeds = "".join(
        f"<tr><td>{esc(row['adapter'])}</td><td>{esc(row['mode'])}</td>"
        f"<td>{esc(row['signal_count'])}</td><td>{esc(row.get('fetched_at') or '—')}</td>"
        f"<td>{esc(row.get('detail', ''))}</td></tr>" for row in report["feeds"])
    cards = []
    for case in report["cases"]:
        decision = case["brief"]["shift_decision"]
        opportunities = "".join(
            f"<tr><td>{esc(row['zone'])}<br><small>{esc(row.get('venue_name') or '')}</small></td>"
            f"<td>{esc(row['action'])}</td><td>{row['score']:.2f}</td>"
            f"<td>{row['route']['traffic_minutes']:g} min / {row['route']['distance_miles']:g} mi<br>"
            f"<small>{esc(row['route']['basis'])}</small></td></tr>"
            for row in sorted(case["all_opportunities"], key=lambda item: item["score"], reverse=True))
        runs = []
        for result in report["results"]:
            if result["case"] != case["id"]:
                continue
            try:
                raw = json.loads(result.get("raw_content", "{}"))
            except ValueError:
                raw = {}
            runs.append(
                f"<div class='run'><h3>{esc(report.get('profile', {}).get('label', 'Local model'))} · run {result['repeat']} · {result['seconds']}s</h3>"
                f"<p class='{'good' if result['passed'] else 'bad'}'>"
                f"{'Automated checks passed — semantic review still needed' if result['passed'] else esc('; '.join(result['errors']))}</p>"
                + (f"<p class='bad'><b>Manual review:</b> {esc('; '.join(result['review_issues']))}</p>"
                   if result.get("review_issues") else "") +
                f"<blockquote>{esc(raw.get('spoken') or result.get('raw_content', 'No response'))}</blockquote>"
                f"<p><b>Guarded spoken:</b> {esc(result.get('guarded', {}).get('spoken', 'Unavailable'))}</p>"
                f"<p><b>Guard changed:</b> {esc(', '.join(result.get('guard_changed_fields', [])) or 'none')}</p>"
                f"<p><b>Guarded checks:</b> {esc('; '.join(result.get('guarded_errors', ['unavailable'])) or 'passed')}</p>"
                f"<details><summary>Complete response, guard, and timing</summary><pre>{esc(json.dumps(result, indent=2))}</pre></details></div>")
        failed = [key for key, passed in case["engine_checks"].items() if not passed]
        cards.append(
            f"<article data-variant='{esc(case['variant'])}'><div class='eyebrow'>{esc(case['variant'].replace('_', ' '))}</div>"
            f"<h2>{esc(case['label'])}</h2><p>{esc(case['pin'])} · {esc(case['zone'])}</p>"
            f"<p>{esc(case['changes'])}</p><div class='decision'>{esc(decision['action'])}"
            f"<span>{esc(decision.get('best_zone') or 'No qualifying signal')}</span></div>"
            f"<p>{esc(decision['explanation'])}</p><p>Engine checks: {esc(', '.join(failed) if failed else 'passed')}</p>"
            f"<details><summary>Production HERE response · {esc(case['here']['action'])} · no receipt history</summary>"
            f"<p>{esc(case['here']['spoken'])}</p></details>"
            + ''.join(runs) +
            f"<details><summary>All {len(case['all_opportunities'])} engine opportunities</summary>"
            f"<div class='scroll'><table><thead><tr><th>Zone / venue</th><th>Action</th><th>Score</th><th>Route</th></tr></thead>"
            f"<tbody>{opportunities}</tbody></table></div></details>"
            f"<details><summary>Exact model input · {case['prompt_characters']:,} characters</summary>"
            f"<pre>{esc(json.dumps(case['prompt_payload'], indent=2))}</pre></details></article>")
    summary = report.get("summary")
    summary_text = (f"{summary['passed']}/{summary['total']} narration checks · median {summary['median_seconds']}s"
                    if summary else "Engine replay ready · local model has not run yet")
    if report.get("manual_review"):
        summary_text += f" · {report['manual_review']['flagged_responses']} responses flagged in manual review"
    if summary and "guarded_passed" in summary:
        summary_text += f" · {summary['guarded_passed']}/{summary['total']} after guard"
    document = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Farol · Seattle simulation lab</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#101820;color:#e8edf2;font:16px/1.55 system-ui,sans-serif}
main{max-width:1150px;margin:auto;padding:32px 22px}h1{font-size:clamp(30px,5vw,48px);line-height:1.1}h2{margin:8px 0;font-size:24px}h3{font-size:17px}
.eyebrow{color:#7ed9c0;text-transform:uppercase;font-size:12px;letter-spacing:1.5px}.muted,small{color:#a4b8c8}.intro{max-width:900px}
.banner,article{background:#192631;border:1px solid #314655;border-radius:14px;padding:24px;margin:20px 0}.banner{border-left:4px solid #77d6b5}
.decision{font-weight:750;font-size:22px;color:#8ee3c4}.decision span{display:block;font-size:15px;font-weight:400;color:#b1c7d5}
button{background:#233d4b;color:#eef6fc;border:1px solid #56717f;padding:10px 16px;border-radius:8px;margin:4px;cursor:pointer}button[aria-pressed=true]{background:#a0e6cd;color:#102b25}
details{border-top:1px solid #304653;padding:14px 0}summary{cursor:pointer;color:#c3d9e8}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#101a22;padding:16px;border-radius:8px}
blockquote{margin:14px 0;border-left:3px solid #79c9e1;padding-left:18px;color:#e0f2ff;font-size:18px}.run{margin:18px 0;padding:16px;background:#13222c;border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;padding:10px;border-bottom:1px solid #304653;vertical-align:top;overflow-wrap:anywhere}.scroll{overflow-x:auto}.good{color:#9be2bf}.bad{color:#ffb5a7}[hidden]{display:none!important}
@media(max-width:600px){main{padding:20px 12px}article,.banner{padding:16px}table{min-width:530px}}
</style><main><div class="eyebrow">Farol / stationary test lab</div><h1>Seattle, without the drive.</h1>"""
    document += (f"<p class='intro'>{esc(SCOPE)}</p><div class='banner'><b>{esc(summary_text)}</b>"
                 f"<p>Captured {esc(report['capture_started_at'])} through {esc(report['capture_finished_at'])}. "
                 f"These observations describe that capture, not conditions when this report is reopened.</p>"
                 f"<p>{len({case['label'] for case in report['cases']})} locations shown · "
                 f"{sum(case['variant'] != 'baseline' for case in report['cases'])} controlled fault cases · "
                 f"{report['route_elements_requested']} route elements requested in the full capture. "
                 "No simulated rides or earnings.</p></div>"
                 "<details><summary>Source audit — live, cached, static, and unavailable are distinct</summary><div class='scroll'>"
                 "<table><thead><tr><th>Adapter</th><th>State</th><th>Signals</th><th>Fetched</th><th>Detail</th></tr></thead>"
                 f"<tbody>{feeds}</tbody></table></div></details>"
                 "<nav aria-label='Scenario filter'><button aria-pressed='true' data-filter='all'>All scenarios</button>"
                 "<button aria-pressed='false' data-filter='baseline'>Captured conditions</button>"
                 "<button aria-pressed='false' data-filter='fault'>Controlled faults</button></nav>" + ''.join(cards) +
                 "<details><summary>Capture corrections and reproducibility</summary>"
                 f"<pre>{esc(json.dumps({key: report.get(key) for key in ('snapshot_sha256', 'code_sha256', 'capture_updates')}, indent=2))}</pre></details>"
                 "<p class='muted'>Automated checks catch structural errors and selected unsupported claims; they do not prove factual completeness or forecast quality. "
                 "Route snapshots were fetched sequentially. Scores are heuristics, not probabilities or hourly earnings.</p></main>"
                 "<script>document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));"
                 "document.querySelectorAll('article').forEach(c=>{c.hidden=!(b.dataset.filter==='all'||(b.dataset.filter==='baseline'?c.dataset.variant==='baseline':c.dataset.variant!=='baseline'))})});</script></html>")
    output.write_text(document, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["capture", "replay", "evaluate"])
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--profile", choices=["gemma", "qwen"], default="gemma")
    parser.add_argument("--endpoint", default=DEFAULT_URL)
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=1)
    parser.add_argument("--case", help="evaluate/replay only this saved scenario ID")
    args = parser.parse_args()
    if args.command == "capture":
        directory = args.directory or ROOT / ".cache" / "simulations" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = capture(directory)
    elif args.snapshot:
        path = args.snapshot
    else:
        parser.error("--snapshot is required for replay/evaluate")
    report = replay(path)
    if args.case:
        report = select_case(report, args.case)
    suffix = f"{args.profile}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}" if args.command == "evaluate" else "replay"
    output = path.parent / f"{suffix}.json"
    if args.command == "evaluate":
        report = evaluate(report, args.profile, args.endpoint, args.repeats, output)
    save(output, report)
    render(report, output.with_suffix(".html"))
    print(json.dumps({"snapshot": str(path), "report": str(output.with_suffix('.html')), "summary": report.get("summary")}), flush=True)
    if report.get("summary") and (report["summary"]["passed"] != report["summary"]["total"] or report["summary"]["engine_check_failures"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
