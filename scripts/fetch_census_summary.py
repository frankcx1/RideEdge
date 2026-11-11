"""Account-free alternative: retain four official ACS summary tables and project King County.

--fetch permits four downloads, each bounded to 150 MB, never retried implicitly.
Default replays local files only. Does not write production feed caches.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

from farol.besttime import save
from farol.neighborhood import FIELDS, profile
from scripts.research_area_opportunities import AREA_IDS

BASE = "https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/"
TABLES = sorted({code.split("_")[0] for code in FIELDS.values()})


def project_tables(directory):
    fields = [code + suffix for code in FIELDS.values() for suffix in ("E", "M")]
    rows, provenance, retrievals = {}, {}, []
    for table in TABLES:
        path = directory / f"{table}.dat"
        meta_path = directory / f"{table}.receipt.json"
        if not path.exists() or not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("state") != "completed":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != meta.get("sha256"):
            raise ValueError("Summary table hash differs from retained receipt")
        retrievals.append(meta.get("retrieved_at"))
        columns = {
            f: f.split("_")[0] + "_" + f[-1] + f.split("_")[1][:-1]
            for f in fields
            if f.startswith(table + "_")
        }
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source, delimiter="|")
            if not {"GEO_ID", *columns.values()} <= set(reader.fieldnames or []):
                raise ValueError("Summary table schema changed")
            for line, row in enumerate(reader, 2):
                geoid = row.get("GEO_ID", "")
                if not geoid.startswith("1500000US53033") or len(geoid) != 21:
                    continue
                gid = geoid[9:]
                dest = rows.setdefault(
                    gid,
                    {
                        "state": gid[:2],
                        "county": gid[2:5],
                        "tract": gid[5:11],
                        "block group": gid[11:],
                    },
                )
                for field, column in columns.items():
                    dest[field] = row.get(column)
                    provenance[gid + ":" + field] = {
                        "file": path.name,
                        "line": line,
                        "column": column,
                        "receipt": meta_path.name,
                        "sha256": digest,
                    }
    header = ["state", "county", "tract", "block group", *fields]
    return {
        "http_status": 200,
        "basis": "projection from retained official summary tables",
        "retrieved_at": max((r for r in retrievals if r), default=None),
        "payload": [header, *[[r.get(k) for k in header] for _, r in sorted(rows.items())]],
        "field_provenance": provenance,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--directory", type=Path, default=Path(".cache/research/neighborhood-2024"))
    args = parser.parse_args()
    for table in TABLES:
        path = args.directory / f"{table}.dat"
        meta_path = args.directory / f"{table}.receipt.json"
        if not args.fetch or meta_path.exists():
            continue
        url = BASE + f"acsdt5y2024-{table.lower()}.dat"
        meta = {"url": url, "state": "attempted", "attempted_at": datetime.now(UTC).isoformat()}
        save(meta_path, meta)
        try:
            with urlopen(url, timeout=30) as response, path.open("xb") as target:
                digest, size = hashlib.sha256(), 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 150 * 1024 * 1024:
                        raise ValueError("Summary download exceeded 150 MB cap")
                    target.write(chunk)
                    digest.update(chunk)
            meta.update(
                state="completed",
                bytes=size,
                sha256=digest.hexdigest(),
                retrieved_at=datetime.now(UTC).isoformat(),
            )
        except (OSError, ValueError):
            meta.update(
                state="unavailable", error="Download failed or exceeded bound; no automatic retry"
            )
        save(meta_path, meta)
        print(
            json.dumps({"table": table, "state": meta["state"], "bytes": meta.get("bytes")}),
            flush=True,
        )
    acs = project_tables(args.directory)
    save(args.directory / "acs-summary-projection.json", acs)
    profiles = {}
    for aid in AREA_IDS:
        path = args.directory / f"{aid}-geography.json"
        geo = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        profiles[aid] = profile(
            geo, acs, geography_id=path.name, acs_id="acs-summary-projection.json"
        )
    save(args.directory / "summary-profiles.json", {"schema_version": 1, "areas": profiles})
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
