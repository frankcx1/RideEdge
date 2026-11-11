import copy
from unittest.mock import patch

import pytest

from farol import recovery, shift

RELEASED = {"phase": "idle", "last_released_lease_id": "later-owned-release",
            "stopped_at": "2026-10-26T01:00:00+00:00"}


def test_old_warning_is_resolved_by_verified_later_release_without_reset_or_shift_mutation(tmp_path):
    probes = []

    def check(verb, args):
        probes.append((verb, args))
        return {"ok": args == ["-LeaseId", "later-owned-release"]}

    with patch.object(shift, "status", return_value=copy.deepcopy(RELEASED)), \
            patch.object(shift, "control_status", return_value={"state": "idle"}), \
            patch.object(shift, "_run_script", side_effect=check), \
            patch.object(shift, "acknowledge_recovery") as mutate:
        supervisor = recovery.RecoverySupervisor(tmp_path, lambda: {"status": "free"}, recovery.acknowledge_verified_release)
        supervisor.record("older-failed-release")
        supervisor.state.update(attempts=10, remaining=0)
        supervisor.tick()
    assert supervisor.status()["state"] == "restored"
    assert supervisor.status()["attempts"] == 10
    assert supervisor.status()["remaining_seconds"] == 0
    assert supervisor.state["lease_id"] == "older-failed-release"
    assert probes == [("check-recovery", ["-LeaseId", "older-failed-release"]),
                      ("check-recovery", ["-LeaseId", "later-owned-release"])]
    mutate.assert_not_called()


@pytest.mark.parametrize("changes,control", [
    ({"phase": "narrating"}, "idle"), ({"last_released_lease_id": None}, "idle"),
    ({"stopped_at": None}, "idle"), ({"stopped_at": "bad-date"}, "idle"),
    ({"stopped_at": "2026-10-26T01:00:00"}, "idle"),
    ({"stopped_at": "2099-01-01T00:00:00+00:00"}, "idle"), ({}, "running"), ({}, "unknown"),
])
def test_incomplete_or_busy_release_cannot_clear_warning(changes, control):
    with patch.object(shift, "status", return_value={**RELEASED, **changes}), \
            patch.object(shift, "control_status", return_value={"state": control}), \
            patch.object(shift, "_run_script", return_value={"ok": False}) as check:
        assert not recovery.acknowledge_verified_release("older-failed-release")
    assert check.call_count == 1


@pytest.mark.parametrize("healthy,changed", [(False, False), (True, True)])
def test_failed_service_verification_or_changed_identity_cannot_clear_warning(healthy, changed):
    after = {**RELEASED, "last_released_lease_id": "different"} if changed else RELEASED
    with patch.object(shift, "status", side_effect=[RELEASED, after]), \
            patch.object(shift, "control_status", return_value={"state": "idle"}), \
            patch.object(shift, "_run_script", side_effect=[{"ok": False}, {"ok": healthy}]):
        assert not recovery.acknowledge_verified_release("older-failed-release")


def test_foreign_coordinator_lease_does_not_enter_release_reconciliation(tmp_path):
    with patch.object(recovery, "acknowledge_verified_release") as verify:
        supervisor = recovery.RecoverySupervisor(tmp_path, lambda: {"status": "valid", "lease": {"owner": "other"}}, verify)
        supervisor.record("older-failed-release")
        supervisor.tick()
    verify.assert_not_called()
    assert supervisor.status()["state"] == "restoration_failed"
