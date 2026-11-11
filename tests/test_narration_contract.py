import copy
import json
from unittest.mock import MagicMock, patch

import pytest

from farol.brain import _cache_key, _public_brief, constrain_narration
from farol.local import complete
from farol.narration_contract import contract, duration_text, narration_issues


@pytest.fixture
def brief():
    items = []
    for ident, venue, start, end in (
        ("paramount", "Paramount Theatre", "22:30", "23:15"),
        ("chop", "Chop Suey", "23:00", "23:45"),
    ):
        items.append({"id": ident, "zone": "capitol_hill", "venue_name": venue,
                      "starts_at": f"2026-09-17T{start}:00-07:00",
                      "ends_at": f"2026-09-17T{end}:00-07:00",
                      "action": "WATCH", "navigation_available": False,
                      "route": {"traffic_minutes": 13, "distance_miles": 3.1,
                                "vehicle_cost": 1.4, "basis": "live"},
                      "facts": [], "audit": {"missed_window": False}})
    return {"as_of": "2026-09-17T21:39:00-07:00", "opportunities": items,
            "ranked_opportunity_ids": ["paramount", "chop"], "feeds": [],
            "shift_decision": {"action": "CHECK WINDOW", "best_zone": "capitol_hill",
                               "earnings_status": "uncalibrated", "explanation": "Review the later signal window."}}


def valid_narration(brief):
    claims = contract(brief)
    return {"headline": "CHECK WINDOW", "spoken": claims["fallback_spoken"],
            "shift_rationale": brief["shift_decision"]["explanation"], "now_move": "WATCH",
            "risks": claims["required_risks"],
            "opportunity_notes": {key: value["window"] for key, value in claims["opportunities"].items()}}


@pytest.mark.parametrize("bad", [
    "Paramount's exit is based on a 3:00 PM show plus a 45-minute exit wave.",
    "The concert starts at three pm.",
    "Paramount Theatre and Chop Suey exit between 10:30 PM and 11:15 PM.",
    "Chop Suey starts at 22:30.",
    "Current traffic is unknown.",
    "Travel times are estimated and traffic is unknown.",
    "The streets have heavy traffic and the route is a 99 minute drive.",
])
def test_wrong_time_or_route_claim_is_replaced_in_every_field(brief, bad):
    narration = valid_narration(brief)
    narration.update({"spoken": bad, "shift_rationale": bad, "now_move": bad,
                      "opportunity_notes": {"paramount": bad}, "risks": [bad]})
    assert narration_issues(brief, narration)
    guarded = constrain_narration(brief, narration)
    assert not narration_issues(brief, guarded)
    assert bad not in json.dumps(guarded)
    assert guarded["now_move"] == "WATCH"
    assert guarded["headline"] == "CHECK WINDOW"


def test_correct_clock_for_other_venue_is_still_wrong(brief):
    narration = valid_narration(brief)
    narration["opportunity_notes"]["chop"] = contract(brief)["opportunities"]["paramount"]["window"]
    assert "opportunity_notes.chop" in narration_issues(brief, narration)
    guarded = constrain_narration(brief, narration)
    assert "Chop Suey" in guarded["opportunity_notes"]["chop"]
    assert "11:00 pm to 11:45 pm" in guarded["opportunity_notes"]["chop"]


def test_checked_separate_windows_and_live_traffic_survive(brief):
    narration = valid_narration(brief)
    assert narration_issues(brief, narration) == {}
    assert constrain_narration(brief, narration) == narration
    assert "captured traffic-aware" in narration["spoken"]
    assert "unknown" not in narration["spoken"]


@pytest.mark.parametrize("changed", ["route_basis", "window_end"])
def test_evidence_changes_invalidate_narration_cache_even_when_scores_match(brief, changed):
    original = _cache_key(brief)
    if changed == "route_basis":
        brief["opportunities"][0]["route"]["basis"] = "assumed"
    else:
        brief["opportunities"][0]["ends_at"] = "2026-09-18T00:15:00-07:00"
    assert _cache_key(brief) != original


def test_missing_uncertainty_is_added_and_live_claim_rejected(brief):
    brief["opportunities"][0]["route"]["basis"] = "assumed"
    brief["opportunities"][0]["zone"] = "sea_airport"
    brief["opportunities"][0]["venue_name"] = "SEA"
    narration = valid_narration(brief)
    narration["spoken"] = "SEA: captured traffic-aware route is 13 minutes."
    narration["risks"] = []
    guarded = constrain_narration(brief, narration)
    assert narration_issues(brief, guarded) == {}
    assert any("current traffic is unknown" in row for row in guarded["risks"])
    assert any("queue and waiting time are unknown" in row for row in guarded["risks"])
    assert len(guarded["spoken"].split()) <= 45


def test_midnight_windows_keep_both_dates(brief):
    brief["opportunities"][0]["ends_at"] = "2026-09-18T00:15:00-07:00"
    sentence = contract(brief)["opportunities"]["paramount"]["window"]
    assert "Sep 17" in sentence and "Sep 18 12:15 am" in sentence


def test_duration_strings_never_resemble_wall_clock():
    assert duration_text("assumed 3:00:00 show + 0:45:00 exit wave") == "assumed 180 minutes show + 45 minutes exit wave"
    assert duration_text("assumed 2:10:00 game + 0:45:00 exit wave") == "assumed 130 minutes game + 45 minutes exit wave"


def test_prompt_contract_and_guard_do_not_mutate_engine_or_send_receipts(brief):
    before = copy.deepcopy(brief)
    payload = _public_brief(brief, local=True)
    assert payload["narration_contract"]["version"] == "checked-claims-v1"
    constrain_narration(brief, valid_narration(brief))
    assert brief == before
    assert "receipts" not in json.dumps(payload)


@pytest.mark.parametrize("profile,thinking,budget", [("gemma", False, 0), ("qwen", True, 1024)])
def test_request_uses_selected_reasoning_settings(profile, thinking, budget):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"choices": []}'
    with patch("farol.local.urlopen", return_value=response) as post, \
         patch("farol.prompt_budget.enforce", return_value={"input_tokens": 10}):
        complete(system="test", user="{}", cache_key="test", model_name=profile, model_profile=profile)
    body = json.loads(post.call_args.args[0].data)
    assert body["chat_template_kwargs"]["enable_thinking"] is thinking
    assert body["reasoning_budget"] == budget
    assert body["max_tokens"] > budget + 700
