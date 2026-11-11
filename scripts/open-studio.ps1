# Run on workstation. Copies an expiring browser key without changing the phone key.
[CmdletBinding()]
param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$python = 'C:\Users\YOUR_USER\AppData\Local\Programs\Python\Python311\python.exe'
Push-Location -LiteralPath $repo
try {
    $browserKey = & $python -m farol.browser_access
    if ($LASTEXITCODE -ne 0 -or $browserKey -cnotmatch '\Arb_[A-Za-z0-9_-]{43}\z') {
        throw 'Could not create dashboard access. Check the local RideEdge configuration.'
    }
    try {
        $loginCheck = Invoke-RestMethod -Method Post -Uri 'https://rideedge.example.com/auth/login' `
            -Headers @{ Origin = 'https://rideedge.example.com' } -ContentType 'application/json' `
            -Body (@{ token = $browserKey } | ConvertTo-Json -Compress) -TimeoutSec 15
        if ($loginCheck.authenticated -ne $true) { throw 'Authentication not confirmed' }
    } catch {
        throw 'The dashboard did not accept the new key or could not be reached. No key was copied.'
    }
    Set-Clipboard -Value $browserKey
    $browserKey = $null
    if (-not $NoBrowser) { Start-Process 'https://rideedge.example.com/auth/login' }
    Write-Host 'Dashboard accepted the key; it is now copied. Paste (Ctrl+V) into Access key and click Connect.'
    Write-Host 'Valid for 12 hours. Your phone connection is unchanged.'
} finally {
    $browserKey = $null
    Pop-Location
}
