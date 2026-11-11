param([Parameter(Mandatory=$true)][string]$TestDirectory)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $root 'beast/server-safety.ps1')
$source = Join-Path $root 'beast/farol-server.ps1'
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw "Launcher parse errors: $parseErrors" }
# Load only function definitions. Never execute the actual launcher's dispatch.
foreach ($definition in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]}, $false)) {
    Invoke-Expression $definition.Extent.Text
}
function Assert-True($condition, $message) { if (-not $condition) { throw $message } }
function Expect-Rejection([scriptblock]$action) {
    $rejected = $false
    try { & $action } catch { $rejected = $true }
    Assert-True $rejected 'Unsafe operation was not rejected'
}
function Get-Process { return $script:fixture }
function Get-FarolProcesses { return @($script:fixture) }
function Test-FarolHealth { return $false }
function Get-NetTCPConnection { return @() }
function Start-Process { throw 'Test must never launch a real process' }
function Disable-ScheduledTask { $script:disabled++ }

$Python = 'C:\fixture\python.exe'
$LogDir = (Resolve-Path -LiteralPath $TestDirectory).Path
$IdentityFile = Join-Path $LogDir 'farol-service.json'
$StopRequestFile = Join-Path $LogDir 'farol-stop.json'
$PidFile = Join-Path $LogDir 'farol.pid'
$ListenPort = 18787
$TaskName = 'FixtureTask'
$script:disabled = 0
$script:fixture = [pscustomobject]@{
    Id = 4242; Handle = 123; Path = $Python; StartTime = [datetime]'2026-10-26T12:00:00Z'
}
$script:fixture | Add-Member ScriptMethod Dispose { }
$script:fixture | Add-Member ScriptMethod WaitForExit { param($milliseconds) return $false }
$record = @{
    protocol = 1; pid = 4242; instance = ('a' * 32); executable = $Python
    creation_token = $script:fixture.StartTime.ToUniversalTime().ToFileTimeUtc().ToString()
}
$owned = Get-FarolOwnedProcess $record $Python
Assert-True ($owned.Id -eq 4242) 'Matching process not recognized'
$oldToken = $record.creation_token
$record.creation_token = 'different'
Expect-Rejection { Get-FarolOwnedProcess $record $Python }
$record.creation_token = $oldToken
$record.executable = 'C:\unrelated\python.exe'
Expect-Rejection { Get-FarolOwnedProcess $record $Python }
$record.executable = $Python
$record.protocol = 0
Expect-Rejection { Get-FarolOwnedProcess $record $Python }
$record.protocol = 1
Expect-Rejection { Start-Farol } # Failed health never triggers restart.
Expect-Rejection { Stop-Farol }  # A legacy/missing identity never trusts a PID.
[IO.File]::WriteAllText($IdentityFile, ($record | ConvertTo-Json))
Expect-Rejection { Stop-Farol }  # Observer timeout retains process and request.
$request = Get-Content -LiteralPath $StopRequestFile -Raw | ConvertFrom-Json
Assert-True ($request.action -eq 'stop' -and $request.instance -eq $record.instance -and
    $request.creation_token -eq $record.creation_token) 'Stop request identity mismatch'
Assert-True ($script:disabled -eq 1) 'Watchdog was not disabled for intentional stop'
Assert-True (Test-Path -LiteralPath $IdentityFile) 'Pending instance identity removed'
Write-Host '7 launcher guard cases passed; no real process or network access.'

$ListenPort = 8787
$PublicHost = 'rideedge.example.test'
$script:serveFixture = @'
{"TCP":{"443":{"HTTPS":true},"80":{"HTTP":true}},"Web":{"rideedge.example.test:443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:8787"}}},"rideedge.example.test:80":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:8787"},"/desk/":{"Proxy":"http://127.0.0.1:8791/desk"}}}}}
'@ | ConvertFrom-Json
$script:serveCalls = [Collections.Generic.List[string]]::new()
function tailscale {
    $global:LASTEXITCODE = 0
    if (($args -join ' ') -eq 'serve status --json') { return ($script:serveFixture | ConvertTo-Json -Depth 8) }
    $script:serveCalls.Add(($args -join ' '))
    if ($args -contains '--http=80' -and $args -contains 'off') {
        $script:serveFixture.Web.'rideedge.example.test:80'.Handlers.PSObject.Properties.Remove('/')
    }
}
function Test-FarolHealth { return $true }
Enable-TailscaleServe
Assert-True ($script:serveCalls.Count -eq 2) 'Unexpected Serve operations'
Assert-True ($script:serveCalls[0] -eq 'serve --bg --http=80 --set-path=/ off') 'HTTP removal was not path-scoped'
Assert-True ($script:serveCalls[1] -eq 'serve --bg --https=443 --set-path=/ http://127.0.0.1:8787') 'HTTPS target changed'
Assert-True ($script:serveFixture.Web.'rideedge.example.test:80'.Handlers.'/desk/'.Proxy -eq 'http://127.0.0.1:8791/desk') 'Unrelated path changed'
$script:serveCalls.Clear()
$script:serveFixture.Web.'rideedge.example.test:443'.Handlers.'/'.Proxy = 'http://127.0.0.1:9999'
Expect-Rejection { Enable-TailscaleServe }
Assert-True ($script:serveCalls.Count -eq 0) 'Foreign route overwritten'
$script:serveFixture.Web.'rideedge.example.test:443'.Handlers.'/'.Proxy = 'http://127.0.0.1:8787'
$script:serveFixture | Add-Member NoteProperty AllowFunnel ([pscustomobject]@{'rideedge.example.test:443' = $true})
Expect-Rejection { Enable-TailscaleServe }
Assert-True ($script:serveCalls.Count -eq 0) 'Funnel conflict was ignored'
Write-Host '3 Serve ownership/migration cases passed with fake CLI only.'
$script:serveFixture.PSObject.Properties.Remove('AllowFunnel')
$script:serveFixture.TCP.'443'.HTTPS = $false
Expect-Rejection { Enable-TailscaleServe }
Assert-True ($script:serveCalls.Count -eq 0) 'Foreign TCP listener overwritten'
