#Requires -Version 5.1
param([Parameter(Mandatory=$true)][string]$InputFile, [Parameter(Mandatory=$true)][string]$OutputFile)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$speechInput = Get-Content -LiteralPath $InputFile -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $speechInput.text -or $speechInput.text.Length -gt 700) { throw 'Invalid speech length' }
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $englishVoice = $synth.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Name -eq 'Microsoft Zira Desktop' } | Select-Object -First 1
    if (-not $englishVoice) { throw 'Microsoft Zira Desktop speech voice is not installed or enabled' }
    $synth.SelectVoice($englishVoice.VoiceInfo.Name)
    $synth.Rate = 0
    $synth.SetOutputToWaveFile($OutputFile)
    $synth.Speak([string]$speechInput.text)
    $synth.SetOutputToNull()
    Write-Output $englishVoice.VoiceInfo.Name
} finally { $synth.Dispose() }
