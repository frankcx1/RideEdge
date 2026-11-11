# Launch Google's Desktop Head Unit against one explicitly selected ADB phone.
# This tests projected Android Auto, not the separate automotive/ AAOS app.
[CmdletBinding()]
param(
    [string]$SdkPath = 'C:\Android\Sdk',
    [string]$DeviceId,
    [ValidateRange(1024, 65535)][int]$Port = 5278,
    [ValidateSet('default_720p', 'default')][string]$DisplayProfile = 'default_720p',
    [switch]$CheckOnly,
    [switch]$SmokeTest
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$adb = Join-Path $SdkPath 'platform-tools\adb.exe'
$dhuDirectory = Join-Path $SdkPath 'extras\google\auto'
$dhu = Join-Path $dhuDirectory 'desktop-head-unit.exe'
$config = Join-Path $dhuDirectory "config\$DisplayProfile.ini"
foreach ($required in @($adb, $dhu, $config)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Missing Android SDK component: $required"
    }
}

$devices = @(& $adb devices)
if ($LASTEXITCODE -ne 0) { throw 'ADB inventory failed.' }
$ready = @($devices | ForEach-Object {
    if ($_ -match '^([^\s]+)\s+device$') { $Matches[1] }
})
if ($DeviceId) {
    if ($DeviceId -notin $ready) { throw 'Selected device is not connected and authorized in ADB.' }
} elseif ($ready.Count -eq 1) {
    $DeviceId = $ready[0]
} else {
    throw 'Connect one authorized phone, or select it explicitly with -DeviceId.'
}

$packages = @(& $adb -s $DeviceId shell pm list packages)
if ($LASTEXITCODE -ne 0) { throw 'Could not check installed phone packages.' }
if ('package:com.google.android.projection.gearhead' -notin $packages) {
    throw 'Android Auto is not installed on the selected phone.'
}
$normalInstalled = 'package:com.rideedge.app' -in $packages
$previewInstalled = 'package:com.rideedge.app.preview' -in $packages
if (-not ($normalInstalled -or $previewInstalled)) { throw 'Install a RideEdge build before testing.' }
Write-Host "SDK and ADB prerequisites found. RideEdge: $normalInstalled; Preview: $previewInstalled."
Write-Host 'Unlock the phone. In Android Auto developer settings, start the head unit server.'
Write-Host 'Complete any first-connection setup on the phone yourself.'
Write-Host 'These checks do not prove projection, app discovery, or trusted real-car distribution.'
if ($CheckOnly) { return }

$createdForward = $false
try {
    # Never replace an existing tunnel. Only our own successful forward is removed.
    $null = & $adb -s $DeviceId forward --no-rebind "tcp:$Port" 'tcp:5277'
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the test tunnel. Select another -Port.' }
    $createdForward = $true
    Write-Host 'Opening the car display. Quit the DHU to finish and remove this test tunnel.'
    Push-Location -LiteralPath $dhuDirectory
    try {
        if ($SmokeTest) {
            # Official DHU console commands; bounded connection attempt, no GPS injection.
            @('sleep 3', 'focus video on', 'sleep 15', 'quit') |
                & $dhu "--adb=127.0.0.1:$Port" "--config=$config"
        } else {
            & $dhu "--adb=127.0.0.1:$Port" "--config=$config"
        }
        if ($LASTEXITCODE -ne 0) {
            throw "DHU exited with code $LASTEXITCODE. Check the unlocked phone and head unit server; no projection success is implied."
        }
        Write-Host 'DHU exited normally. Verify the projected UI separately; exit status is not an Android Auto acceptance result.'
    } finally { Pop-Location }
} finally {
    if ($createdForward) {
        $null = & $adb -s $DeviceId forward --remove "tcp:$Port"
        if ($LASTEXITCODE -ne 0) { Write-Warning "Remove the test tunnel manually: adb forward --remove tcp:$Port" }
    }
}
