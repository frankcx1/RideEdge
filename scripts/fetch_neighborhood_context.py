"""Fetch public Census context for four commercial centers, never the driver's location.

Default offline. --fetch permits five GETs maximum: four fixed-vintage geography
queries and one county ACS table. Each attempt is retained before dispatch, raw
responses preserved, existing attempts never retried. No production publication.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from farol.besttime import save
from farol.neighborhood import ACS, FIELDS, TIGER, profile
from farol.zones import load_zones
from scripts.research_area_opportunities import AREA_IDS


def receipt(path, endpoint, params, fetch):
    if path.exists():
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("endpoint") != endpoint or result.get("parameters") != params:
            raise ValueError("Existing receipt has different parameters; choose a new directory")
        return result
    if not fetch:
        return {}
    result = {
        "endpoint": endpoint,
        "parameters": params,
        "state": "attempted",
        "attempted_at": datetime.now(UTC).isoformat(),
    }
    save(path, result)
    try:
        req = Request(
            endpoint + "?" + urlencode(params),
            headers={"User-Agent": "RideEdge-neighborhood-research/1"},
        )
        with urlopen(req, timeout=25) as response:
            result["http_status"] = response.status
            result["raw_text"] = response.read().decode("utf-8")
    except HTTPError as exc:
        result.update(http_status=exc.code, raw_text=exc.read().decode("utf-8", errors="replace"))
    except (URLError, OSError, TimeoutError):
        result.update(error="Transport unavailable", http_status=None)
    try:
        result["payload"] = json.loads(result.get("raw_text", ""))
    except ValueError:
        result["payload"] = None
    result.update(state="completed", retrieved_at=datetime.now(UTC).isoformat())
    save(path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--directory", type=Path, default=Path(".cache/research/neighborhood-2024"))
    args = parser.parse_args()
    centers = {p.id: p for p in load_zones().pickup_centers}
    fields = [code + suffix for code in FIELDS.values() for suffix in ("E", "M")]
    acs = receipt(
        args.directory / "acs-king.json",
        ACS,
        {
            "get": ",".join(["NAME", *fields]),
            "for": "block group:*",
            "in": "state:53 county:033 tract:*",
        },
        args.fetch,
    )
    profiles = {}
    for aid in AREA_IDS:
        center = centers[aid]
        dy = 1000 / 111320
        dx = dy / math.cos(math.radians(center.latitude))
        params = {
            "f": "json",
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "geometry": ",".join(
                str(v)
                for v in (
                    center.longitude - dx,
                    center.latitude - dy,
                    center.longitude + dx,
                    center.latitude + dy,
                )
            ),
            "spatialRel": "esriSpatialRelIntersects",
            "returnGeometry": "false",
            "outFields": "GEOID,AREALAND",
            "where": "STATE='53' AND COUNTY='033'",
        }
        geo = receipt(args.directory / f"{aid}-geography.json", TIGER, params, args.fetch)
        profiles[aid] = profile(
            geo, acs, geography_id=f"{aid}-geography.json", acs_id="acs-king.json"
        )
    save(args.directory / "profiles.json", {"schema_version": 1, "areas": profiles})
    print(
        json.dumps(
            {
                aid: {
                    "state": p["state"],
                    "block_groups": len(p["block_groups"]),
                    "density": p["metrics"].get("population_per_land_sq_mile"),
                }
                for aid, p in profiles.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
