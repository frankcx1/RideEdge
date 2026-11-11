#Requires -Version 5.1
<#
.SYNOPSIS
  Timeshare GPU1: pause Companion/Cydonia, load a selected Farol narrator, restore after.

.DESCRIPTION
  Borrower of C:\ProgramData\gpu-lease\gpulease.ps1 (profile text-only).
  Stops llama (Cydonia) via the lease, stops the Telegram bot (Companion is "on a shift"),
  starts the selected model on :1234 GPU1, writes beast\shift.json.
  Release stops that model first, then restores Cydonia and the bot.

  Prints ONE JSON object on stdout for the last line.

.EXAMPLE
  .\farol-shift.ps1 status
  .\farol-shift.ps1 start
  .\farol-shift.ps1 stop
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'status', 'renew', 'verify-recovery', 'check-recovery')]
    [string]$Command = 'status',
    [int]$FarolPid = 0,
    [string]$LeaseId = '',
    [string]$Owner = 'farol',
    [ValidateSet('', 'qwen', 'gemma')]
    [string]$Model = '',
    [ValidateSet('driving', 'narrating')]
    [string]$Mode = 'driving',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$StateFile = Join-Path $PSScriptRoot 'shift.json'
$LogFile = Join-Path $PSScriptRoot 'logs\farol-shift.log'
$GpuLease = 'C:\ProgramData\gpu-lease\gpulease.ps1'
$CompanionSvc = 'C:\Users\YOUR_USER\companion-bot\companion_services.ps1'
$RestartBot = 'C:\Users\YOUR_USER\companion-bot\restart_bot.ps1'
$ModelConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'local-models.json') -Raw | ConvertFrom-Json
if (-not $Model) { $Model = if ($env:FAROL_LOCAL_PROFILE) { $env:FAROL_LOCAL_PROFILE } else { $ModelConfig.default } }
$ModelProfile = $ModelConfig.models.PSObject.Properties[$Model].Value
if (-not $ModelProfile) { throw "Unknown local model profile: $Model" }
$LlamaExe = $ModelProfile.server_exe
$ModelGguf = $ModelProfile.gguf
$ModelAlias = $ModelProfile.alias
$Port = 1234
$CudaDevice = '1'
. (Join-Path $PSScriptRoot 'runtime-safety.ps1')

function Write-ShiftLog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null
    Add-Content -Path $LogFile -Value $line -Encoding utf8
}

function Emit([hashtable]$Obj) {
    $json = $Obj | ConvertTo-Json -Compress -Depth 6
    Write-Output $json
}

function Get-FarolOwner {
    if ($FarolPid -gt 0) { $procId = $FarolPid }
    else {
        $pidFile = Join-Path $PSScriptRoot 'logs\farol.pid'
        if (Test-Path $pidFile) { $procId = [int](Get-Content $pidFile | Select-Object -First 1) }
        else { $procId = 0 }
    }
    if (-not $procId) { return $null }
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if (-not $p) { return $null }
    $start = ([datetime]$p.CreationDate).ToUniversalTime().ToString('o')
    return @{ Pid = $procId; Start = $start }
}

function Invoke-ExternalScript([string]$ScriptFile, [string[]]$ScriptArgs) {
    # Wait for the script process itself. A server it starts may retain pipe
    # handles, so capturing a native pipeline can wait forever for EOF.
    $controlTag = [guid]::NewGuid().ToString('N')
    $controlDir = Join-Path $PSScriptRoot 'logs'
    New-Item -ItemType Directory -Force -Path $controlDir | Out-Null
    $controlOut = Join-Path $controlDir "control-$controlTag.out.log"
    $controlErr = Join-Path $controlDir "control-$controlTag.err.log"
    $control = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList (@('-NoProfile', '-File', ('"{0}"' -f $ScriptFile)) + $ScriptArgs) `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $controlOut -RedirectStandardError $controlErr
    $controlHandle = $control.Handle
    if (-not $control.WaitForExit(360000)) {
        Write-ShiftLog 'Control observation deadline reached; retaining original child until confirmed exit.'
        # The Python caller persists this controller's identity. Keep the parent
        # alive while its child is alive so restart cannot orphan an operation.
        while (-not $control.WaitForExit(1000)) { }
    }
    $raw = [string](Get-Content -LiteralPath $controlOut -Raw -ErrorAction SilentlyContinue)
    $errorText = [string](Get-Content -LiteralPath $controlErr -Raw -ErrorAction SilentlyContinue)
    return @{ exit = $control.ExitCode; raw = $raw; error = $errorText }
}

function Invoke-Lease([string[]]$LeaseArgs) {
    $control = Invoke-ExternalScript $GpuLease $LeaseArgs
    $raw = $control.raw
    $json = $null
    try { $json = $raw | ConvertFrom-Json } catch { $json = $null }
    if ($null -eq $control.exit -and $json -and $null -ne $json.exit_code) { $control.exit = [int]$json.exit_code }
    if ($null -eq $control.exit) { throw 'GPU lease control returned no exit status.' }
    return @{ exit = $control.exit; json = $json; raw = ($raw + $control.error) }
}

function Invoke-OwnedRelease([string]$OwnedLeaseId) {
    # Claim the operation atomically inside the shared coordinator lock, then
    # commit only if its lease/operation identity is still ours.
    Invoke-ExternalScript (Join-Path $PSScriptRoot 'farol-recover.ps1') @(
        '-ExpectedLeaseId', $OwnedLeaseId, '-DeadlineSeconds', '300', '-AllowActiveRelease')
}

function Restore-CompanionBot {
    $listeners = @(Get-RideEdgeListeners 8888)
    if ($listeners.Count) {
        foreach ($listener in $listeners) {
            $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$listener" -ErrorAction SilentlyContinue
            if (-not $existing -or $existing.CommandLine -notmatch 'companion_telegram') {
                throw 'Bot port belongs to an unverified process; no process was changed.'
            }
        }
        return # Idempotent restore: leave an already running bot alone.
    }
    if (Test-Path $RestartBot) { $restored = Invoke-ExternalScript $RestartBot @() }
    else { $restored = Invoke-ExternalScript $CompanionSvc @('-Action', 'start', '-Service', 'bot') }
    if ($restored.exit -ne 0) { throw 'Companion bot restore failed; inspect control logs.' }
}

function Invoke-CheckRecovery {
    # Startup verification is read-only: retry-budget exhaustion must not trigger
    # unlimited bot restarts through a supposedly observational health check.
    $state = Read-State
    $matching = ($state.lease_id -eq $LeaseId -and $state.phase -in @('error', 'restoring')) -or
        ($state.phase -eq 'idle' -and $state.last_released_lease_id -eq $LeaseId)
    if (-not $LeaseId -or -not $matching) { Emit @{ ok = $false; code = 'recovery_identity_changed' }; return }
    $before = Invoke-Lease @('status')
    if ($before.json.status -ne 'free') { Emit @{ ok = $false; code = 'coordinator_not_free' }; return }
    $models = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 3
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
    $listeners = @(Get-RideEdgeListeners 8888)
    $botReady = $listeners.Count -gt 0
    foreach ($listener in $listeners) {
        $bot = Get-CimInstance Win32_Process -Filter "ProcessId=$listener" -ErrorAction SilentlyContinue
        if (-not $bot -or $bot.CommandLine -notmatch 'companion_telegram') { $botReady = $false }
    }
    $after = Invoke-Lease @('status')
    $ok = @($models.data).Count -eq 1 -and $models.data[0].id -eq 'Cydonia-24B-v4.3-Q6_K.gguf' -and
        $health.status -eq 'ok' -and $botReady -and $after.json.status -eq 'free'
    Emit @{ ok = [bool]$ok; code = $(if ($ok) { 'restored_health_verified' } else { 'restored_services_not_verified' }) }
}

function Test-Port([int]$ListenPort) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.Connect('127.0.0.1', $ListenPort)
        $c.Close()
        return $true
    } catch { return $false }
}

function Stop-OwnedNarratorOrThrow($Identity) {
    $result = Stop-RideEdgeNarrator $Identity $Port
    if (-not $result.ok) { throw "Narrator stop blocked: $($result.code)" }
}

function Read-State {
    if (-not (Test-Path $StateFile)) { return @{ phase = 'idle' } }
    try { return Get-Content $StateFile -Raw | ConvertFrom-Json } catch { return @{ phase = 'error'; detail = 'unreadable' } }
}

function Write-State($Obj) {
    $dir = Split-Path $StateFile
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $temporary = "$StateFile.$PID.tmp"
    [System.IO.File]::WriteAllText($temporary, ($Obj | ConvertTo-Json -Depth 6), $utf8)
    if (Test-Path -LiteralPath $StateFile) {
        # Windows PowerShell coerces $null to an empty string for this overload;
        # File.Replace then rejects the backup path. Pass an actual null string.
        [System.IO.File]::Replace($temporary, $StateFile, [System.Management.Automation.Language.NullString]::Value)
    } else { [System.IO.File]::Move($temporary, $StateFile) }
}

function Invoke-Status {
    $lease = Invoke-Lease @('status')
    $state = Read-State
    $model = ''
    try {
        $models = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 3
        $model = [string]$models.data[0].id
    } catch { $model = '' }
    Emit @{
        ok = $true
        phase = $(if ($state.phase) { $state.phase } else { 'idle' })
        lease_status = $(if ($lease.json) { $lease.json.status } else { 'unknown' })
        lease_owner = $(if ($lease.json.lease) { $lease.json.lease.owner } else { $null })
        lease_id = $(if ($state.lease_id) { $state.lease_id } else { $null })
        port_1234 = (Test-Port $Port)
        model = $model
        companion_away = [bool]$state.companion_away
        detail = $(if ($state.detail) { $state.detail } else { '' })
    }
}

function Invoke-Start {
    if (-not (Test-Path $GpuLease)) { Emit @{ ok = $false; detail = "gpulease missing at $GpuLease" }; exit 2 }
    if (-not (Test-Path $ModelGguf)) { Emit @{ ok = $false; detail = "Model GGUF missing at $ModelGguf" }; exit 2 }
    if (-not (Test-Path $LlamaExe)) { Emit @{ ok = $false; detail = "llama-server missing at $LlamaExe" }; exit 2 }

    $leaseNow = Invoke-Lease @('status')
    $st = if ($leaseNow.json) { $leaseNow.json.status } else { 'unknown' }
    if ($st -eq 'restore-failed') {
        Emit @{
            ok = $false
            phase = 'blocked'
            lease_status = $st
            detail = 'GPU lease is restore-failed. Reclaim first: powershell -File C:\ProgramData\gpu-lease\gpulease.ps1 reclaim'
        }
        exit 21
    }
    if ($st -ne 'free') {
        Emit @{ ok = $false; phase = 'blocked'; lease_status = $st; detail = "GPU lease busy ($st); wait or release the current owner" }
        exit 10
    }

    $ident = Get-FarolOwner
    if (-not $ident) {
        Emit @{ ok = $false; detail = 'Farol API is not running; start it before a shift so it can own the GPU lease' }
        exit 20
    }
    if ($DryRun) {
        Emit @{
            ok = $true
            phase = 'dry-run'
            would_pause = @('llama via gpulease text-only', 'companion telegram bot')
            would_load = $ModelGguf
            server_exe = $LlamaExe
            model = $ModelAlias
            profile = $Model
            owner_pid = $ident.Pid
        }
        return
    }

    Write-State @{ phase = 'acquiring'; owner = $Owner; owner_pid = $ident.Pid; detail = 'acquiring GPU lease'; started_at = (Get-Date).ToUniversalTime().ToString('o') }
    Write-ShiftLog "acquire owner=$Owner pid=$($ident.Pid)"
    $acq = Invoke-Lease @(
        'acquire', '-Owner', $Owner, '-OwnerPid', "$($ident.Pid)",
        '-OwnerProcessStart', $ident.Start, '-Profile', 'text-only', '-ExpiresInHours', '12',
        '-VramMode', 'gpu:1', '-VramReqMb', '19000'
    )
    if ($acq.exit -ne 0) {
        $failedPhase = 'idle'
        $failedState = @{ phase = 'idle'; detail = 'GPU acquisition failed; inspect coordinator status.' }
        if ($acq.json.status -eq 'restore-failed' -and $acq.json.lease.owner -eq $Owner) {
            $failedPhase = 'error'
            $failedState.phase = 'error'
            $failedState.owner = $Owner
            $failedState.lease_id = $acq.json.lease.lease_id
        }
        Write-State $failedState
        Emit @{ ok = $false; phase = $failedPhase; lease_exit = $acq.exit; detail = 'GPU acquisition failed; inspect coordinator status.' }
        exit $acq.exit
    }
    $leaseId = $acq.json.lease.lease_id
    $narratorState = @{ phase = 'acquiring'; owner = $Owner; owner_pid = $ident.Pid; lease_id = "$leaseId"; model = $ModelAlias; detail = 'GPU lease acquired; loading narrator' }
    Write-State $narratorState
    try {
    Write-ShiftLog "lease $leaseId acquired; stopping Companion bot"
    $pausedBot = Invoke-ExternalScript $CompanionSvc @('-Action', 'stop', '-Service', 'bot')
    if ($pausedBot.exit -ne 0) { throw 'Companion bot did not pause.' }

    # The coordinator already paused its model. An unexpected listener is a
    # conflict, not permission to kill whichever llama-server owns the port.
    if (Test-Port $Port) { throw 'Model port is occupied after acquisition; no process was stopped.' }
    Write-ShiftLog "starting $ModelAlias on GPU$CudaDevice :$Port"
    $env:CUDA_VISIBLE_DEVICES = $CudaDevice
    $proc = Start-Process -FilePath $LlamaExe -ArgumentList @(
        '-m', $ModelGguf,
        '--alias', $ModelAlias,
        '--host', '127.0.0.1',
        '--port', "$Port",
        '-ngl', '99',
        '-c', "$($ModelProfile.context_size)",
        '-np', '1',
        '--jinja',
        '--log-disable',
        '--reasoning-budget', "$($ModelProfile.reasoning_budget)"
    ) -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $PSScriptRoot 'logs\narrator-server.out.log') `
        -RedirectStandardError (Join-Path $PSScriptRoot 'logs\narrator-server.err.log')

    $ownedIdentity = Get-RideEdgeNarratorIdentity $proc
    foreach ($key in $ownedIdentity.Keys) { $narratorState[$key] = $ownedIdentity[$key] }
    $narratorState.phase = 'loading'
    Write-State $narratorState

    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Seconds 3
        if ($proc.HasExited) { break }
        try {
            $id = (Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2).data[0].id
            if ($id -eq $ModelAlias) { $ready = $true; break }
        } catch {}
    }
    if (-not $ready) {
        throw "$ModelAlias failed to come up on :1234"
    }

    $state = @{
        phase = $Mode
        owner = $Owner
        owner_pid = $ident.Pid
        lease_id = "$leaseId"
        llama_pid = $proc.Id
        llama_process_start = $ownedIdentity.llama_process_start
        model = $ModelAlias
        profile = $Model
        gguf = $ModelGguf
        server_exe = $LlamaExe
        port = $Port
        companion_away = $true
        started_at = (Get-Date).ToUniversalTime().ToString('o')
        detail = $(if ($Mode -eq 'narrating') { "$ModelAlias is preparing a brief; Companion will resume afterward." } else { "Companion parked. $ModelAlias is on GPU1 for Farol narration. Python still scores." })
    }
    Write-State $state
    Write-ShiftLog "driving lease=$leaseId llama_pid=$($proc.Id)"
    Emit ($state + @{ ok = $true })
    } catch {
        $loadError = $_.Exception.Message
        $checked = Invoke-Lease @('status')
        if (-not (Test-RideEdgeLease $checked.json $Owner "$leaseId")) {
            throw 'Load cleanup blocked by a changed lease or active coordinator operation.'
        }
        $narratorState.phase = 'restoring'
        $narratorState.detail = 'Cleaning up failed narrator load.'
        Write-State $narratorState
        Stop-OwnedNarratorOrThrow $narratorState
        $release = Invoke-OwnedRelease "$leaseId"
        if ($release.exit -ne 0) {
            Write-State @{ phase = 'error'; owner = $Owner; lease_id = "$leaseId"; detail = "Model load failed and lease restore failed: $loadError" }
            Emit @{ ok = $false; phase = 'error'; detail = 'Model load/restore failed; inspect GPU lease status.' }
            exit 12
        }
        Restore-CompanionBot
        Write-State @{ phase = 'idle'; last_released_lease_id = "$leaseId"; companion_away = $false; detail = "Model load failed; restore requested: $loadError" }
        Emit @{ ok = $false; phase = 'idle'; detail = "Model load failed; restore requested: $loadError" }
        exit 11
    }
}

function Invoke-Stop {
    $state = Read-State
    $leaseId = if ($LeaseId) { $LeaseId } elseif ($state.lease_id) { $state.lease_id } else { '' }
    if (-not $leaseId) {
        Emit @{ ok = $true; phase = 'idle'; detail = 'No Farol lease; existing model left running.' }
        return
    }
    $leaseNow = Invoke-Lease @('status')
    if ($leaseNow.json.status -eq 'free' -and $state.phase -in @('restoring', 'error')) {
        # Recovery after lease release succeeded but the prior launcher hung.
        $restoredModel = (Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 5).data[0].id
        if ($restoredModel -ne 'Cydonia-24B-v4.3-Q6_K.gguf') { throw 'Lease is free but Cydonia is not restored; leaving state for inspection.' }
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
        if ($health.status -ne 'ok') { throw 'Restored model health is not ready.' }
        if ($DryRun) { Emit @{ ok = $true; phase = 'dry-run'; would_finish_bot_restore = $true }; return }
        Restore-CompanionBot
        $verifiedLease = Invoke-Lease @('status')
        if ($verifiedLease.json.status -ne 'free') { throw 'Coordinator changed during verification; state retained.' }
        Write-State @{ phase = 'idle'; last_released_lease_id = "$leaseId"; companion_away = $false; detail = 'Cydonia restored; Companion bot restore completed.' }
        Emit @{ ok = $true; phase = 'idle'; detail = 'Cydonia restored; Companion bot restore completed.' }
        return
    }
    if (-not (Test-RideEdgeLease $leaseNow.json $Owner "$leaseId")) {
        Emit @{ ok = $false; phase = 'blocked'; detail = 'GPU lease identity differs; existing model left running.' }
        exit 12
    }
    if ($DryRun) {
        Emit @{ ok = $true; phase = 'dry-run'; would_stop_model = $state.model; would_release = $leaseId }
        return
    }
    $state.phase = 'restoring'
    $state.detail = 'stopping owned local narrator; restoring Cydonia'
    Write-State $state
    Write-ShiftLog "stop local narrator; release $leaseId"
    Stop-OwnedNarratorOrThrow $state
    Start-Sleep -Seconds 2
    if ($leaseId) {
        $rel = Invoke-OwnedRelease "$leaseId"
        if ($rel.exit -ne 0) {
            Write-ShiftLog "release failed $($rel.exit) $($rel.raw)"
            $state.phase = 'error'
            $state.detail = 'GPU lease restore failed; inspect gpulease status.'
            Write-State $state
            Emit @{ ok = $false; phase = 'error'; detail = 'GPU lease restore failed; inspect gpulease status.' }
            exit $rel.exit
        }
    }
    Restore-CompanionBot
    Write-State @{
        phase = 'idle'
        last_released_lease_id = "$leaseId"
        companion_away = $false
        stopped_at = (Get-Date).ToUniversalTime().ToString('o')
        detail = 'Shift over. Cydonia/Companion restore requested.'
    }
    Emit @{ ok = $true; phase = 'idle'; detail = 'Shift over. Companion should be back on Cydonia.' }
}

function Invoke-Renew {
    if (-not $LeaseId) {
        $s = Read-State
        $LeaseId = [string]$s.lease_id
    }
    if (-not $LeaseId) { Emit @{ ok = $false; detail = 'no lease_id' }; exit 11 }
    $ren = Invoke-Lease @('renew', '-Owner', $Owner, '-LeaseId', $LeaseId)
    Emit @{ ok = ($ren.exit -eq 0); exit = $ren.exit; detail = $(if ($ren.exit -eq 0) { 'renewed' } else { $ren.raw.Trim() }) }
    if ($ren.exit -ne 0) { exit $ren.exit }
}

switch ($Command) {
    'status' { Invoke-Status }
    'check-recovery' { Invoke-CheckRecovery }
    'verify-recovery' {
        $existing = Read-State
        $verifiedLease = Invoke-Lease @('status')
        if (-not $LeaseId -or $existing.lease_id -ne $LeaseId -or
            $existing.phase -notin @('error', 'restoring') -or $verifiedLease.json.status -ne 'free') {
            Emit @{ ok = $false; code = 'recovery_identity_or_health_changed' }
            exit 12
        }
        Invoke-Stop
    }
    'start' { Invoke-Start }
    'stop' { Invoke-Stop }
    'renew' { Invoke-Renew }
}
