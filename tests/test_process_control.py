import json
import subprocess
from unittest.mock import Mock

from farol import shift
from farol.process_control import LauncherControl


def fake_launcher():
    child = Mock(pid=42)
    child.poll.return_value = None
    child.wait.side_effect = subprocess.TimeoutExpired("fixture", 0)

    def launch(*_, **kwargs):
        kwargs["stdout"].write(b'{"ok":true}\n')
        return child

    return child, Mock(side_effect=launch)


def test_timeout_keeps_original_handle_and_blocks_overlapping_launch(tmp_path):
    child, launch = fake_launcher()
    control = LauncherControl(tmp_path, spawn=launch, identity=lambda _: "created-1")
    assert control.run(["fixture"], "start", tmp_path, timeout=0)["code"] == "launcher_pending"
    assert control.status()["state"] == "running"
    assert not control.run(["fixture"], "stop", tmp_path)["ok"]
    assert launch.call_count == 1
    child.kill.assert_not_called()
    child.terminate.assert_not_called()
    child.poll.return_value = 0
    assert control.status()["state"] == "finished"
    assert control.acknowledge_finished()
    assert control.status()["state"] == "idle"


def test_restart_preserves_live_operation_and_creation_identity(tmp_path):
    _, launch = fake_launcher()
    original = LauncherControl(tmp_path, spawn=launch, identity=lambda _: "created-1")
    original.run(["fixture"], "stop", tmp_path, timeout=0)
    restarted = LauncherControl(tmp_path, spawn=launch, identity=lambda _: "created-1")
    assert restarted.status()["state"] == "running"
    restarted.run(["fixture"], "start", tmp_path)
    assert launch.call_count == 1
    restarted.identity = lambda _: "reused-pid"
    assert restarted.status()["state"] == "finished"


def test_observation_failure_retains_identity_and_does_not_spawn(tmp_path):
    _, launch = fake_launcher()
    original = LauncherControl(tmp_path, spawn=launch, identity=lambda _: "created-1")
    original.run(["fixture"], "stop", tmp_path, timeout=0)
    restarted = LauncherControl(tmp_path, spawn=launch, identity=Mock(side_effect=OSError))
    assert restarted.status()["state"] == "unknown"
    assert not restarted.acknowledge_finished()
    restarted.run(["fixture"], "start", tmp_path)
    assert launch.call_count == 1
    assert json.loads(restarted.path.read_text())["identity"] == "created-1"


def test_crash_during_launch_is_not_permission_to_start_another(tmp_path):
    control = LauncherControl(tmp_path, spawn=Mock())
    control._save({"verb": "start", "phase": "launching"})
    assert control.status()["state"] == "unknown"
    assert not control.run(["fixture"], "start", tmp_path)["ok"]
    control.spawn.assert_not_called()


def test_late_start_cleanup_only_after_confirmed_launcher_completion(tmp_path, monkeypatch):
    child, launch = fake_launcher()
    control = LauncherControl(tmp_path, spawn=launch, identity=lambda _: "created-1")
    control.run(["fixture"], "start", tmp_path, timeout=0)
    monkeypatch.setattr(shift, "_control", control)
    monkeypatch.setattr(shift, "status", lambda: {"phase": "narrating"})
    stop = Mock(return_value={"ok": True})
    monkeypatch.setattr(shift, "stop", stop)
    assert not shift.reconcile_control()
    stop.assert_not_called()
    child.poll.return_value = 0
    assert shift.reconcile_control()
    stop.assert_called_once()


def test_synchronous_control_releases_record_after_confirmed_exit(tmp_path):
    child, launch = fake_launcher()
    child.wait.side_effect = None
    child.wait.return_value = 0
    child.poll.return_value = 0
    control = LauncherControl(tmp_path, spawn=launch, identity=lambda _: None)
    assert control.run(["fixture"], "stop", tmp_path)["ok"]
    assert control.status()["state"] == "idle"


def test_malformed_record_fails_closed(tmp_path):
    control = LauncherControl(tmp_path, spawn=Mock())
    control.path.write_text("{invalid")
    assert control.status()["state"] == "unknown"
    assert not control.run(["fixture"], "start", tmp_path)["ok"]
    control.spawn.assert_not_called()


def test_acknowledgment_survives_crash_after_app_state_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(shift, "STATE_PATH", tmp_path / "shift.json")
    shift._write({"phase": "error", "lease_id": "fixture"})
    assert not shift.acknowledge_recovery("different")
    assert shift.status()["phase"] == "error"
    assert shift.acknowledge_recovery("fixture")
    assert shift.status()["phase"] == "idle"
    assert shift.acknowledge_recovery("fixture")
    assert not shift.acknowledge_recovery("different")
