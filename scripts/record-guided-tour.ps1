# Capture the Preview-only guided tour into separate editable phone/car tracks.
[CmdletBinding()]
param(
    [string]$DeviceId,
    [switch]$PhoneOnly,
    [switch]$CheckOnly,
    [ValidatePattern('^\d+x\d+$')][string]$DhuVideoSize,
    [ValidateRange(0,29)][int]$StartShot = 0,
    [ValidateRange(0,29)][int]$EndShot = 29,
    [string]$OutputDirectory,
    [string]$Python = 'C:\Users\YOUR_USER\AppData\Local\Programs\Python\Python311\python.exe'
)
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot '..\recordings' }
$arguments = @((Join-Path $PSScriptRoot 'record_guided_tour.py'), '--start-shot', $StartShot,
    '--output', $OutputDirectory)
if ($PSBoundParameters.ContainsKey('EndShot')) { $arguments += @('--end-shot', $EndShot) }
if ($DeviceId) { $arguments += @('--device', $DeviceId) }
if ($PhoneOnly) { $arguments += '--phone-only' }
else {
    $windows = @(Get-Process desktop-head-unit -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle })
    if ($windows.Count -ne 1) { throw 'Open exactly one Android Auto DHU window and select RideEdge Preview, or use -PhoneOnly.' }
    $arguments += @('--dhu-title', $windows[0].MainWindowTitle)
    if ($DhuVideoSize) { $arguments += @('--dhu-video-size', $DhuVideoSize) }
}
if ($CheckOnly) { $arguments += '--check-only' }
& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Guided capture did not complete. Inspect the error/logs; earlier completed takes are preserved.' }
