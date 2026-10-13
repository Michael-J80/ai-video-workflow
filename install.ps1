[CmdletBinding()]
param([string]$Python = 'python', [switch]$SkipBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Exe (exit $LASTEXITCODE)" }
}
Invoke-Checked $Python @('-c', 'import sys; assert sys.version_info[:2] == (3,12), "Python 3.12 is required for this tested release"')
$venvPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    Invoke-Checked $Python @('-m', 'venv', (Join-Path $PSScriptRoot '.venv'))
}
Invoke-Checked $venvPython @('-m', 'pip', 'install', '-r', (Join-Path $PSScriptRoot 'requirements.lock.txt'))
Invoke-Checked $venvPython @('-m', 'pip', 'check')
if (-not $SkipBrowser) { Invoke-Checked $venvPython @('-m', 'playwright', 'install', 'chromium', '--only-shell') }
foreach ($command in @('codex', 'hermes', 'ffmpeg', 'ffprobe')) {
    if (Get-Command $command -ErrorAction SilentlyContinue) { Write-Host "$command : found" }
    else { Write-Warning "$command is missing. Read README.md before starting generation." }
}
Write-Host 'Install complete. Chrome is used with a separate profile. Run start.cmd; no generation was submitted.'
