"""RideEdge / UberTRAC — Seattle & Eastside Repositioning Test Plan & Harness.

Usage:
    python scripts/reposition_test_plan.py
    python scripts/reposition_test_plan.py --max-drive 25 --finish-near Home
    python scripts/reposition_test_plan.py --area "Ballard" --max-drive 20
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_LOCATIONS: list[tuple[str, str, float, float]] = [
    ("Public Totem Lake reference", "Home", 47.711, -122.179),
    ("Totem Lake (Zone)", "totem_lake", 47.7160, -122.1800),
    ("Village at Totem Lake (Curb)", "Village at Totem Lake", 47.7145, -122.1795),
    ("Kirkland Waterfront", "kirkland_waterfront", 47.6769, -122.2060),
    ("Redmond Downtown", "redmond_downtown", 47.6740, -122.1215),
    ("Bellevue Core", "bellevue_core", 47.6155, -122.2015),
    ("Woodinville Wine", "woodinville_wine", 47.7543, -122.1587),
    ("Downtown Seattle", "seattle_core", 47.6101, -122.3344),
    ("Capitol Hill", "capitol_hill", 47.6145, -122.3208),
    ("South Lake Union", "south_lake_union", 47.6231, -122.3384),
    ("Queen Anne / Arena", "queen_anne", 47.6221, -122.3540),
    ("Ballard", "ballard", 47.6687, -122.3847),
    ("University District", "u_district", 47.6606, -122.3148),
    ("Sea-Tac Airport", "sea_airport", 47.4480, -122.3088),
]


def run_reposition_suite(
    base_url: str = "http://127.0.0.1:8787",
    max_drive_minutes: int = 15,
    finish_near: str | None = None,
    single_area: str | None = None,
) -> list[dict]:
    sys.stdout.reconfigure(encoding="utf-8")
    locs = (
        [(single_area, single_area, 0.0, 0.0)]
        if single_area
        else DEFAULT_LOCATIONS
    )
    results: list[dict] = []
    for label, area, lat, lon in locs:
        qs = urllib.parse.urlencode({"at": area, "max_reposition_minutes": max_drive_minutes})
        with urllib.request.urlopen(f"{base_url}/api/here?{qs}", timeout=15) as r:
            here = json.loads(r.read().decode("utf-8"))
        course_req: dict = {
            "area": area,
            "reposition_under_minutes": max_drive_minutes,
            "pull_all": False,
        }
        if finish_near:
            course_req["finish_near"] = finish_near
        body = json.dumps(course_req).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/ask/course",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            course = json.loads(r.read().decode("utf-8"))

        card = here["stay_or_move_card"]
        s0 = course["stops"][0]
        s1 = course["stops"][1] if len(course["stops"]) > 1 else {}
        aligned = (
            card.get("action") == s0.get("action")
            and card.get("decision_state") == s0.get("decision_state")
            and card.get("destination_id") == s0.get("destination_id")
        )
        row = {
            "label": label,
            "input_area": area,
            "resolved_zone": here["place"]["zone"],
            "origin_kind": card.get("origin_kind"),
            "now_action": card.get("action"),
            "now_state": card.get("decision_state"),
            "now_basis": card.get("recommendation_basis"),
            "now_dest_id": card.get("destination_id"),
            "now_dest_label": card.get("destination_label"),
            "now_headline": card.get("headline"),
            "now_reason": card.get("reason"),
            "plan0_action": s0.get("action"),
            "plan0_state": s0.get("decision_state"),
            "plan0_basis": s0.get("recommendation_basis"),
            "plan0_zone": s0.get("zone"),
            "plan0_dest_id": s0.get("destination_id"),
            "plan0_dest_label": s0.get("destination_label"),
            "plan0_trigger": s0.get("primary_trigger"),
            "plan1_zone": s1.get("zone"),
            "plan1_action": s1.get("action"),
            "aligned": aligned,
        }
        results.append(row)
        print(
            f"{label:28s} | NOW: {row['now_action']:4s}/{row['now_state']:4s} -> {row['now_dest_id']:20s} "
            f"| PLAN0: {row['plan0_action']:4s}/{row['plan0_state']:4s} -> {row['plan0_dest_id']:20s} | ALIGN={aligned}"
        )
        print(f"   NOW   : {row['now_headline']} — {row['now_reason']}")
        print(f"   PLAN0 : {row['plan0_trigger']}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RideEdge Seattle repositioning test suite.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--max-drive", type=int, default=15)
    parser.add_argument("--finish-near", default=None)
    parser.add_argument("--area", default=None)
    parser.add_argument(
        "--out",
        default="review/argon-remediation-round7/seattle-repositioning-14-matrix.json",
    )
    args = parser.parse_args()
    rows = run_reposition_suite(
        base_url=args.base_url,
        max_drive_minutes=args.max_drive,
        finish_near=args.finish_near,
        single_area=args.area,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
