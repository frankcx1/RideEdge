"""Keep domain tests independent of credentials; security tests use real policy.

This is a test dependency override, not a production environment bypass.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_decision_policy(monkeypatch, tmp_path_factory):
    # Existing domain tests remain the frozen legacy control. New policy tests
    # call the engine explicitly and exercise both gate-dispatch paths separately.
    from farol import decision_policy
    # Keep harness files outside tmp_path so privacy tests can detect application writes.
    path = tmp_path_factory.mktemp("decision-policy") / "decision-policy.yaml"
    raw = decision_policy.PATH.read_text(encoding="utf-8")
    import re
    raw = re.sub(r'^mode:.*$', 'mode: "off"', raw, flags=re.MULTILINE)
    path.write_text(raw, encoding="utf-8")
    monkeypatch.setattr(decision_policy, 'PATH', path)


@pytest.fixture(autouse=True)
def isolated_besttime_transport_allowance(monkeypatch, request, tmp_path):
    # Existing transport tests mock HTTP and exercise the enabled branch. Never
    # enable the workstation policy or read its real request allowance in tests.
    monkeypatch.setenv("RIDEEDGE_BESTTIME_CONTROL_FILE", str(tmp_path / "besttime-policy.sqlite3"))
    monkeypatch.setenv("RIDEEDGE_MODEL_METRICS_FILE", str(tmp_path / "model-metrics.sqlite3"))
    if request.node.path.name in {"test_besttime.py", "test_besttime_identity.py",
                                  "test_area_shadow.py", "test_review_remediation.py"}:
        from farol.besttime_control import configure
        configure(60, 100)


@pytest.fixture(autouse=True)
def domain_test_access(monkeypatch, request):
    if request.node.path.name != "test_access.py":
        from farol.access import AccessPolicy
        monkeypatch.setattr(AccessPolicy, "check", lambda self, request: "allowed")


def pytest_collection_modifyitems(items):
    """Do not substitute invented observations for excluded private fixture data."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    replay_tests = {
        "test_actual_replay_keeps_inferred_actions_ungradeable",
        "test_replay_compares_all_four_policies_without_claiming_evidence",
        "test_api_navigates_decision_timeline", "test_api_rejects_out_of_range_decision",
        "test_brief_is_explicitly_not_live_advice", "test_cost_selector_uses_supported_scenario",
        "test_every_explanation_number_comes_from_scores",
        "test_local_api_serves_health_brief_and_dashboard",
        "test_navigation_mailbox_requires_pairing_and_returns_demo_route",
        "test_stadium_report_is_not_learning_eligible",
        "test_friday_split_reports_executed_path_lower_bounds",
        "test_shadow_window_conceals_recommendation_until_choice",
        "test_only_compliant_observable_advice_is_gradeable", "test_override_cannot_grade_farol",
        "test_early_finish_defaults_to_driver_choice_and_sampler_is_conservative",
    }
    transcript_tests = {
        "test_recording_plan_preserves_transcript_order_and_real_calculation",
        "test_recording_routes_and_public_evaluation_fields",
    }
    for item in items:
        if item.name in replay_tests and not (root / "fixtures/friday_observed.json").exists():
            item.add_marker(pytest.mark.skip(reason="Private historical driving fixtures are not distributed"))
        if item.name in transcript_tests and not (root / "Uber App Text.txt").exists():
            item.add_marker(pytest.mark.skip(reason="Personal podcast transcript is not distributed"))
