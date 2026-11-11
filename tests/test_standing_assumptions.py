import copy
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from farol import collect, radar
from farol.adapters import situational_waves
from scripts.check_radar_prompt_budget import capture_request

NOW = datetime(2026, 10, 27, 2, 0, tzinfo=UTC)


def legacy_hospital():
    return {"id": "standing-hospital", "source": situational_waves.SOURCE,
            "kind": "special_event", "zone": "seattle_core", "basis": "scheduled",
            "magnitude": 12000, "fetched_at": NOW.isoformat(),
            "starts_at": (NOW-timedelta(minutes=15)).isoformat(),
            "ends_at": (NOW+timedelta(minutes=45)).isoformat(),
            "expires_at": (NOW+timedelta(minutes=45)).isoformat(),
            "details": {"title": "Hospital shift-change wave", "venue": "Fixture hospital",
                        "notes": "Unverified old claim about departing riders"}}


def test_new_standing_rules_are_assumptions_without_passenger_magnitudes():
    start = NOW.astimezone(radar.PACIFIC)
    records = situational_waves.parse(start, start+timedelta(hours=8), fetched_at=NOW.isoformat())
    assert records
    assert all(r.basis == "assumed" and r.magnitude == 0 for r in records)
    assert all(r.details["title"].startswith("Unverified local assumption:") for r in records)
    transit = [r for r in records if r.kind == "transit_disruption"]
    assert transit and all(r.details["context_only"] for r in transit)
    assert all(situational_waves.review_record(asdict(r)) == asdict(r) for r in records)


def test_retained_false_schedule_is_corrected_without_changing_raw_input():
    original = legacy_hospital()
    saved = copy.deepcopy(original)
    checked = situational_waves.review_record(original)
    assert original == saved
    assert checked["basis"] == "assumed" and checked["magnitude"] == 0
    assert checked["details"]["assumption_review"]["reported_basis"] == "scheduled"
    assert checked["details"]["assumption_review"]["reported_magnitude"] == 12000
    assert situational_waves.review_record(checked) == checked
    foreign = {**original, "source": "fixture:dated-schedule"}
    assert situational_waves.review_record(foreign) == foreign


def test_phone_and_qwen_receive_best_guess_not_a_scheduled_hospital_wave():
    view = radar.build(radar.origin("Seattle Center"), {"signals": [legacy_hospital()]}, {}, now=NOW)
    row = next(r for r in view["nearby"] if r["id"] == "signal:standing-hospital")
    assert row["strength"] == "Best guess"
    assert row["evidence"][0]["basis"] == "assumed"
    prompt = json.loads(capture_request(view)["user"])
    prompt["evidence"] = {eid: dict(zip(prompt["evidence_layouts"][row[0]], row[1:], strict=True))
                          for eid, row in prompt["evidence"].items()}
    evidence = [e for e in prompt["evidence"].values()
                if prompt["sources"].get(e["source"]) == situational_waves.SOURCE]
    assert evidence and all(e["basis"] == "assumed" for e in evidence)
    assert all(e["text"].startswith("Unverified local assumption:") for e in evidence)
    transit = {**legacy_hospital(), "kind": "transit_disruption"}
    excluded = radar.build(radar.origin("Seattle Center"), {"signals": [transit]}, {}, now=NOW)
    assert all(r["id"] != "signal:standing-hospital" for s in excluded["plan"] for r in s["options"])
    assert any(e["code"] == "context_only" for e in excluded["excluded"])


def test_source_detail_discloses_correction_and_preserves_reported_values(tmp_path):
    original = legacy_hospital()
    path = tmp_path / "awareness_snapshot.json"
    path.write_text(json.dumps({"signals": [original]}), encoding="utf-8")
    saved = path.read_bytes()
    health = {"feeds": [{"adapter": situational_waves.NAME, "label": "Local assumptions", "category": "context"}]}
    with patch.object(collect, "feed_health_view", return_value=health), \
            patch("farol.adapters.base.cache_dir", return_value=tmp_path):
        report = collect.feed_detail_view(situational_waves.NAME, NOW)
    record = report["records"][0]
    assert record["basis"] == "assumed"
    assert "not a dated schedule" in record["detail"]
    assert record["assumption_review"]["reported_title"] == original["details"]["title"]
    assert path.read_bytes() == saved
