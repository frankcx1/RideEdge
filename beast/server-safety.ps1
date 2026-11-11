# Read-only process identity checks for the cooperative service protocol.
function Get-FarolOwnedProcess($Record, [string]$ExpectedPython) {
    if (-not $Record -or $Record.protocol -ne 1 -or
        $Record.instance -notmatch '^[a-f0-9]{32}$' -or
        -not $Record.creation_token -or [int]$Record.pid -le 4 -or
        -not [string]::Equals([string]$Record.executable, $ExpectedPython, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Missing or incompatible API identity; no process was changed.'
    }
    $process = Get-Process -Id ([int]$Record.pid) -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    try {
        $null = $process.Handle
        if ($process.StartTime.ToUniversalTime().ToFileTimeUtc().ToString() -ne [string]$Record.creation_token -or
            -not [string]::Equals($process.Path, $ExpectedPython, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'API process identity changed; no process was changed.'
        }
        return $process
    } catch {
        $process.Dispose()
        throw
    }
}
