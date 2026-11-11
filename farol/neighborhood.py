"""Dated Census neighborhood context. No network or live-scoring side effects."""

from __future__ import annotations

import math

YEAR = 2024
TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_ACS2024/MapServer/10/query"
ACS = "https://api.census.gov/data/2024/acs/acs5"
FIELDS = {
    "population": "B01003_001",
    "housing_units": "B25024_001",
    "units_5_9": "B25024_006",
    "units_10_19": "B25024_007",
    "units_20_49": "B25024_008",
    "units_50_plus": "B25024_009",
    "households": "B08201_001",
    "households_no_vehicle": "B08201_002",
    "households_one_vehicle": "B08201_003",
    "median_household_income": "B19013_001",
}


def nonnegative(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None


def profile(geography_receipt, acs_receipt, *, geography_id, acs_id):
    """Summarize whole block groups intersecting a declared search envelope.

    No areal interpolation or claim that residents occupy the search circle.
    Preserve estimates and MOEs individually; median incomes are never averaged.
    """
    output = {
        "state": "unavailable",
        "basis": "structural estimate",
        "period": "2020-2024",
        "geography_vintage": YEAR,
        "block_groups": [],
        "metrics": {},
        "income_role": "descriptive only; zero scoring weight",
        "geography_method": "Whole block groups intersecting a 2 km by 2 km search envelope",
        "limitations": [
            "Footprint extends beyond the search envelope; not a population count within 1 km.",
            "Residents are not current visitors or waiting riders.",
            "ACS estimates describe 2020-2024, not present occupancy.",
            "Income medians remain per block group; no combined median is inferred.",
            "Density does not establish a probability of receiving a ride.",
        ],
    }
    geo = geography_receipt.get("payload") or {}
    raw = acs_receipt.get("payload")
    if (
        geography_receipt.get("http_status") != 200
        or acs_receipt.get("http_status") != 200
        or geo.get("error")
        or geo.get("exceededTransferLimit")
        or not isinstance(raw, list)
        or len(raw) < 2
    ):
        return output
    header = raw[0]
    required = {"state", "county", "tract", "block group"}
    if not isinstance(header, list) or not required <= set(header):
        return output
    records = {}
    for index, values in enumerate(raw[1:], 1):
        if not isinstance(values, list) or len(values) != len(header):
            continue
        row = dict(zip(header, values))
        geoid = "".join(str(row[k]) for k in ("state", "county", "tract", "block group"))
        records[geoid] = (index, row)
    seen = set()
    for feature_index, feature in enumerate(geo.get("features") or []):
        attr = feature.get("attributes") or {}
        geoid = attr.get("GEOID")
        if not geoid or geoid in seen:
            continue
        seen.add(geoid)
        index, row = records.get(geoid, (None, {}))
        fields = {}
        for name, code in FIELDS.items():
            fields[name] = {
                "estimate": nonnegative(row.get(code + "E")),
                "moe90": nonnegative(row.get(code + "M")),
                "provenance": {
                    "receipt": acs_id,
                    "row": index,
                    "estimate_field": code + "E",
                    "moe_field": code + "M",
                },
            }
            if name == "median_household_income" and fields[name]["estimate"] in (250001, 2499):
                fields[name].update(
                    estimate=None,
                    provider_estimate_code=row.get(code + "E"),
                    qualifier="Open-ended median code; not an exact dollar estimate",
                )
        output["block_groups"].append(
            {
                "geoid": geoid,
                "fields": fields,
                "land_sq_m": nonnegative(attr.get("AREALAND")),
                "geography_provenance": {
                    "receipt": geography_id,
                    "field": f"payload.features[{feature_index}].attributes",
                },
            }
        )
    groups = output["block_groups"]
    if not groups:
        return output

    def total(name):
        vals = [g["fields"][name]["estimate"] for g in groups]
        moes = [g["fields"][name]["moe90"] for g in groups]
        return {
            "estimate": sum(vals) if all(v is not None for v in vals) else None,
            "moe90_approx": math.sqrt(sum(v * v for v in moes))
            if all(v is not None for v in moes)
            else None,
            "inputs": [g["geoid"] + ":" + name for g in groups],
        }

    land = [g["land_sq_m"] for g in groups]
    land_total = sum(land) if all(v is not None and v > 0 for v in land) else None
    output["land_sq_m"] = land_total
    for name in FIELDS:
        if name != "median_household_income":
            output["metrics"][name] = total(name)
    for name in ("population", "housing_units"):
        value = output["metrics"][name]
        output["metrics"][name + "_per_land_sq_mile"] = {
            "estimate": value["estimate"] * 2589988.110336 / land_total
            if land_total and value["estimate"] is not None
            else None,
            "moe90_approx": value["moe90_approx"] * 2589988.110336 / land_total
            if land_total and value["moe90_approx"] is not None
            else None,
            "inputs": value["inputs"],
            "denominator": "sum of whole block group land areas",
        }
    output["state"] = (
        "available"
        if all(g["fields"]["population"]["estimate"] is not None for g in groups) and land_total
        else "partial"
    )
    output["retrieved_at"] = {
        "geography": geography_receipt.get("retrieved_at"),
        "acs": acs_receipt.get("retrieved_at"),
    }
    output["moe_note"] = (
        "Aggregate MOEs use square root of sum of squared MOEs; approximation ignores covariance."
    )
    return output
