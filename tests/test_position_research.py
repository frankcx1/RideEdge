import json

from scripts.research_seattle_positions import compact, encode_references


def test_model_encoding_roundtrips_evidence_and_preserves_nulls():
    timestamp = "2026-10-26T21:49:00-07:00"
    data = {
        "decision_time": timestamp,
        "areas": [
            {
                "id": "first",
                "route": {"minutes": 7.2},
                "coverage": [{"state": "available", "retrieved_at": timestamp, "returned": 20}],
                "venues": [["v1", "A", 0, None, False]],
            },
            {
                "id": "second",
                "route": {"minutes": 9.3},
                "coverage": [{"state": "unavailable", "retrieved_at": timestamp, "returned": 0}],
                "venues": [["v2", "B", None, 50, True]],
            },
        ],
        "signals": [["event-fixture-long-id", timestamp], ["event-fixture-long-id", timestamp]],
    }
    encoded = json.loads(encode_references(data))

    def decode(v):
        if isinstance(v, str):
            return encoded["string_refs"].get(v, v)
        if isinstance(v, list):
            return [decode(child) for child in v]
        if isinstance(v, dict):
            return {k: decode(child) for k, child in v.items()}
        return v

    result = decode(encoded["data"])
    columns = result.pop("area_columns")
    coverage_columns = result.pop("coverage_columns")
    result["areas"] = [
        {"id": aid, **dict(zip(columns, row))} for aid, row in result["areas"].items()
    ]
    for area in result["areas"]:
        area["coverage"] = [dict(zip(coverage_columns, row)) for row in area["coverage"]]
    assert result == data


def test_traffic_summaries_do_not_claim_route_impact_or_drop_events():
    event = {
        "id": "event",
        "kind": "event_exit",
        "basis": "scheduled",
        "starts_at": "a",
        "ends_at": "b",
        "fresh": True,
        "title": "Event",
        "timing_basis": "assumed duration",
        "location_basis": "provider event coordinates",
        "arrival_window": False,
    }
    highway = {**event, "id": "traffic", "kind": "highway_alert"}
    data = {"areas": [{"id": "one", "signals": [event, highway], "coverage": []}], "feeds": []}
    result = compact(data)
    assert result["areas"][0]["signal_refs"] == [["event", False]]
    assert result["areas"][0]["regional_traffic_alerts"]["count"] == 1
    assert result["signals"][0][0] == "event"
    assert result["signals"][0][7] == "assumed duration"
    assert data["areas"][0]["signals"] == [event, highway]
