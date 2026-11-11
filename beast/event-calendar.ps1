#Requires -Version 5.1
<#
  CPU-only sibling of IntelRaker's news task. No news runner, GPU lease, email,
  or public publishing is invoked. Store is events.db, outside its items.db scan.
#>
[CmdletBinding()]
param(
    [ValidateSet('run', 'install', 'status')][string]$Command = 'run',
    [string]$Store = 'C:\intelraker\raked\seattle-events',
    [string]$Python = 'C:\Users\YOUR_USER\AppData\Local\Programs\Python\Python311\python.exe'
)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$TaskName = 'IntelRaker-SeattleEvents'
$Description = 'RideEdge Seattle community calendar: Seattle and Redmond, local database, CPU only, 06:00 and 15:30 Pacific'

if ($Command -eq 'status') {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        $info = $task | Get-ScheduledTaskInfo
        [pscustomobject]@{ Task = $TaskName; State = $task.State.ToString(); LastRun = $info.LastRunTime;
            NextRun = $info.NextRunTime; LastResult = $info.LastTaskResult; Store = $Store }
    } else { Write-Output 'Seattle event task is not installed' }
    return
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Python 3.11 executable is missing' }
if ($Command -eq 'install') {
    if ((Get-TimeZone).Id -ne 'Pacific Standard Time') { throw 'This schedule expects the workstation Pacific timezone' }
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing -and $existing.Description -notlike 'RideEdge Seattle community calendar*') {
        throw 'Task name is already owned by another workload'
    }
    $arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Command run -Store "{1}" -Python "{2}"' -f $PSCommandPath, $Store, $Python
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $Repo
    $triggers = @((New-ScheduledTaskTrigger -Daily -At '06:00'), (New-ScheduledTaskTrigger -Daily -At '15:30'))
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15)
    # Matches the existing IntelRaker login model. Locked desktop is fine; browser
    # and RideEdge need not be open. The user must remain signed into Windows.
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings `
        -Principal $principal -Description $Description -Force | Out-Null
    Write-Output "$TaskName installed: daily 06:00 and 15:30 Pacific; store $Store"
    return
}

$logDir = Join-Path $Store 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logFile = Join-Path $logDir ('collection-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
Push-Location $Repo
try {
    $env:PYTHONIOENCODING = 'utf-8'
    & $Python -u -m farol.event_collect --days 14 --store $Store *> $logFile
    $code = $LASTEXITCODE
    if ($null -eq $code) { throw 'Event collector returned no process result' }
    Write-Output "Event collection finished (exit $code); log $logFile"
    exit $code
} finally {
    Pop-Location
}
