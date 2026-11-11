import json

from farol.recovery import MAX_ATTEMPTS, RecoverySupervisor


class Clock:
    def __init__(self):
        self.wall = 10000.0
        self.mono = 100.0

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds


class Runner:
    def __init__(self):
        self.calls = []
        self.live = False
        self.unknown = False

    def start(self, lease, seconds):
        assert not self.live
        self.calls.append((lease, seconds))
        self.live = True
        return {"pid": 42, "identity": "fixture"}

    def alive(self, _):
        if self.unknown:
            raise OSError("temporary observation failure")
        return self.live


def setup(tmp_path):
    clock, runner = Clock(), Runner()
    lease = {"status": "restore-failed", "lease": {"owner": "farol", "lease_id": "fixture"}}
    acknowledged = []

    def ack(lease_id):
        acknowledged.append(lease_id)
        return lease.get("healthy", False)

    def instance():
        return RecoverySupervisor(tmp_path, lambda: lease, ack, runner,
                                  wall=lambda: clock.wall, mono=lambda: clock.mono)

    supervisor = instance()
    supervisor.record("fixture")
    return supervisor, clock, runner, lease, acknowledged, instance


def test_attempts_are_spaced_after_completion_and_do_not_overlap(tmp_path):
    supervisor, clock, runner, _, _, _ = setup(tmp_path)
    supervisor.tick()
    assert not runner.calls
    clock.advance(60)
    supervisor.tick()
    assert len(runner.calls) == 1
    clock.advance(100)
    supervisor.tick()
    assert len(runner.calls) == 1
    runner.live = False
    supervisor.tick()
    clock.advance(59)
    supervisor.tick()
    assert len(runner.calls) == 1
    clock.advance(1)
    supervisor.tick()
    assert len(runner.calls) == 2


def test_restart_and_repeated_record_do_not_reset_retry_budget(tmp_path):
    supervisor, clock, runner, _, _, restart = setup(tmp_path)
    clock.advance(60)
    supervisor.tick()
    recreated = restart()
    recreated.record("fixture")
    recreated.record("different-id")
    assert recreated.status()["attempts"] == 1
    clock.advance(600)
    recreated.tick()
    assert recreated.status()["recovery_state"] == "deadline_with_live_operation"
    assert len(runner.calls) == 1
    runner.live = False
    recreated.tick()
    assert recreated.status()["recovery_state"] == "exhausted"


def test_observation_timeout_is_not_a_terminal_handle(tmp_path):
    supervisor, clock, runner, _, _, _ = setup(tmp_path)
    clock.advance(60)
    supervisor.tick()
    runner.unknown = True
    clock.advance(60)
    supervisor.tick()
    assert supervisor.status()["code"] == "recovery_observation_unavailable"
    assert supervisor.state["running"]["pid"] == 42 and len(runner.calls) == 1
    runner.unknown = False
    supervisor.tick()
    assert supervisor.status()["recovery_state"] == "running"


def test_startup_clears_only_verified_recovery_even_after_budget_exhausted(tmp_path):
    supervisor, clock, runner, lease, acknowledged, restart = setup(tmp_path)
    clock.advance(601)
    supervisor.tick()
    lease["status"] = "free"
    recreated = restart()
    recreated.tick()
    assert recreated.status()["state"] == "restoration_failed"
    lease["healthy"] = True
    recreated.tick()
    assert recreated.status()["state"] == "restored"
    assert acknowledged and not runner.calls


def test_foreign_lease_and_live_operation_are_never_mutated(tmp_path):
    supervisor, clock, runner, lease, _, _ = setup(tmp_path)
    clock.advance(60)
    lease["lease"]["owner"] = "another-app"
    supervisor.tick()
    lease["lease"]["owner"] = "farol"
    lease["operation_alive"] = True
    supervisor.tick()
    lease["operation_alive"] = False
    lease["lease"]["operation_id"] = "other-operation"
    supervisor.tick()
    assert not runner.calls


def test_wall_clock_rollback_does_not_extend_budget(tmp_path):
    supervisor, clock, runner, _, _, _ = setup(tmp_path)
    clock.wall -= 3600
    clock.mono += 1
    supervisor.tick()
    assert supervisor.status()["remaining_seconds"] == 0
    assert not runner.calls


def test_attempt_limit_and_time_limit_are_both_enforced(tmp_path):
    supervisor, clock, runner, _, _, _ = setup(tmp_path)
    supervisor.state["attempts"] = MAX_ATTEMPTS
    clock.advance(60)
    supervisor.tick()
    assert supervisor.status()["recovery_state"] == "exhausted"
    assert not runner.calls


def test_corrupt_state_fails_closed(tmp_path):
    (tmp_path / "recovery.json").write_text('{"remaining": "invalid"}')
    supervisor = RecoverySupervisor(tmp_path, lambda: {"status": "free"}, lambda _: True)
    supervisor.tick()
    assert supervisor.status()["recovery_state"] == "manual"
    assert supervisor.status()["attempts"] == MAX_ATTEMPTS


def test_restart_during_unsaved_launch_does_not_spawn_again(tmp_path):
    supervisor, clock, runner, _, _, restart = setup(tmp_path)
    supervisor.state["phase"] = "launching"
    supervisor.state["attempts"] = 1
    supervisor._save()
    recreated = restart()
    clock.advance(100)
    recreated.tick()
    assert recreated.status()["recovery_state"] == "manual"
    assert not runner.calls
    saved = json.loads((tmp_path / "recovery.json").read_text())
    assert saved["attempts"] == 1
