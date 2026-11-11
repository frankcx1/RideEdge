"""Run coordinator integration only with its documented isolated mock environment."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COORDINATOR = Path("C:/ProgramData/gpu-lease/gpulease.ps1")
pytestmark = pytest.mark.skipif(
    not shutil.which("powershell.exe") or not COORDINATOR.exists(),
    reason="Installed Windows v3 coordinator integration",
)


def seed(folder, *, owner="farol", phase="restore-failed", services="llama"):
    state = {
        "version": 3, "lease_id": "synthetic-lease", "owner": owner,
        "phase": phase, "profile": "text-only", "operation_id": None,
        "operation_kind": None, "operation_pid": None, "operation_process_start": None,
        "operation_started_at": None, "paused_services": ["llama"],
        "remaining_services": ["llama"], "vram_required_free_mb": 19000,
        "vram_mode": "gpu:1", "last_error": "fixture",
    }
    (folder / "lease.json").write_text(json.dumps(state), encoding="utf-8")
    (folder / "mock-services.json").write_text(services, encoding="utf-8")
    (folder / "MAINTENANCE.flag").write_text("fixture", encoding="utf-8")


def recover(folder, *, active_release=False, **env):
    environment = {**os.environ, "GPULEASE_MOCK": "1", "GPULEASE_DIR": str(folder),
                   "GPULEASE_LEGACY_FLAG": str(folder / "MAINTENANCE.flag"),
                   "GPULEASE_MOCK_RUNNING": "", "GPULEASE_MOCK_VRAM_UNSAFE": "",
                   "GPULEASE_MOCK_LLAMA_UNHEALTHY": "", "GPULEASE_MOCK_START_FAIL": "",
                   "GPULEASE_MOCK_CONFLICT": "", "GPULEASE_MOCK_RESTORED_MODEL": "", **env}
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-File", str(ROOT / "beast/farol-recover.ps1"),
         "-ExpectedLeaseId", "synthetic-lease", "-Coordinator", str(COORDINATOR),
         *(["-AllowActiveRelease"] if active_release else [])],
        capture_output=True, text=True, timeout=20, check=False, env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.stdout.strip(), result.stderr
    return json.loads(result.stdout), result.returncode


def test_already_restored_health_reconciles_without_restarting_or_changing_gate(tmp_path):
    seed(tmp_path)
    service_before = (tmp_path / "mock-services.json").read_bytes()
    result, code = recover(tmp_path, GPULEASE_MOCK_VRAM_UNSAFE="1")
    assert code == 0 and result["code"] == "restored_health_verified"
    assert not (tmp_path / "lease.json").exists()
    assert not (tmp_path / "MAINTENANCE.flag").exists()
    assert (tmp_path / "mock-services.json").read_bytes() == service_before


@pytest.mark.parametrize("owner,phase", [("foreign", "restore-failed"), ("farol", "reclaiming"),
                                       ("farol", "releasing"), ("farol", "active")])
def test_foreign_or_active_operations_are_untouched(tmp_path, owner, phase):
    seed(tmp_path, owner=owner, phase=phase)
    before = (tmp_path / "lease.json").read_bytes()
    result, code = recover(tmp_path)
    assert code != 0 and result["code"] == "ownership_or_operation_conflict"
    assert (tmp_path / "lease.json").read_bytes() == before


@pytest.mark.parametrize("setting", ["GPULEASE_MOCK_LLAMA_UNHEALTHY", "GPULEASE_MOCK_RESTORED_MODEL"])
def test_unhealthy_or_wrong_running_model_is_not_restarted(tmp_path, setting):
    seed(tmp_path)
    service_before = (tmp_path / "mock-services.json").read_bytes()
    result, code = recover(tmp_path, **{setting: "wrong" if setting.endswith("MODEL") else "1"})
    assert code != 0 and result["code"] == "model_listener_conflict"
    lease = json.loads((tmp_path / "lease.json").read_text(encoding="utf-8-sig"))
    assert lease["phase"] == "restore-failed" and lease["operation_id"] is None
    assert lease["vram_required_free_mb"] == 19000
    assert (tmp_path / "mock-services.json").read_bytes() == service_before


def test_stopped_model_is_not_started_below_gate(tmp_path):
    seed(tmp_path, services="")
    result, code = recover(tmp_path, GPULEASE_MOCK_VRAM_UNSAFE="1")
    assert code != 0 and result["code"] == "vram_gate_not_met"
    assert not (tmp_path / "mock-services.json").read_text().strip()


def test_stopped_model_can_be_restored_through_coordinator_after_gate(tmp_path):
    seed(tmp_path, services="")
    result, code = recover(tmp_path)
    assert code == 0 and result["ok"]
    assert "llama" in (tmp_path / "mock-services.json").read_text(encoding="utf-8-sig")


def test_owned_initial_release_requires_explicit_release_mode(tmp_path):
    seed(tmp_path, phase="active")
    denied, code = recover(tmp_path)
    assert code != 0 and not denied["ok"]
    accepted, code = recover(tmp_path, active_release=True)
    assert code == 0 and accepted["ok"]


def test_initial_release_mode_still_rejects_recorded_operations(tmp_path):
    seed(tmp_path, phase="active")
    path = tmp_path / "lease.json"
    state = json.loads(path.read_text())
    state["operation_id"] = "another-controller"
    path.write_text(json.dumps(state), encoding="utf-8")
    before = path.read_bytes()
    denied, code = recover(tmp_path, active_release=True)
    assert code != 0 and not denied["ok"]
    assert path.read_bytes() == before
