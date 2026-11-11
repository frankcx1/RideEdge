# Deterministic PowerShell guard tests. No real process/network/coordinator access.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../beast/runtime-safety.ps1')

function Assert-True($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Get-RideEdgeProcess([int]$ProcessId) { return $script:fixtureProcess }
function Get-RideEdgeListeners([int]$ListenPort) { return $script:fixtureListeners }

function New-Fixture {
    $script:killCount = 0
    $script:disposeCount = 0
    $script:fixtureListeners = @(4242)
    $script:fixtureProcess = [pscustomobject]@{
        Id = 4242; Handle = 123; ProcessName = 'llama-server'
        StartTime = [datetime]'2026-10-26T12:00:00Z'; Path = 'C:\fixture\llama-server.exe'
    }
    $script:fixtureProcess | Add-Member ScriptMethod Kill { $script:killCount++ }
    $script:fixtureProcess | Add-Member ScriptMethod WaitForExit { param($timeout) return $true }
    $script:fixtureProcess | Add-Member ScriptMethod Dispose { $script:disposeCount++ }
    return Get-RideEdgeNarratorIdentity $script:fixtureProcess
}

$ident = New-Fixture
$result = Stop-RideEdgeNarrator $ident 1234
Assert-True ($result.ok -and $script:killCount -eq 1 -and $script:disposeCount -eq 1) 'Owned process not stopped/disposed'

$ident = New-Fixture
$script:fixtureListeners = @(9898)
$result = Stop-RideEdgeNarrator $ident 1234
Assert-True (-not $result.ok -and $script:killCount -eq 0) 'Foreign listener was touched'

$ident = New-Fixture
$script:fixtureProcess.StartTime = $script:fixtureProcess.StartTime.AddSeconds(1)
$result = Stop-RideEdgeNarrator $ident 1234
Assert-True (-not $result.ok -and $script:killCount -eq 0) 'Recycled PID was touched'

$ident = New-Fixture
$ident.server_exe = 'C:\another-app\llama-server.exe'
$result = Stop-RideEdgeNarrator $ident 1234
Assert-True (-not $result.ok -and $script:killCount -eq 0) 'Foreign executable was touched'

$ident = New-Fixture
$ident.Remove('llama_process_start')
$result = Stop-RideEdgeNarrator $ident 1234
Assert-True (-not $result.ok -and $script:killCount -eq 0) 'Legacy identity was treated as verified'

$ident = New-Fixture
$script:fixtureProcess = $null
$script:fixtureListeners = @()
$result = Stop-RideEdgeNarrator $ident 1234
Assert-True ($result.ok -and $script:killCount -eq 0) 'Already exited process not recognized'

$ident = New-Fixture
$script:fixtureListeners = @()
$result = Stop-RideEdgeNarrator $ident 1234
Assert-True ($result.ok -and $script:killCount -eq 1) 'Owned loading process was not stopped before listening'

$ident = New-Fixture
$result = Stop-RideEdgeNarrator @{} 1234
Assert-True (-not $result.ok -and $script:killCount -eq 0) 'Unrecorded listener was touched'

$lease = @{ ok = $true; status = 'valid'; lease = @{ owner = 'farol'; lease_id = 'fixture' } }
Assert-True (Test-RideEdgeLease $lease 'farol' 'fixture') 'Owned lease rejected'
foreach ($phase in @('acquiring', 'reclaiming', 'releasing')) {
    $lease.status = $phase
    $lease.operation_alive = $true
    Assert-True (-not (Test-RideEdgeLease $lease 'farol' 'fixture')) 'Live operation accepted'
    $lease.operation_alive = $false
    Assert-True (-not (Test-RideEdgeLease $lease 'farol' 'fixture')) 'Transient operation accepted'
}
$lease.status = 'restore-failed'
$lease.lease.operation_id = 'unfinished-operation'
Assert-True (-not (Test-RideEdgeLease $lease 'farol' 'fixture')) 'Recorded operation accepted'
$lease.lease.Remove('operation_id')
$lease.lease.owner = 'another-app'
Assert-True (-not (Test-RideEdgeLease $lease 'farol' 'fixture')) 'Foreign recovery accepted'
$lease.lease.owner = 'farol'
$lease.lease.lease_id = 'replacement'
Assert-True (-not (Test-RideEdgeLease $lease 'farol' 'fixture')) 'Replacement lease accepted'

$errors = $null; $tokens = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot '../beast/farol-shift.ps1'), [ref]$tokens, [ref]$errors)
Assert-True ($errors.Count -eq 0) 'Shift launcher has syntax errors'
# Extract only the observational function; do not run the launcher's dispatch.
$tree = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot '../beast/farol-shift.ps1'), [ref]$tokens, [ref]$errors)
$check = $tree.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-CheckRecovery' }, $true)
. ([scriptblock]::Create($check.Extent.Text))
$LeaseId = 'fixture'; $Port = 1234
$script:checkState = @{ phase = 'idle'; last_released_lease_id = 'fixture' }
$script:botPresent = $true
$script:checkResult = $null
function Read-State { return $script:checkState }
function Invoke-Lease { return @{ json = @{ status = 'free' } } }
function Get-RideEdgeListeners { if ($script:botPresent) { return @(42) }; return @() }
function Get-CimInstance { return @{ CommandLine = 'python companion_telegram fixture' } }
function Invoke-RestMethod { param($Uri, $TimeoutSec)
    if ($Uri.EndsWith('/health')) { return @{ status = 'ok' } }
    return @{ data = @(@{ id = 'Cydonia-24B-v4.3-Q6_K.gguf' }) }
}
function Emit($value) { $script:checkResult = $value }
function Restore-CompanionBot { throw 'Read-only verification attempted a bot mutation' }
function Write-State { throw 'Read-only verification attempted a state mutation' }
Invoke-CheckRecovery
Assert-True $script:checkResult.ok 'Crash after app-state commit was not recognized'
$script:botPresent = $false
Invoke-CheckRecovery
Assert-True (-not $script:checkResult.ok) 'Absent bot was falsely reported restored'
$script:botPresent = $true
$script:checkState.last_released_lease_id = 'different'
Invoke-CheckRecovery
Assert-True (-not $script:checkResult.ok) 'Different recovery identity accepted'
Write-Output 'Runtime safety: 8 process cases, ownership/operation guards and launcher parse passed.'
