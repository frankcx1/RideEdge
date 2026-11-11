"""Bounded, isolated comparison of four public Eastside centers; never publishes scoring inputs.

Default: inspect saved research receipts. --fetch permits at most eight BestTime
filter requests (four typical/current-hour queries and four live-only queries).
Attempts are saved before requests; existing attempts are never retried. No new
venue forecasts/search jobs, Google requests, production writes or private origin.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from farol.besttime import BestTimeClient, save
from farol.env import load_env
from farol.zones import load_zones

AREA_IDS = ("kirkland_waterfront", "totem_lake_village", "redmond_downtown", "kirkland_rose_hill")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument(
        "--directory", type=Path, default=Path(".cache/research/eastside-2026-10-26")
    )
    args = parser.parse_args()
    load_env()
    centers = {p.id: p for p in load_zones().pickup_centers}
    client = (
        BestTimeClient(
            os.getenv("BESTTIME_API_KEY_PRIVATE", ""),
            os.getenv("BESTTIME_API_KEY_PUBLIC", ""),
            args.directory,
            budget=8,
        )
        if args.fetch
        else None
    )
    summaries = []
    for area_id in AREA_IDS:
        area = centers[area_id]
        for mode in ("typical", "live"):
            path = args.directory / f"{area_id}-{mode}.json"
            if not path.exists() and args.fetch:
                params = {
                    "lat": round(area.latitude, 4),
                    "lng": round(area.longitude, 4),
                    "radius": 1000,
                    "limit": 50,
                    "own_venues_only": "false",
                    "foot_traffic": "both",
                    "live" if mode == "live" else "now": "true",
                }
                if mode == "live":
                    # Provider docs describe both stored-live filtering and an
                    # optional refresh limit. Never allow its default bulk refresh.
                    params["live_limit"] = 0
                receipt = {
                    "area": area.label,
                    "mode": mode,
                    "parameters": params,
                    "attempted_at": datetime.now(UTC).isoformat(),
                    "state": "attempted",
                }
                save(path, receipt)
                receipt.update(client._request("GET", "/venues/filter", params))
                receipt.update(retrieved_at=datetime.now(UTC).isoformat(), state="completed")
                save(path, receipt)
            if not path.exists():
                summaries.append({"area": area.label, "mode": mode, "state": "not fetched"})
                continue
            receipt = json.loads(path.read_text(encoding="utf-8"))
            payload = receipt.get("payload", {})
            venues = payload.get("venues", [])
            summaries.append(
                {
                    "area": area.label,
                    "mode": mode,
                    "http_status": receipt.get("http_status"),
                    "provider_status": payload.get("status"),
                    "retrieved_at": receipt.get("retrieved_at"),
                    "venue_count": len(venues),
                    "response_keys": sorted(payload),
                    "sample_fields": sorted(venues[0]) if venues else [],
                    "names": [v.get("venue_name") for v in venues],
                }
            )
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
