# Launch the separate Preview APK with synthetic recording data. No API calls.
[CmdletBinding()]
param(
    [string]$DeviceId,
    [ValidateRange(0, 100)][int]$Scene = 0,
    [string]$SdkPath = 'C:\Android\Sdk'
)
$ErrorActionPreference = 'Stop'
$fixture = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\fixtures\contracts\recording-demo.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Scene -ge $fixture.stages.Count) { throw 'Unknown recording scene. Use a scene index present in the recording fixture.' }
$adb = Join-Path $SdkPath 'platform-tools\adb.exe'
if (-not (Test-Path -LiteralPath $adb)) { throw 'Android platform tools not found.' }
$devices = @(& $adb devices)
if ($LASTEXITCODE -ne 0) { throw 'ADB inventory failed.' }
$ready = @($devices | ForEach-Object { if ($_ -match '^([^\s]+)\s+device$') { $Matches[1] } })
if ($DeviceId) {
    if ($DeviceId -notin $ready) { throw 'Selected phone is not connected and authorized.' }
} elseif ($ready.Count -eq 1) { $DeviceId = $ready[0] }
else { throw 'Select the USB phone with -DeviceId. Run adb devices to see the available connections.' }
& $adb -s $DeviceId shell am start -S -W -n 'com.rideedge.app.preview/com.rideedge.app.MainActivity' --es radar_fixture_state recording --ei recording_step $Scene
if ($LASTEXITCODE -ne 0) { throw 'Could not launch RideEdge Preview. Install the recording Preview APK first.' }
Write-Host 'Preview replay requested. Verify the DEMO banner on the unlocked phone.'
Write-Host 'Tap Play 12-minute guided tour for hands-free rehearsal, or use the scene controls.'
Write-Host 'For recording, connect the DHU and select RideEdge Preview, then run scripts/record-guided-tour.ps1.'
Write-Host 'Studio monitors real infrastructure independently; the replay does not run inference.'
