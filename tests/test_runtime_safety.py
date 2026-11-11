"""Run Windows-native safety guards with fake processes; never touch a real GPU."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="Windows PowerShell guard tests")
def test_owned_process_and_lease_guards():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-File", str(root / "scripts/test_runtime_safety.ps1")],
        capture_output=True, text=True, timeout=20, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "8 process cases" in result.stdout
