import copy
from datetime import UTC, datetime, timedelta

import pytest

from farol import position_contract as pc

AT = datetime(2026, 10, 27, 4, 49, tzinfo=UTC)


def inputs():
    source = {
        "decision_time": AT.isoformat(),
        "origin": {"label": "Synthetic"},
        "signal_columns": [
            "id",
            "kind",
            "title",
            "starts_at",
            "ends_at",
            "fresh",
            "location_basis",
        ],
        "signals": [
            [
                "future",
                "event_exit",
                "Future event",
                (AT + timedelta(hours=1)).isoformat(),
                (AT + timedelta(hours=2)).isoformat(),
                True,
                "provider event coordinates",
            ]
        ],
        "areas": [],
    }
    briefs = []
    for aid, mins in (("a", 5), ("b", 10)):
        source["areas"].append(
            {"id": aid, "straight_line_miles": 1, "signal_refs": [["future", False]]}
        )
        briefs.append(
            {
                "id": aid,
                "name": aid.upper(),
                "route": {
                    "minutes": mins,
                    "basis": "Google traffic-aware",
                    "fetched_at": AT.isoformat(),
                },
                "venues": [
                    {
                        "id": aid + "-venue",
                        "name": aid + " dining",
                        "type": "RESTAURANT",
                        "live_percent": 40,
                        "live_retrieved_at": AT.isoformat(),
                        "typical_percent_at_arrival": 50,
                        "typical_retrieved_at": AT.isoformat(),
                        "scheduled_open_at_arrival": True,
                        "provenance": {
                            "live": {"receipt": "live.json"},
                            "typical": {"receipt": "weekly.json"},
                        },
                    }
                ],
            }
        )
    return source, briefs


def fixture():
    source, briefs = inputs()
    ledger = pc.build(source, briefs, enabled=True)
    choice = {
        "selected_area": "a",
        "alternative_area": "b",
        "support_ids": ledger["areas"]["a"]["eligible_support"],
        "alternative_support_ids": ledger["areas"]["b"]["eligible_support"],
        "primary_reason": "live_activity",
        "uncertainty_codes": ["pickup_demand_unknown", "sparse_live_coverage"],
        "recheck_on": "new_live_activity",
    }
    return ledger, choice


def test_explicit_gate_and_future_watch_cannot_support_now():
    source, briefs = inputs()
    with pytest.raises(ValueError):
        pc.build(source, briefs)
    ledger, choice = fixture()
    assert ledger["watch"][0]["id"] == "future"
    assert not any("future" in e for e in ledger["evidence"])
    card = pc.validate(ledger, choice, now=AT)
    assert card["travel_difference_minutes"] == -5
    assert "40%" in card["verified_facts"][0]
    assert card["action"] == "move"


@pytest.mark.parametrize(
    "failure",
    [
        "extra_probability",
        "same_alternative",
        "wrong_area_citation",
        "false_shorter",
        "unsupported_reason",
        "missing_uncertainty",
        "invented_uncertainty",
        "duplicate_citations",
    ],
)
def test_invalid_model_judgments_are_rejected(failure):
    ledger, choice = fixture()
    if failure == "extra_probability":
        choice["ride_probability"] = 0.9
    elif failure == "same_alternative":
        choice["alternative_area"] = "a"
    elif failure == "wrong_area_citation":
        choice["support_ids"] = choice["alternative_support_ids"]
    elif failure == "false_shorter":
        choice.update(
            selected_area="b",
            alternative_area="a",
            primary_reason="shorter_travel",
            support_ids=choice["alternative_support_ids"],
            alternative_support_ids=choice["support_ids"],
        )
    elif failure == "unsupported_reason":
        choice["primary_reason"] = "event_timing"
    elif failure == "missing_uncertainty":
        choice["uncertainty_codes"] = ["sampling_incomplete", "sparse_live_coverage"]
    elif failure == "invented_uncertainty":
        choice["uncertainty_codes"] = ["pickup_demand_unknown", "event_end_estimated"]
    else:
        choice["support_ids"] *= 2
    with pytest.raises(ValueError):
        pc.validate(ledger, choice, now=AT)


def test_expiry_and_algorithm_fallback_do_not_silently_repair_model_choice():
    ledger, valid = fixture()
    invalid = {**valid, "rationale": "invented demand"}
    result = pc.validate_or_fallback(ledger, invalid, valid, now=AT)
    assert result["selection_source"] == "algorithm_fallback"
    assert "Wrong decision shape" in result["model_rejection"]
    with pytest.raises(ValueError):
        pc.validate_or_fallback(ledger, invalid, valid, now=AT + timedelta(minutes=16))


@pytest.mark.parametrize(
    "failure", ["closed", "zero", "outside_radius", "invalid_radius", "stale_route", "stale_both"]
)
def test_ineligible_evidence_cannot_create_supported_area(failure):
    source, briefs = inputs()
    v = briefs[0]["venues"][0]
    if failure == "closed":
        v["scheduled_open_at_arrival"] = False
    elif failure == "zero":
        v["live_percent"] = 0
    elif failure == "outside_radius":
        source["areas"][0]["straight_line_miles"] = 5.01
    elif failure == "invalid_radius":
        source["areas"][0]["straight_line_miles"] = float("nan")
    elif failure == "stale_route":
        briefs[0]["route"]["fetched_at"] = (AT - timedelta(minutes=11)).isoformat()
    else:
        v["live_retrieved_at"] = v["typical_retrieved_at"] = (AT - timedelta(days=30)).isoformat()
    ledger = pc.build(source, briefs, enabled=True)
    assert "a" not in ledger["eligible_areas"]


def test_model_projection_preserves_all_eligible_support_and_live_counterevidence():
    ledger, choice = fixture()
    before = copy.deepcopy(ledger)
    data, aliases = pc.model_data(ledger)
    assert ledger == before
    assert len(data["evidence"]) == 2
    assert data["areas"]["a"]["eligible_support"] == [aliases[choice["support_ids"][0]]]
    assert "provenance" not in str(data)  # retained in ledger; not a model decision factor


def test_empty_evidence_requires_honest_insufficient_result():
    source, briefs = inputs()
    for b in briefs:
        b["venues"] = []
    ledger = pc.build(source, briefs, enabled=True)
    choice = {
        "selected_area": "none",
        "alternative_area": "none",
        "support_ids": [],
        "alternative_support_ids": [],
        "primary_reason": "insufficient_evidence",
        "uncertainty_codes": ["pickup_demand_unknown"],
        "recheck_on": "new_live_activity",
    }
    assert pc.validate(ledger, choice, now=AT)["state"] == "insufficient_evidence"


def test_single_option_stay_and_provenance():
    source, briefs = inputs()
    source["areas"] = source["areas"][:1]
    briefs = briefs[:1]
    briefs[0]["route"]["minutes"] = 0
    ledger = pc.build(source, briefs, enabled=True)
    _, choice = fixture()
    choice.update(alternative_area="none", alternative_support_ids=[])
    assert pc.validate(ledger, choice, now=AT)["action"] == "stay_nearby"
    evidence = ledger["evidence"][choice["support_ids"][0]]
    assert evidence["provider_venue_id"] == "a-venue"
    assert evidence["provenance"] == {"receipt": "live.json"}
    assert evidence["measurement_time"] is None


def test_event_timing_is_rechecked_after_inference():
    source, briefs = inputs()
    source["signals"][0][3:5] = [AT.isoformat(), (AT + timedelta(minutes=16)).isoformat()]
    ledger = pc.build(source, briefs, enabled=True)
    _, choice = fixture()
    choice.update(support_ids=["a:future"], primary_reason="event_timing")
    assert pc.validate(ledger, choice, now=AT)["state"] == "validated"
    with pytest.raises(ValueError, match="Event window no longer fits"):
        pc.validate(ledger, choice, now=AT + timedelta(minutes=2))


@pytest.mark.parametrize("kind", ["live", "traffic"])
def test_support_expiring_during_review_is_rejected(kind):
    ledger, choice = fixture()
    if kind == "live":
        ledger["evidence"][choice["support_ids"][0]]["fetched_at"] = (
            AT - timedelta(minutes=54)
        ).isoformat()
    else:
        ledger["areas"]["a"]["route_fetched_at"] = (AT - timedelta(minutes=9)).isoformat()
    pc.validate(ledger, choice, now=AT)
    with pytest.raises(ValueError, match="expired"):
        pc.validate(ledger, choice, now=AT + timedelta(minutes=2))
