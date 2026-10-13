[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidateSet('cpu','cuda')][string]$Device, [string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Exe (exit $LASTEXITCODE)" }
}
$speechPython = Join-Path $PSScriptRoot '.venv-whisper/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $speechPython)) {
    Invoke-Checked $Python @('-m','venv',(Join-Path $PSScriptRoot '.venv-whisper'))
}
$indexUrl = if ($Device -eq 'cuda') { 'https://download.pytorch.org/whl/cu128' } else { 'https://download.pytorch.org/whl/cpu' }
Invoke-Checked $speechPython @('-m','pip','install','torch==2.8.0','torchaudio==2.8.0','torchvision==0.23.0','--index-url',$indexUrl)
Invoke-Checked $speechPython @('-m','pip','install','whisperx==3.8.6','torchcodec==0.7.0','ctranslate2==4.8.2')
Invoke-Checked $speechPython @('-m','pip','check')
Invoke-Checked $speechPython @('-c','import torch; print("CUDA available:", torch.cuda.is_available())')
Write-Host 'Optional speech environment installed. Select the intended CPU/CUDA device in the app; models download on first use.'
