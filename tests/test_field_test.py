from pathlib import Path

import pytest

from farol.dashboard import friday_window_split
from farol.field_test import ACTIONS, POLICY_VERSION, FieldTestStore


def test_friday_split_reports_executed_path_lower_bounds() -> None:
    afternoon, evening = friday_window_split(0.45)

    assert afternoon["label"] == "AFTERNOON"
    assert afternoon["trips"] == 10
    assert afternoon["net_per_committed_hour_lower_bound"] == 24.55
    assert evening["label"] == "FRIDAY ANCHOR"
    assert evening["trips"] == 8
    assert evening["net_per_committed_hour_lower_bound"] == 18.95


def test_shadow_window_conceals_recommendation_until_choice(tmp_path: Path) -> None:
    store = FieldTestStore(tmp_path)

    concealed = store.start(driver_zone="kirkland", vehicle_cost=0.45, decision_index=0)

    assert concealed["policy_version"] == POLICY_VERSION
    assert concealed["policy_frozen"] is True
    assert concealed["learning_enabled"] is False
    assert "recommendation" not in concealed["model_snapshot"]

    revealed = store.choose(concealed["session_id"], "WAIT")

    assert revealed["driver_choice"]["action"] == "WAIT"
    assert revealed["model_snapshot"]["recommendation"]["action"] in ACTIONS
    with pytest.raises(ValueError, match="already locked"):
        store.choose(concealed["session_id"], "MOVE")


def test_only_compliant_observable_advice_is_gradeable(tmp_path: Path) -> None:
    store = FieldTestStore(tmp_path)
    concealed = store.start(driver_zone="kirkland", vehicle_cost=0.45, decision_index=0)
    active = store.choose(concealed["session_id"], "ROAM")
    recommendation = active["model_snapshot"]["recommendation"]["action"]
    store.add_event(concealed["session_id"], "OFFER_DECLINED")

    complete = store.finish(
        concealed["session_id"], actual_action=recommendation, observable=True
    )

    assert complete["status"] == "COMPLETE"
    assert complete["observability"] == "OBSERVABLE"
    assert complete["advice_gradeable"] is True


def test_override_cannot_grade_farol(tmp_path: Path) -> None:
    store = FieldTestStore(tmp_path)
    concealed = store.start(driver_zone="kirkland", vehicle_cost=0.45, decision_index=0)
    active = store.choose(concealed["session_id"], "WAIT")
    recommendation = active["model_snapshot"]["recommendation"]["action"]
    override = next(action for action in ACTIONS if action != recommendation)

    complete = store.finish(concealed["session_id"], actual_action=override, observable=True)

    assert complete["advice_gradeable"] is False


def test_early_finish_defaults_to_driver_choice_and_sampler_is_conservative(
    tmp_path: Path,
) -> None:
    store = FieldTestStore(tmp_path)
    concealed = store.start(driver_zone="kirkland", vehicle_cost=0.45, decision_index=0)
    store.choose(concealed["session_id"], "ROAM")

    complete = store.finish(concealed["session_id"])

    assert complete["actual_action"] == "ROAM"
    assert complete["observability"] == "UNCERTAIN"
    assert complete["observability_basis"] == "presence_sampler"
    assert complete["advice_gradeable"] is False
