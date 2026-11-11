"""CLI for a small BestTime coverage trial, independent of scoring and GPU use."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from farol.besttime import (
    BestTimeClient,
    normalize_forecast,
    normalize_live,
    now,
    save,
    venue_match,
)

ROOT = Path(__file__).resolve().parent.parent


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render_html(report: dict) -> str:
    def cell(value):
        return escape(str(value)) if value is not None else "Unknown"

    rows, profiles = [], []
    for item in report["venues"]:
        requested, forecast, live = item["requested"], item["forecast"], item["live"]
        days = forecast["days_available"] if item["identity_matched"] else 0
        rows.append("<tr>" + "".join(f"<td>{cell(value)}</td>" for value in (
            requested["name"], requested["area"], f"{days}/7 days",
            live.get("provider_current_localtime"),
            live.get("open_status"), live.get("busyness"), live.get("typical_this_hour"),
            live.get("delta_percentage_points"), item["note"],
        )) + "</tr>")
        friday = next((day for day in forecast["days"] if day["weekday"] == 4), None)
        if friday and item["identity_matched"]:
            hour_rows = []
            for hour in friday["hours"]:
                value = hour["typical_busyness"]
                status = "Closed" if hour["closed"] else cell(value)
                width = value if value is not None and not hour["closed"] else 0
                hour_rows.append(f'<tr><td>{cell(hour["label"])}</td><td>{status}</td>'
                                 f'<td><div class="bar" style="width:{width}%"></div></td></tr>')
            profiles.append(f'<details><summary>{cell(requested["name"])} — typical Friday'
                            '</summary><table><thead><tr><th>Local hour</th><th>Busyness</th>'
                            '<th>Relative to own weekly peak</th></tr></thead><tbody>'
                            + "".join(hour_rows) + '</tbody></table></details>')
    summary = report["summary"]
    return '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Farol · BestTime coverage pilot</title><style>
body{font:16px/1.5 system-ui,sans-serif;background:#10202b;color:#e9f1f5;margin:0;padding:32px}
main{max-width:1200px;margin:auto}h1{font-size:32px}p{max-width:950px}.scroll{overflow:auto}
table{border-collapse:collapse;width:100%;margin:16px 0}td,th{text-align:left;padding:10px;
border-bottom:1px solid #456}th{color:#a3e5de}details{background:#183341;padding:16px;margin:12px 0}
summary{cursor:pointer;font-weight:600}.bar{height:12px;background:#73cebe;min-width:0}
td:last-child{min-width:180px}.muted{color:#bacbd5}a{color:#a3e5de}</style><main>
<h1>BestTime coverage pilot</h1>''' + (
        f'<p class="muted">Captured {cell(report["started_at"])} to '
        f'{cell(report["finished_at"])} (UTC). Venue hours below use America/Los_Angeles.</p>'
        f'<p><strong>{summary["weekly_coverage"]}/{summary["sample_size"]} venues with '
        f'accepted weekly data; {summary["live_coverage"]}/{summary["sample_size"]} with '
        'live readings.</strong> Missing readings are unknown, not zero. This is a small '
        'selected sample, not neighborhood-wide coverage.</p>'
        f'<p>Forecast credits used: {cell(summary["forecast_credits_used"])}; remaining: '
        f'{cell(report["credits_after"].get("credits_forecast"))}. '
        f'Query credits used: {cell(summary["query_credits_used"])}. '
        f'Request reservation: {summary["reserved_credits"]}/{report["budget"]} credits.</p>'
        '<p>Busyness uses each venue’s own typical weekly peak of 100. Live values can '
        'exceed 100. The difference is in percentage points. These are neither visitor '
        'counts nor Uber demand. Typical Friday profiles describe historical patterns, '
        'not confirmed activity tonight.</p><div class="scroll"><table><thead><tr>'
        '<th>Venue</th><th>Area</th><th>Weekly coverage</th><th>Provider local time</th>'
        '<th>Open status</th>'
        '<th>Live</th><th>Typical now</th><th>Difference (pp)</th><th>Status</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'
        '<p class="muted">Retrieval times and provider current times are retained in report.json. '
        'The provider does not supply a documented measurement timestamp in these responses. '
        'A closed venue’s missing live reading does not establish its coverage when open.</p>'
        '<h2>Typical Friday through Saturday 5 a.m.</h2>' + "".join(profiles)
        + '<p>Source: <a href="https://documentation.besttime.app/#api-reference">'
        'BestTime API</a>. No automatic polling or decision-engine integration.</p></main></html>'
    )


def run(client: BestTimeClient, venues: list[dict], previous: dict | None = None) -> dict:
    directory = client.directory
    before_path = directory / "credits_before.json"
    if not before_path.exists():
        save(before_path, client.key_status())
    before = read(before_path)
    # Recheck on resume; the recorded starting balance is preserved for audit.
    current = client.key_status()
    if current.get("valid") is not True or current.get("active") is not True:
        raise ValueError("BestTime key is not valid and active; no forecast requests sent")
    remaining_reservation = client.budget - sum(r["reserved_credits"] for r in client.attempts())
    if (not isinstance(current.get("credits_forecast"), (int, float))
            or current["credits_forecast"] < remaining_reservation):
        raise ValueError("Insufficient trial credits for the selected request cap")
    report = {"started_at": before["retrieved_at"], "budget": client.budget,
              "credits_before": before, "venues": []}
    live_blocked = False
    old = {item["requested"]["id"]: item for item in previous["venues"]} if previous else {}
    seen_ids = set()
    for requested in venues:
        key = requested["id"]
        print(f'Checking {requested["name"]} ({requested["area"]})', flush=True)
        if key in old:
            forecast = old[key]["forecast"]
        else:
            receipt = client.fetch(key, "forecast", {"venue_name": requested["name"],
                                                     "venue_address": requested["address"]})
            forecast = normalize_forecast(receipt)
        info = forecast["venue"]
        matched = venue_match(requested, info)
        venue_id = info.get("venue_id")
        duplicate = bool(venue_id) and venue_id in seen_ids
        if venue_id:
            seen_ids.add(venue_id)
        accepted = matched and not duplicate and info.get("venue_timezone") == "America/Los_Angeles"
        live = {"available": False, "state": "not_requested"}
        note = "Venue identity/timezone requires review" if not accepted else "Live not requested"
        if not forecast["available"]:
            note = "Weekly forecast unavailable; live not checked"
            if forecast.get("provider_message"):
                note += ": " + str(forecast["provider_message"])
        if duplicate:
            note = "Duplicate provider venue ID; excluded"
        if accepted and venue_id and not live_blocked:
            receipt = client.fetch(key, "live", {"venue_id": venue_id})
            live = normalize_live(receipt, venue_id)
            note = live["state"].replace("_", " ")
            if receipt.get("http_status") in {401, 402, 403, 429}:
                live_blocked = True
                note = "Live endpoint blocked; further live requests stopped"
        elif live_blocked:
            note = "Live skipped after provider access/quota/rate-limit response"
        report["venues"].append({"requested": requested, "identity_matched": accepted,
                                  "forecast": forecast, "live": live, "note": note})
        save(directory / "progress.json", report)
    report["finished_at"] = now()
    report["credits_after"] = after = client.key_status()

    def used(key):
        a, b = before.get(key), after.get(key)
        return a - b if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None

    report["summary"] = {
        "sample_size": len(venues),
        "weekly_coverage": sum(v["identity_matched"] and v["forecast"]["available"]
                               for v in report["venues"]),
        "live_coverage": sum(v["live"]["available"] for v in report["venues"]),
        "forecast_credits_used": used("credits_forecast"),
        "query_credits_used": used("credits_query"),
        "reserved_credits": sum(r["reserved_credits"] for r in client.attempts()),
        "request_attempts": len(client.attempts()),
    }
    save(directory / "report.json", report)
    (directory / "report.html").write_text(render_html(report), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Reuse a directory to resume without retries")
    parser.add_argument("--budget", type=int, default=24, help="Maximum reserved credits, at most 24")
    parser.add_argument("--live-only-from", type=Path, help="Reuse weekly data from a previous report")
    args = parser.parse_args()
    from farol.env import load_env

    load_env()
    directory = args.output or ROOT / ".cache" / "besttime" / datetime.now(UTC).strftime(
        "%Y%m%dT%H%M%S%fZ")
    previous = read(args.live_only_from) if args.live_only_from else None
    venues = ([item["requested"] for item in previous["venues"]] if previous
              else read(ROOT / "fixtures" / "besttime_pilot.json")["venues"])
    if not 1 <= len(venues) <= 10 or len({v["id"] for v in venues}) != len(venues):
        parser.error("Use a panel of 1–10 distinct venues")
    manifest = {"venues": venues,
                "baseline_report": str(args.live_only_from.resolve()) if previous else None}
    manifest_path = directory / "panel.json"
    if manifest_path.exists() and read(manifest_path) != manifest:
        parser.error("Output directory belongs to a different panel/run mode")
    save(manifest_path, manifest)
    try:
        client = BestTimeClient(os.getenv("BESTTIME_API_KEY_PRIVATE", ""),
                               os.getenv("BESTTIME_API_KEY_PUBLIC", ""), directory, args.budget)
        report = run(client, venues, previous)
    except (ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {directory / 'report.html'}")


if __name__ == "__main__":
    main()
