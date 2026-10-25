# Run this on a Windows PC WITH internet. It builds an offline package
# that you copy (USB drive) to the offline PC.
#
# Before running, install on this online PC:
#   1. Ollama for Windows  (https://ollama.com/download)
#   2. Python 3.12 64-bit  (same version you will install on the offline PC)
# Also download these two installers into the package folder by hand:
#   OllamaSetup.exe, python-3.12.x-amd64.exe
#
# Usage:  powershell -ExecutionPolicy Bypass -File prepare_offline.ps1 -Out E:\offline_ai
#         add  -Models qwen3:8b,qwen3.5:9b  to choose models

param(
    [string]$Out = "$PWD\offline_ai",
    [string[]]$Models = @("qwen3:8b", "qwen3:4b")
)
$ErrorActionPreference = "Stop"
# "-File" passes "a,b" as one string, so split it here
$Models = $Models | ForEach-Object { $_ -split "," } | Where-Object { $_ }
$repo = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force $Out | Out-Null

foreach ($m in $Models) {
    Write-Host "Pulling model $m ..."
    ollama pull $m
}

$modelDir = if ($env:OLLAMA_MODELS) { $env:OLLAMA_MODELS } else { "$env:USERPROFILE\.ollama\models" }
Write-Host "Copying models from $modelDir ..."
Copy-Item -Recurse -Force $modelDir "$Out\ollama_models"

Write-Host "Downloading Python packages (wheels) ..."
python -m pip download -r "$repo\file_organizer\requirements.txt" -d "$Out\wheels"

Write-Host "Copying tool scripts ..."
Copy-Item -Recurse -Force "$repo\file_organizer" "$Out\file_organizer"
Copy-Item -Force "$repo\scripts\install_offline.ps1" "$Out\"

Write-Host ""
Write-Host "Done. Package folder: $Out"
Write-Host "Remember to put OllamaSetup.exe and the Python installer into it too."
