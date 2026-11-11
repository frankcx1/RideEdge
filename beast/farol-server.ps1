#Requires -Version 5.1
<#
.SYNOPSIS
  Start, stop, and persist the Farol dashboard on workstation.

.DESCRIPTION
  Binds 127.0.0.1:8787 by default. RDP in from the Surface, then open
  http://127.0.0.1:8787. Does not expose 8787 on the public NIC.

.EXAMPLE
  .\farol-server.ps1 start
  .\farol-server.ps1 install
  .\farol-server.ps1 serve-on
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status', 'install', 'uninstall', 'serve-on', 'serve-off')]
    [string]$Command = 'start'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$LogDir = Join-Path $PSScriptRoot 'logs'
$LogFile = Join-Path $LogDir 'farol.log'
$PidFile = Join-Path $LogDir 'farol.pid'
$IdentityFile = Join-Path $LogDir 'farol-service.json'
$StopRequestFile = Join-Path $LogDir 'farol-stop.json'
$Python = 'C:\Users\YOUR_USER\AppData\Local\Programs\Python\Python311\python.exe'
$TaskName = 'FarolDashboard'
$ListenHost = '127.0.0.1'
$ListenPort = 8787
$PublicHost = 'rideedge.example.com'
$HealthUrl = "http://${ListenHost}:${ListenPort}/api/live"
. (Join-Path $PSScriptRoot 'server-safety.ps1')

function Get-FarolProcesses {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'farol\.api' }
}

function Test-FarolHealth {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $HealthUrl
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Start-Farol {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $existing = @(Get-FarolProcesses)
    if ($existing.Count -gt 0) {
        if (Test-FarolHealth) {
            Write-Host "Farol already healthy at $HealthUrl"
            return
        }
        throw 'An API process still exists but health is unavailable. It may be starting, busy, or draining. No restart or termination attempted.'
    }
    if (@(Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue).Count) {
        throw 'The API port is occupied by an unverified listener. No process was changed.'
    }
    if (Test-Path -LiteralPath $IdentityFile) {
        $record = Get-Content -LiteralPath $IdentityFile -Raw | ConvertFrom-Json
        $owned = Get-FarolOwnedProcess $record $Python
        if ($owned) {
            $owned.Dispose()
            throw 'The recorded API process is still alive. Wait for its existing operation; no replacement started.'
        }
    }

    Enable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
    $errLog = Join-Path $LogDir 'farol.err.log'
    $process = Start-Process -FilePath $Python `
        -ArgumentList @('-u', '-m', 'farol.api') `
        -WorkingDirectory $RepoRoot `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $errLog `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $PidFile -Value $process.Id -Encoding ascii

    $healthy = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        if (Test-FarolHealth) {
            $healthy = $true
            break
        }
        if ($process.HasExited) {
            break
        }
    }
    if (-not $healthy) {
        throw "Farol has not become healthy at $HealthUrl. Its process was left intact. Inspect local logs; do not infer exit from this observation timeout."
    }
    Write-Host "Farol listening at $HealthUrl  pid=$($process.Id)"
}

function Stop-Farol {
    param([switch]$KeepTask)
    if (-not (Test-Path -LiteralPath $IdentityFile)) {
        throw 'This API has no cooperative-stop identity. Legacy PID files are not trusted. No process was changed.'
    }
    $record = Get-Content -LiteralPath $IdentityFile -Raw | ConvertFrom-Json
    $owned = Get-FarolOwnedProcess $record $Python
    if (-not $owned) {
        if (@(Get-FarolProcesses).Count -or @(Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue).Count) {
            throw 'The recorded process exited but another process/listener exists. No process was changed.'
        }
        if (-not $KeepTask) { Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null }
        Write-Host 'Recorded API already exited.'
        return
    }
    try {
        if (-not $KeepTask) { Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null }
        $request = @{
            action = 'stop'; protocol = 1; pid = [int]$record.pid
            creation_token = [string]$record.creation_token; instance = [string]$record.instance
        }
        $temporary = "$StopRequestFile.tmp"
        [IO.File]::WriteAllText($temporary, ($request | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false))
        Move-Item -LiteralPath $temporary -Destination $StopRequestFile -Force
        if (-not $owned.WaitForExit(30000)) {
            throw 'API drain remains pending after 30 seconds. The original process and stop request remain intact; no replacement or termination attempted.'
        }
        if (Test-Path -LiteralPath $PidFile) { Remove-Item -LiteralPath $PidFile }
        Write-Host 'API completed cooperative shutdown.'
    } finally {
        $owned.Dispose()
    }
}

function Show-FarolStatus {
    $health = Test-FarolHealth
    $procs = @(Get-FarolProcesses)
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Host "health: $(if ($health) { 'ok' } else { 'down' })  $HealthUrl"
    if ($procs.Count -eq 0) {
        Write-Host 'process: none'
    } else {
        $procs | ForEach-Object { Write-Host "process: pid=$($_.ProcessId) $($_.CommandLine)" }
    }
    if ($task) {
        $info = $task | Get-ScheduledTaskInfo
        Write-Host "task: $($task.State) last=$($info.LastTaskResult) $($info.LastRunTime)"
    } else {
        Write-Host 'task: not installed'
    }
    $serve = & tailscale serve status 2>$null
    if ($serve) {
        Write-Host "tailscale serve:`n$serve"
    }
}

function Install-FarolTask {
    $script = $PSCommandPath
    $arg = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" start"
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg -WorkingDirectory $RepoRoot
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $logon.Delay = 'PT10S'
    $repeat = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) `
        -RepetitionInterval (New-TimeSpan -Minutes 5) `
        -RepetitionDuration (New-TimeSpan -Days 9999)
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew
    $settings.ExecutionTimeLimit = 'PT0S'
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($logon, $repeat) `
        -Settings $settings -Principal $principal -Force `
        -Description 'Farol dashboard on 127.0.0.1:8787 for RDP from Surface Pro' | Out-Null
    Start-Farol
    Write-Host "Scheduled task '$TaskName' installed (logon + every 5 min watchdog)."
}

function Uninstall-FarolTask {
    Stop-Farol
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Scheduled task '$TaskName' removed"
}

function Get-FarolServeConfig {
    $raw = & tailscale serve status --json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect current Tailscale Serve configuration.' }
    return ($raw -join "`n" | ConvertFrom-Json)
}

function Get-FarolServeRoot($Config, [int]$Port) {
    if (-not $Config.Web) { return $null }
    $web = $Config.Web.PSObject.Properties["${PublicHost}:$Port"]
    if (-not $web -or -not $web.Value.Handlers) { return $null }
    $rootRoute = $web.Value.Handlers.PSObject.Properties['/']
    if ($rootRoute) { return $rootRoute.Value }
    return $null
}

function Assert-FarolServeOwnership($Config) {
    foreach ($port in @(80, 443)) {
        if ($Config.TCP) {
            $listener = $Config.TCP.PSObject.Properties[[string]$port]
            if ($listener -and (($port -eq 443 -and -not $listener.Value.HTTPS) -or
                ($port -eq 80 -and -not $listener.Value.HTTP))) {
                throw "Serve listener on port $port belongs to another protocol. No route changed."
            }
        }
        $route = Get-FarolServeRoot $Config $port
        if ($route -and $route.Proxy -ne "http://127.0.0.1:$ListenPort") {
            throw "Serve root on port $port belongs to another target. No route changed."
        }
    }
    if ($Config.AllowFunnel) {
        foreach ($entry in $Config.AllowFunnel.PSObject.Properties) {
            if ($entry.Value -and $entry.Name -eq "${PublicHost}:443") {
                throw 'Public Funnel is enabled on this listener. No route changed.'
            }
        }
    }
}

function Remove-FarolServeRoot([int]$Port) {
    $flag = if ($Port -eq 443) { '--https=443' } else { '--http=80' }
    & tailscale serve --bg $flag --set-path=/ off
    if ($LASTEXITCODE -ne 0) { throw "Could not remove the RideEdge root route on port $Port." }
}

function Enable-TailscaleServe {
    $before = Get-FarolServeConfig
    Assert-FarolServeOwnership $before
    if (-not (Test-FarolHealth)) {
        Start-Farol
    }
    # Remove only RideEdge's HTTP root; e.g. /desk/ and other listeners remain.
    if (Get-FarolServeRoot $before 80) { Remove-FarolServeRoot 80 }
    & tailscale serve --bg --https=443 --set-path=/ "http://127.0.0.1:$ListenPort"
    if ($LASTEXITCODE -ne 0) {
        throw "tailscale serve failed with exit $LASTEXITCODE"
    }
    $after = Get-FarolServeConfig
    if ((Get-FarolServeRoot $after 80) -or
        (Get-FarolServeRoot $after 443).Proxy -ne "http://127.0.0.1:$ListenPort") {
        throw 'HTTPS-only RideEdge route could not be verified. Inspect Serve configuration.'
    }
    Write-Host 'Tailscale Serve (mesh only, not public):'
    Write-Host '  https://rideedge.example.com  (TLS needs the full name)'
}

function Disable-TailscaleServe {
    $before = Get-FarolServeConfig
    Assert-FarolServeOwnership $before
    foreach ($port in @(80, 443)) {
        if (Get-FarolServeRoot $before $port) { Remove-FarolServeRoot $port }
    }
    Write-Host 'RideEdge root routes removed; unrelated Serve paths retained.'
}

# Serialize launcher commands for this checkout; never race two starts or a
# watchdog start against a stop observer. This mutex does not authorize killing.
$hasher = [Security.Cryptography.SHA256]::Create()
$lockHash = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($RepoRoot.ToLowerInvariant()))).Replace('-', '')
$hasher.Dispose()
$launcherMutex = New-Object Threading.Mutex($false, "Local\RideEdgeServer-$lockHash")
$ownsMutex = $false
try {
    try { $ownsMutex = $launcherMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) { throw 'Another launcher command is still running. No action taken.' }
    switch ($Command) {
    'start' { Start-Farol }
    'stop' { Stop-Farol }
    'restart' { Stop-Farol -KeepTask; Start-Farol }
    'status' { Show-FarolStatus }
    'install' { Install-FarolTask }
    'uninstall' { Uninstall-FarolTask }
    'serve-on' { Enable-TailscaleServe }
    'serve-off' { Disable-TailscaleServe }
    }
} finally {
    if ($ownsMutex) { $launcherMutex.ReleaseMutex() }
    $launcherMutex.Dispose()
}
