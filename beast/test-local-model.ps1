#Requires -Version 5.1
<# Temporarily borrow Farol's GPU1 lease, evaluate synthetic cases, always restore. #>
[CmdletBinding()]
param(
    [ValidateSet('gemma', 'qwen')][string]$Model = 'gemma',
    [ValidateRange(1, 10)][int]$Repeats = 1,
    [string]$SimulationSnapshot = '',
    [string]$Case = ''
)
$ErrorActionPreference = 'Stop'
if ($Case -and -not $SimulationSnapshot) { throw '-Case requires -SimulationSnapshot.' }
$repoPath = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$shiftScript = Join-Path $PSScriptRoot 'farol-shift.ps1'
$pythonExe = 'C:\Users\YOUR_USER\AppData\Local\Programs\Python\Python311\python.exe'
$shiftState = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'shift.json') -Raw | ConvertFrom-Json
if ($shiftState.phase -ne 'idle') { throw 'Farol is not idle; finish the active shift before a model evaluation.' }
$renewJob = $null
$borrowed = $false
$evaluationExit = 1

function Invoke-ShiftControl([string[]]$ControlArgs) {
    # A long-lived llama child can inherit the native command's pipe handles.
    # Capture to files and wait on the launcher process, not pipe EOF.
    $runTag = [guid]::NewGuid().ToString('N')
    $outFile = Join-Path $PSScriptRoot "logs\eval-control-$runTag.out.log"
    $errFile = Join-Path $PSScriptRoot "logs\eval-control-$runTag.err.log"
    $controlProcess = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList (@('-NoProfile', '-File', ('"{0}"' -f $shiftScript)) + $ControlArgs) `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    $controlHandle = $controlProcess.Handle
    if (-not $controlProcess.WaitForExit(450000)) { throw 'Shift control exceeded its time limit; inspect shift and GPU lease state.' }
    $raw = Get-Content -LiteralPath $outFile -ErrorAction SilentlyContinue
    $result = ($raw | Select-Object -Last 1) | ConvertFrom-Json
    if (-not $result) { throw "Shift control returned no JSON; inspect $errFile" }
    if ($null -eq $controlProcess.ExitCode) { throw 'Shift control returned no exit status.' }
    return @{ exit = $controlProcess.ExitCode; result = $result }
}

Push-Location $repoPath
try {
    $control = Invoke-ShiftControl @('start', '-Model', $Model, '-FarolPid', "$PID")
    $started = $control.result
    if ($control.exit -ne 0 -or -not $started.ok) { throw "Model start failed: $($started.detail)" }
    $borrowed = $true
    Write-Output "Loaded $($started.model); running narration evaluation."
    $renewJob = Start-Job -ArgumentList $shiftScript,$started.lease_id -ScriptBlock {
        param($control, $lease)
        while ($true) {
            Start-Sleep -Seconds 60
            & powershell -NoProfile -File $control renew -LeaseId $lease -Owner farol | Out-Null
        }
    }
    if ($SimulationSnapshot) {
        $evalArgs = @('-m', 'farol.live_simulation', 'evaluate', '--snapshot', $SimulationSnapshot, '--profile', $Model, '--repeats', "$Repeats")
        if ($Case) { $evalArgs += @('--case', $Case) }
        & $pythonExe @evalArgs
    } else {
        & $pythonExe -m farol.eval_local --profile $Model --repeats $Repeats
    }
    $evaluationExit = $LASTEXITCODE
} finally {
    if ($renewJob) { Stop-Job -Job $renewJob; Remove-Job -Job $renewJob }
    $ownedState = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'shift.json') -Raw | ConvertFrom-Json
    $ownedLease = $ownedState.owner_pid -eq $PID -and $ownedState.lease_id
    if ($borrowed -or $ownedLease) {
        $stopArgs = @('stop')
        if ($ownedState.lease_id) { $stopArgs += @('-LeaseId', [string]$ownedState.lease_id) }
        $restored = Invoke-ShiftControl $stopArgs
        Write-Output ($restored.result | ConvertTo-Json -Compress)
        if ($restored.exit -ne 0 -or -not $restored.result.ok) { $evaluationExit = 2; Write-Warning 'Restore failed; inspect GPU lease status.' }
    }
    Pop-Location
}
exit $evaluationExit
