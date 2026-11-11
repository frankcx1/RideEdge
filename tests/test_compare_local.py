import copy

import pytest

from farol.compare_local import compare, render
from farol.live_simulation import select_case


@pytest.fixture
def reports():
    base = {
        "snapshot_sha256": "snapshot", "prompt_sha256": "prompt", "grader_sha256": "grader",
        "code_sha256": {"farol/narration_contract.py": "guard", "farol/brain.py": "brain"},
        "cases": [{"id": ident, "prompt_payload": {"route": 13}, "required_any": [],
                   "check_claim_contract": True} for ident in ("seattle", "airport")],
        "results": [{"case": ident, "repeat": repeat, "errors": [], "reasoning_present": False}
                    for repeat in (1, 2) for ident in ("seattle", "airport")],
        "summary": {"total": 4, "passed": 4, "guarded_passed": 4, "guard_interventions": 0,
                    "median_seconds": 5, "max_seconds": 6},
        "profile": {"id": "first", "label": "First"}, "generation_settings": {},
    }
    second = copy.deepcopy(base)
    second["profile"] = {"id": "second", "label": "Second"}
    second["generation_settings"] = {"enable_thinking": True}
    for row in second["results"]:
        row["reasoning_present"] = True
    return [base, second]


def test_same_inputs_allow_different_models_and_reasoning_settings(reports):
    result = compare(reports)
    assert [row["reasoning_observed"] for row in result["models"]] == [0, 4]
    assert result["models"][1]["generation_settings"]["enable_thinking"]


@pytest.mark.parametrize("changed", ["snapshot", "prompt", "guard", "payload"])
def test_comparison_refuses_changed_evidence_or_checks(reports, changed):
    if changed in {"snapshot", "prompt"}:
        reports[1][f"{changed}_sha256"] = "different"
    elif changed == "guard":
        reports[1]["code_sha256"]["farol/narration_contract.py"] = "different"
    else:
        reports[1]["cases"][0]["prompt_payload"]["route"] = 99
    with pytest.raises(ValueError, match="identical"):
        compare(reports)


@pytest.mark.parametrize("mutation", ["unequal", "both_missing", "duplicate", "no_summary", "bad_total"])
def test_comparison_refuses_incomplete_or_mismatched_runs(reports, mutation):
    if mutation == "unequal":
        reports[1]["results"].pop()
    else:
        for report in reports:
            if mutation == "both_missing":
                report["results"].pop()
            elif mutation == "duplicate":
                report["results"].append(copy.deepcopy(report["results"][0]))
            elif mutation == "no_summary":
                del report["summary"]
            else:
                report["summary"]["total"] = 10
    with pytest.raises(ValueError):
        compare(reports)


def test_comparison_report_escapes_untrusted_model_labels(reports, tmp_path):
    reports[0]["profile"]["label"] = '<script>alert("bad")</script>'
    path = tmp_path / "comparison.html"
    render(compare(reports), path)
    document = path.read_text(encoding="utf-8")
    assert "<script>" not in document
    assert "&lt;script&gt;" in document


def test_focused_selection_preserves_full_original_report(reports):
    original = copy.deepcopy(reports[0])
    focused = select_case(reports[0], "airport")
    assert [row["id"] for row in focused["cases"]] == ["airport"]
    assert reports[0] == original
    with pytest.raises(ValueError, match="Unknown simulation case"):
        select_case(reports[0], "typo")
