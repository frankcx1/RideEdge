# Owned recovery using the installed coordinator's lock, identity and atomic-state
# primitives. No process termination, gate changes, force-recover, or abandon.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExpectedLeaseId,
    [ValidateRange(5, 600)][int]$DeadlineSeconds = 60,
    [switch]$AllowActiveRelease,
    [string]$Coordinator = 'C:\ProgramData\gpu-lease\gpulease.ps1'
)
$ErrorActionPreference = 'Stop'
$requestedLease = $ExpectedLeaseId
$requestedDeadline = $DeadlineSeconds
$allowActive = $AllowActiveRelease
$coordinatorFile = $Coordinator
. $coordinatorFile
$deadlineAt = (Get-Date).ToUniversalTime().AddSeconds($requestedDeadline)
$timer = [System.Diagnostics.Stopwatch]::StartNew()

function Recovery-TimeLeft {
    return [math]::Max(0, [math]::Min($requestedDeadline - $timer.Elapsed.TotalSeconds,
        ($deadlineAt - (Get-Date).ToUniversalTime()).TotalSeconds))
}

function Test-RestoredCydonia {
    if ((_SvcState 'llama').state -ne 'running') { return $false }
    if ($Mock) {
        return ($env:GPULEASE_MOCK_LLAMA_UNHEALTHY -ne '1' -and
                $env:GPULEASE_MOCK_RESTORED_MODEL -ne 'wrong')
    }
    try {
        if ((Recovery-TimeLeft) -lt 6) { return $false }
        $models = Invoke-RestMethod 'http://127.0.0.1:1234/v1/models' -TimeoutSec 3
        $ids = @($models.data | ForEach-Object { $_.id })
        if ($ids.Count -ne 1 -or $ids[0] -ne 'Cydonia-24B-v4.3-Q6_K.gguf') { return $false }
        $health = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 3
        return $health.status -eq 'ok'
    } catch { return $false }
}

function Emit-Recovery([bool]$Ok, [string]$Code) {
    @{ ok = $Ok; code = $Code; lease_id = $requestedLease;
       elapsed_seconds = [math]::Round($timer.Elapsed.TotalSeconds, 3) } | ConvertTo-Json -Compress
}

# This integration depends on v3 operation identities. Unknown coordinators fail
# closed. Dot-sourcing the library executes no verb or service operation.
if ($SchemaVersion -ne 3) { Emit-Recovery $false 'unsupported_coordinator'; exit 20 }
$script:recoveryLease = $null
$script:recoveryCode = 'ownership_or_operation_conflict'
_WithLock {
    $current = Get-GpuLease
    $candidate = $current.lease
    $permitted = $current.status -eq 'restore-failed' -or
        ($allowActive -and $current.status -in @('valid', 'expired-live', 'orphan-grace', 'stale'))
    if (-not $permitted -or -not $candidate -or
        $candidate.owner -ne 'farol' -or $candidate.lease_id -ne $requestedLease -or
        $current.operation_alive -or $candidate.operation_id -or
        $candidate.profile -ne 'text-only') { return }
    # Only the normal text-only restore set is supported by this app integration.
    if (@($candidate.paused_services | Where-Object { $_ -ne 'llama' }).Count -or
        @($candidate.remaining_services | Where-Object { $_ -ne 'llama' }).Count) { return }
    _SetOp $candidate 'reclaim' | Out-Null
    _WriteLeaseAtomic $candidate
    $script:recoveryLease = $candidate
}
if (-not $script:recoveryLease) { Emit-Recovery $false $script:recoveryCode; exit 12 }
$claimed = $script:recoveryLease
$restored = $false
$code = 'restored_model_not_verified'
try {
    $restored = Test-RestoredCydonia
    if (-not $restored) {
        # A running different/unhealthy model is never stopped or replaced. A
        # stopped service may be restored only through the coordinator's gate.
        $service = _SvcState 'llama'
        if ($service.state -ne 'stopped') {
            $code = 'model_listener_conflict'
        } elseif ((Recovery-TimeLeft) -lt 30) {
            $code = 'recovery_deadline'
        } else {
            # One bounded gate observation per attempt, never lower its threshold.
            $gate = _LeaseGate $claimed
            $req = $gate.GateReq; $mode = $gate.GateMode
            if ($req -le 0) { $req = $VramReqByProfile[$claimed.profile] }
            if (-not $mode) { $mode = $VramModeByProfile[$claimed.profile] }
            $safe = if ($Mock) { $env:GPULEASE_MOCK_VRAM_UNSAFE -ne '1' } else { _VramOk -Req $req -Mode $mode }
            if (-not $safe) {
                $code = 'vram_gate_not_met'
            } else {
                # Starting may outlive observation. It remains a live coordinator
                # operation; the Python supervisor must not issue another attempt.
                $restored = (_SvcStart 'llama') -and (Test-RestoredCydonia)
                $code = 'restored_model_not_verified'
            }
        }
    }
} catch { $code = 'recovery_probe_failed' }

$script:recoveryCommitted = $false
_WithLock {
    $raw = _ReadLeaseRaw
    $current = $raw.lease
    if (-not $raw.ok -or -not $current -or $current.owner -ne 'farol' -or
        $current.lease_id -ne $requestedLease -or $current.operation_id -ne $claimed.operation_id) { return }
    if ($restored) {
        _DeleteLease
        _ClearLegacyFlag
        _Log 'rideedge-verified-recovery' @{ owner = 'farol'; lease_id = $requestedLease }
    } else {
        $current.phase = 'restore-failed'
        $current.last_error = $code
        _ClearOp $current | Out-Null
        _WriteLeaseAtomic $current
    }
    $script:recoveryCommitted = $true
}
if (-not $script:recoveryCommitted) { Emit-Recovery $false 'operation_changed'; exit 12 }
if ($restored) {
    if (-not $Mock) {
        # Finish the app-owned bot/state restoration INSIDE this tracked attempt.
        # Startup probes are read-only and cannot repeatedly restart services.
        if ((Recovery-TimeLeft) -lt 5) { Emit-Recovery $false 'app_restore_deadline'; exit 12 }
        $finish = & powershell.exe -NoProfile -File (Join-Path $PSScriptRoot 'farol-shift.ps1') `
            verify-recovery -LeaseId $requestedLease
        if ($LASTEXITCODE -ne 0) { Emit-Recovery $false 'app_restore_not_verified'; exit 12 }
        try { $verified = ($finish | Select-Object -Last 1) | ConvertFrom-Json } catch { $verified = $null }
        if (-not $verified.ok) { Emit-Recovery $false 'app_restore_not_verified'; exit 12 }
    }
    Emit-Recovery $true 'restored_health_verified'
    exit 0
}
Emit-Recovery $false $code
exit 12
