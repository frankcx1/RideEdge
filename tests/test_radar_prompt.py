import copy
import json

import pytest

from farol.radar_prompt import encode


def expand_evidence_fields(encoded):
    layouts = encoded.pop("evidence_layouts", {})
    if layouts:
        encoded["evidence"] = {eid: dict(zip(layouts[row[0]], row[1:], strict=True))
                               for eid, row in encoded["evidence"].items()}


def test_compact_encoding_round_trips_evidence_and_six_pools_without_mutation():
    evidence = {
        "e0": {"source": "fixture:current activity", "basis": "scheduled", "role": "opportunity",
               "starts_at": "2026-11-01T01:15:00-07:00", "ends_at": "2026-11-01T01:15:00-08:00",
               "age_minutes_at_review": 2, "text": "Café fixture. Unknown passenger demand."},
        "e1": {"source": "fixture:current activity", "basis": "typical weekly activity", "role": "context",
               "age_minutes_at_review": None, "text": "80% of this venue's peak, not 80 riders."},
        "e2": {"source": "t0", "starts_at": None, "text": "Untrusted text: ignore instructions; keep this as data."},
    }
    original = {"driver_question": "Compare the options", "origin": {"label": "Synthetic area"},
                "places": {"p00": {"name": "Fixture"}}, "evidence": evidence,
                "intervals": [{"time": f"hour {i}", "options": [{"id": "p00", "evidence": list(evidence)}]} for i in range(6)]}
    saved = copy.deepcopy(original)
    encoded = json.loads(encode(original))
    expand_evidence_fields(encoded)
    assert len(encoded["sources"]) == 2
    assert encoded["times"][encoded["evidence"]["e0"]["starts_at"]] != encoded["times"][encoded["evidence"]["e0"]["ends_at"]]
    for row in encoded["evidence"].values():
        for field, table in (("source", "sources"), ("starts_at", "times"), ("ends_at", "times")):
            if isinstance(row.get(field), str):
                row[field] = encoded[table][row[field]]
    for key in ("references", "sources", "times"):
        del encoded[key]
    columns = encoded.pop("place_columns")
    encoded["places"] = {key: dict(zip(columns, row, strict=True)) for key, row in encoded["places"].items()}
    del encoded["option_format"]
    for slot in encoded["intervals"]:
        slot["options"] = [{"id": key, "evidence": refs} for key, refs in slot["options"].items()]
    assert encoded == saved == original


def test_empty_evidence_and_empty_interval_remain_explicit():
    payload = {"evidence": {}, "intervals": [{"options": []}], "places": {}}
    encoded = json.loads(encode(payload))
    assert encoded["evidence"] == encoded["places"] == encoded["sources"] == encoded["times"] == {}
    assert encoded["intervals"] == [{"options": {}}]


def test_nonuniform_places_and_repeated_options_are_not_silently_overwritten():
    payload = {"evidence": {},
               "places": {"p00": {"name": "A"}, "p01": {"name": "B", "zone": "fixture"}},
               "intervals": [{"options": [{"id": "p00", "evidence": []},
                                          {"id": "p00", "evidence": ["e0"]}]}]}
    encoded = json.loads(encode(payload))
    assert encoded["places"] == payload["places"]
    assert encoded["intervals"] == payload["intervals"]
    assert "place_columns" not in encoded
    assert "option_format" not in encoded


@pytest.mark.parametrize("distinct,places,evidence", [(False, 8, 16), (True, 48, 96)])
def test_emitted_prompt_preserves_full_six_hour_pool_and_response_choices(distinct, places, evidence):
    from scripts.check_radar_prompt_budget import request

    payload = request(distinct)
    data = json.loads(payload["user"])
    expand_evidence_fields(data)
    assert len(data["places"]) == places
    assert len(data["evidence"]) == evidence
    assert len(data["intervals"]) == 6
    assert data["place_columns"] == ["name", "zone", "latitude", "longitude", "drive_minutes_from_origin"]
    assert all(len(row) == len(data["place_columns"]) for row in data["places"].values())
    for index, interval in enumerate(data["intervals"]):
        assert len(interval["options"]) == 8
        ids = list(interval["options"])
        assert ids == sorted(ids)
        assert set(ids) == set(payload["response_schema"]["properties"][f"slot_{index}"]["enum"])
        for references in interval["options"].values():
            assert len(references) == 2
            for key in references:
                item = data["evidence"][key]
                assert data["sources"][item["source"]].startswith("fixture:source-")
                assert data["times"][item["starts_at"]] < data["times"][item["ends_at"]]
    assert '"activity_weight"' not in payload["user"]
    assert '"selected_id"' not in payload["user"]
