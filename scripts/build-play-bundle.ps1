param()
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$jdk = 'C:/Java/jdk-17'
$sdk = 'C:/Android/Sdk'
$signingDir = Join-Path $repo '.tools/rideedge-play-signing'
$keyFile = Join-Path $signingDir 'upload.p12'
$credentialFile = Join-Path $signingDir 'upload-password.clixml'
$exportDir = Join-Path $repo 'exports/play-internal-testing'

# This upload key is local-only. Google Play App Signing manages the delivered
# app's signing key separately. CLIXML protects the password using Windows DPAPI.
New-Item -ItemType Directory -Force -Path $signingDir | Out-Null
$ownerSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $signingDir /inheritance:r /grant:r "*${ownerSid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not restrict signing directory permissions.' }
if ((Test-Path $keyFile) -and !(Test-Path $credentialFile)) {
    throw 'Upload key exists without its password file; restore the credentials before continuing.'
}
if (!(Test-Path $credentialFile)) {
    $random = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($random) } finally { $rng.Dispose() }
    $securePassword = ConvertTo-SecureString ([Convert]::ToBase64String($random)) -AsPlainText -Force
    $credential = New-Object System.Management.Automation.PSCredential('rideedge-upload', $securePassword)
    $credential | Export-Clixml -LiteralPath $credentialFile
}
$credential = Import-Clixml -LiteralPath $credentialFile
$env:RIDEEDGE_UPLOAD_PASSWORD = $credential.GetNetworkCredential().Password
try {
    if (!(Test-Path $keyFile)) {
        & "$jdk/bin/keytool.exe" -genkeypair -keystore $keyFile -storetype PKCS12 -alias rideedge-upload -keyalg RSA -keysize 3072 -validity 10000 -dname 'CN=RideEdge Upload' -storepass:env RIDEEDGE_UPLOAD_PASSWORD -keypass:env RIDEEDGE_UPLOAD_PASSWORD
        if ($LASTEXITCODE -ne 0) { throw 'Upload key generation failed.' }
    }
    $env:JAVA_HOME = $jdk
    $env:ANDROID_HOME = $sdk
    Push-Location (Join-Path $repo 'android')
    try {
        & .\gradlew.bat :app:bundleRelease --console=plain
        if ($LASTEXITCODE -ne 0) { throw 'Release bundle build failed.' }
    } finally { Pop-Location }
    New-Item -ItemType Directory -Force -Path $exportDir | Out-Null
    $destination = Join-Path $exportDir 'RideEdge-internal-testing.aab'
    Copy-Item -LiteralPath (Join-Path $repo 'android/app/build/outputs/bundle/release/app-release.aab') -Destination $destination
    & "$jdk/bin/jarsigner.exe" -keystore $keyFile -storetype PKCS12 -storepass:env RIDEEDGE_UPLOAD_PASSWORD -keypass:env RIDEEDGE_UPLOAD_PASSWORD -sigalg SHA256withRSA -digestalg SHA-256 $destination rideedge-upload
    if ($LASTEXITCODE -ne 0) { throw 'Bundle signing failed.' }
    & "$jdk/bin/jarsigner.exe" -verify $destination
    if ($LASTEXITCODE -ne 0) { throw 'Bundle signature verification failed.' }
    & "$jdk/bin/keytool.exe" -exportcert -rfc -keystore $keyFile -storepass:env RIDEEDGE_UPLOAD_PASSWORD -alias rideedge-upload -file (Join-Path $exportDir 'upload-certificate.pem')
    if ($LASTEXITCODE -ne 0) { throw 'Public certificate export failed.' }
    Get-FileHash -LiteralPath $destination -Algorithm SHA256
    Write-Output "Signed upload bundle: $destination"
    Write-Output 'Keep .tools/rideedge-play-signing safe. Its encrypted password is tied to this Windows user/profile. No upload or phone change was performed.'
} finally {
    Remove-Item Env:RIDEEDGE_UPLOAD_PASSWORD -ErrorAction SilentlyContinue
}
