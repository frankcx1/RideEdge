# Pure guards and narrowly scoped process access. Dot-sourcing performs no work.
function Get-RideEdgeProcess([int]$ProcessId) {
    Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
}

function Get-RideEdgeListeners([int]$ListenPort) {
    @(Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

function Get-RideEdgeNarratorIdentity($Process) {
    # Acquire a handle before reading identity; subsequent Kill uses this same object.
    $null = $Process.Handle
    return @{
        llama_pid = $Process.Id
        llama_process_start = $Process.StartTime.ToUniversalTime().ToString('o')
        server_exe = $Process.Path
    }
}

function Stop-RideEdgeNarrator($Identity, [int]$ListenPort) {
    $listeners = @(Get-RideEdgeListeners $ListenPort)
    $expected = 0
    if ($Identity.llama_pid) { $expected = [int]$Identity.llama_pid }
    if (@($listeners | Where-Object { $_ -ne $expected }).Count) {
        return @{ ok = $false; code = 'listener_not_owned' }
    }
    if ($expected -le 4) {
        return @{ ok = ($listeners.Count -eq 0); code = 'no_recorded_narrator' }
    }
    $process = Get-RideEdgeProcess $expected
    if (-not $process) {
        return @{ ok = ($listeners.Count -eq 0); code = 'narrator_already_exited' }
    }
    try {
        $actual = Get-RideEdgeNarratorIdentity $process
        if (-not $Identity.llama_process_start -or -not $Identity.server_exe -or
            $actual.llama_process_start -ne $Identity.llama_process_start -or
            -not [string]::Equals($actual.server_exe, [string]$Identity.server_exe,
                [StringComparison]::OrdinalIgnoreCase) -or
            $process.ProcessName -ne 'llama-server') {
            return @{ ok = $false; code = 'narrator_identity_mismatch' }
        }
        # A held process handle plus creation time prevents a recycled PID from
        # causing termination of a new listener. Never enumerate/kill by name.
        $process.Kill()
        if (-not $process.WaitForExit(5000)) {
            return @{ ok = $false; code = 'narrator_exit_pending' }
        }
        return @{ ok = $true; code = 'owned_narrator_stopped' }
    } catch {
        return @{ ok = $false; code = 'narrator_identity_or_stop_failed' }
    } finally {
        $process.Dispose()
    }
}

function Test-RideEdgeLease($Envelope, [string]$ExpectedOwner, [string]$ExpectedLeaseId) {
    if (-not $Envelope.ok -or -not $ExpectedLeaseId -or -not $Envelope.lease -or
        $Envelope.lease.owner -ne $ExpectedOwner -or
        $Envelope.lease.lease_id -ne $ExpectedLeaseId) { return $false }
    if ($Envelope.operation_alive -or $Envelope.lease.operation_id -or
        $Envelope.status -in @('acquiring', 'releasing', 'reclaiming')) {
        return $false
    }
    return $Envelope.status -in @('valid', 'expired-live', 'restore-failed', 'stale', 'orphan-grace')
}
