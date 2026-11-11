"""Exercise the actual state writer in Windows PowerShell, with isolated files."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="Windows PowerShell state writer")
def test_shift_state_creation_and_atomic_replacement(tmp_path):
    script = tmp_path / "test-state.ps1"
    script.write_text(r'''
param([string]$Source, [string]$StateFile)
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Launcher parse failed' }
$writer = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Write-State'
}, $true)
if (-not $writer) { throw 'Missing state writer' }
# Load only the production writer; no launcher switch or service commands run.
. ([scriptblock]::Create($writer.Extent.Text))
Write-State @{ phase = 'error'; lease_id = 'fixture-lease' }
$first = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
if ($first.phase -ne 'error') { throw 'Initial state missing' }
Write-State @{ phase = 'idle'; last_released_lease_id = 'fixture-lease' }
$second = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
if ($second.phase -ne 'idle' -or $second.last_released_lease_id -ne 'fixture-lease') {
    throw 'Replacement state missing'
}
if ($second.PSObject.Properties.Name -contains 'lease_id') { throw 'Old state leaked' }
if (Test-Path -LiteralPath "$StateFile.$PID.tmp") { throw 'Temporary file not consumed' }
Write-Output 'Created and replaced state using Windows PowerShell'
''', encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-File", str(script),
         "-Source", str(root / "beast/farol-shift.ps1"), "-StateFile", str(tmp_path / "state.json")],
        capture_output=True, text=True, timeout=15, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Created and replaced state" in result.stdout
