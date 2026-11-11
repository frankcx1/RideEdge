import copy
import json
from unittest.mock import MagicMock, patch

import pytest

from farol.eval_local import cases, grade, models_url, run
from farol.local import local_model
from farol.local_models import profile
from farol.shift import start


def example(case):
    return {
        "headline": case["brief"]["shift_decision"]["action"],
        "spoken": "Watch WAMU theater access and the way out; hourly earnings are unknown.",
        "shift_rationale": "Review the signal; earnings are uncalibrated.",
        "now_move": "WATCH and review the window.",
        "risks": ["Pickup access is unverified."],
        "opportunity_notes": {},
    }


def test_selectable_profiles_and_unknown_profile_rejected():
    assert profile("gemma")["alias"] == "gemma-4-26b-a4b-ud-q4km"
    assert "UD-Q4_K_M" in profile("gemma")["gguf"]
    assert profile("qwen")["alias"] == "qwen3.8-27b"
    with pytest.raises(ValueError, match="unknown local model"):
        profile("anything")


def test_active_shift_alias_overrides_old_environment_alias():
    with (
        patch("farol.shift.active", return_value=True),
        patch("farol.shift.status", return_value={"phase": "driving", "model": profile("gemma")["alias"]}),
        patch.dict("os.environ", {"FAROL_LOCAL_MODEL": "qwen3.8-27b"}),
    ):
        assert local_model() == profile("gemma")["alias"]


def test_shift_launcher_receives_the_selected_profile():
    with patch("farol.shift._run_script", return_value={"ok": False}) as script:
        start(owner_pid=123, model_profile="gemma")
    assert script.call_args.args == ("start", ["-Model", "gemma", "-FarolPid", "123"])


def test_grader_rejects_fabricated_money_moves_and_unknown_ids():
    case = cases()[0]
    clean = example(case)
    assert grade(case, clean) == []
    bad = copy.deepcopy(clean)
    bad.update({"headline": "DRIVE NOW", "now_move": "MOVE to the curb for $90/hr"})
    bad["opportunity_notes"] = {"made-up-id": "Open curb"}
    assert "invented opportunity ID" in grade(case, bad)
    bad["opportunity_notes"] = {}
    problems = grade(case, bad)
    assert "changed engine headline action" in problems
    assert "dollar/hourly claim in narration" in problems
    assert "MOVE without approved navigation" in problems


def test_grader_checks_actual_structure_length_and_completion():
    case = cases()[0]
    assert grade(case, []) == ["response is not an object"]
    bad = example(case)
    bad["risks"] = "not an array"
    assert "invalid risks" in grade(case, bad)
    bad = example(case)
    bad["spoken"] = "word " * 46
    assert "spoken exceeds 45 words" in grade(case, bad, "length")
    assert "unfinished response: length" in grade(case, bad, "length")


def test_grader_rejects_changed_route_numbers():
    case = cases()[0]
    bad = example(case)
    bad["spoken"] = "WAMU theater access is unknown, but it is a 99 minute drive and a 42 mile reposition."
    assert "invented route minutes" in grade(case, bad)
    assert "invented route miles" in grade(case, bad)


def test_grader_allows_negated_guarantees_and_frozen_vehicle_cost():
    case = cases()[0]
    valid = example(case)
    valid["risks"] = ["Proximity does not guarantee a dispatch match."]
    valid["opportunity_notes"] = {case["id"]: "The vehicle cost is $1.80."}
    assert grade(case, valid) == []
    valid["risks"] = ["Proximity guarantees a dispatch match."]
    assert "unsupported driving/demand instruction" in grade(case, valid)


def test_grader_does_not_confuse_opportunity_and_concert_times():
    case = cases()[0]
    invalid = example(case)
    invalid["opportunity_notes"] = {case["id"]: "The event starts at 22:00."}
    assert "opportunity window described as event start" in grade(case, invalid)
    invalid["opportunity_notes"] = {case["id"]: "The exit window starts at 22:00."}
    assert grade(case, invalid) == []


def test_evaluator_will_not_send_cases_to_cydonia(tmp_path):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({"data": [{"id": "Cydonia"}]}).encode()
    with (
        patch("farol.eval_local.urlopen", return_value=response),
        patch("farol.eval_local.complete") as complete,
        pytest.raises(ValueError, match="no evaluation sent"),
    ):
        run("gemma", "http://127.0.0.1:1234/v1/chat/completions", tmp_path / "eval.json", 1)
    complete.assert_not_called()
    assert not (tmp_path / "eval.json").exists()


def test_model_preflight_uses_the_v1_models_endpoint():
    assert models_url("http://127.0.0.1:1234/v1/chat/completions") == "http://127.0.0.1:1234/v1/models"
    assert models_url("http://localhost:8901/prefix/v1/chat/completions/") == "http://localhost:8901/prefix/v1/models"
    with pytest.raises(ValueError, match="endpoint must end"):
        models_url("http://localhost:8901/anything")


def test_cases_cover_positioning_and_no_private_receipts():
    suite = cases()
    assert len({item["id"] for item in suite}) == 12
    assert {"circling_hypothesis", "fringe_hypothesis", "stadium_overlap"} <= {item["id"] for item in suite}
    assert "gross_earnings" not in json.dumps(suite)
