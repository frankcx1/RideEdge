# Transfer an existing key into RideEdge's focused Connection field over ADB.
# Run interactively. Never supply a key as a command-line argument.
[CmdletBinding()]
param(
    [string]$AdbPath = 'C:\Android\Sdk\platform-tools\adb.exe',
    [string]$Serial
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-PhoneAdb {
    param([string]$Arguments, [string]$StandardInput = '')
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $AdbPath
    $start.Arguments = $Arguments
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    try {
        if (-not $process.Start()) { throw 'Could not start ADB.' }
        $outputTask = $process.StandardOutput.ReadToEndAsync()
        $errorTask = $process.StandardError.ReadToEndAsync()
        if ($StandardInput) { $process.StandardInput.WriteLine($StandardInput) }
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(20000)) {
            $process.Kill()
            throw 'ADB timed out. Check the phone and its debugging connection.'
        }
        $output = $outputTask.GetAwaiter().GetResult()
        $null = $errorTask.GetAwaiter().GetResult()
        # Do not echo subprocess output on failure: it may contain sensitive input.
        if ($process.ExitCode -ne 0) { throw 'ADB failed. Check the phone and its debugging connection.' }
        return $output
    } finally { $process.Dispose() }
}

function Assert-RideEdgeKeyField {
    param([string]$Hierarchy)
    $begin = $Hierarchy.IndexOf('<?xml')
    $end = $Hierarchy.LastIndexOf('</hierarchy>')
    if ($begin -lt 0 -or $end -lt $begin) { throw 'Could not inspect the phone screen. No key was sent.' }
    $settings = New-Object System.Xml.XmlReaderSettings
    $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $reader = [System.Xml.XmlReader]::Create(
        (New-Object System.IO.StringReader($Hierarchy.Substring($begin, $end + 12 - $begin))), $settings)
    try {
        $document = New-Object System.Xml.XmlDocument
        $document.XmlResolver = $null
        $document.Load($reader)
    } finally { $reader.Dispose() }
    $fields = @($document.SelectNodes('//node[@package="com.rideedge.app" and @class="android.widget.EditText" and @focused="true" and @password="true" and @enabled="true"]'))
    $titles = @($document.SelectNodes('//node[@package="com.rideedge.app" and (@text="Connect to workstation" or @text="Connect to workstation.")]'))
    if ($fields.Count -ne 1 -or $titles.Count -ne 1) {
        throw 'Open RideEdge > Connection and tap the empty Access key field. No key was sent.'
    }
    if ($fields[0].GetAttribute('text').Length -ne 0) {
        throw 'Clear the phone Access key field first, then run this helper again. No key was sent.'
    }
}

if (-not (Test-Path -LiteralPath $AdbPath -PathType Leaf)) { throw "ADB not found at $AdbPath. Use -AdbPath to specify it." }
$devices = Invoke-PhoneAdb 'devices'
$connected = @([regex]::Matches($devices, '(?m)^([^\s]+)\s+device\s*\r?$') | ForEach-Object { $_.Groups[1].Value })
if (-not $Serial) {
    if ($connected.Count -ne 1) { throw 'Connect exactly one authorized phone, or select one with -Serial.' }
    $Serial = $connected[0]
}
if ($Serial -notmatch '\A[A-Za-z0-9_.:-]+\z' -or $Serial -notin $connected) {
    throw 'The selected phone is not connected and authorized for ADB.'
}
Write-Host 'On the unlocked phone, open RideEdge > Connection and tap the empty Access key field.'
Write-Host 'Keep that field focused until the transfer finishes. This uses your existing key.'
$null = Read-Host 'Press Enter when the phone is ready'
# /dev/tty requires a remote PTY. Force one even though this helper redirects
# local stdin/stdout; ADB otherwise runs a non-interactive shell without a tty.
Assert-RideEdgeKeyField (Invoke-PhoneAdb "-s $Serial shell -tt uiautomator dump /dev/tty")
$secret = Read-Host 'Paste the existing re_ access key here (input is hidden), then press Enter' -AsSecureString
$pointer = [IntPtr]::Zero
$plain = $null
try {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer).Trim()
    if ($plain -cnotmatch '\Are_[A-Za-z0-9_-]{43}\z') { throw 'The key must start with re_ and contain 46 characters. No key was sent.' }
    Assert-RideEdgeKeyField (Invoke-PhoneAdb "-s $Serial shell -tt uiautomator dump /dev/tty")
    # Strict key alphabet makes this shell input safe. Pipe it over stdin, never
    # Windows process arguments. No clipboard reads, key files, or key output.
    # Android's input utility briefly receives the key in its process arguments.
    $null = Invoke-PhoneAdb "-s $Serial shell -T" "input text '$plain'"
    Write-Host 'Key sent. Tap Connect on the phone and check the result.'
} finally {
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    $plain = $null
    $secret.Dispose()
}
