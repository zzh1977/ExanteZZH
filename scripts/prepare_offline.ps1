# Run this on a Windows PC WITH internet. It builds an offline package
# that you copy (USB drive) to the offline PC.
#
# Before running, install on this online PC:
#   1. Ollama for Windows  (https://ollama.com/download)
#   2. Python 3.14 64-bit  ("Windows installer (64-bit)", tick "Add python.exe to PATH")
# Also put these two installers into the package folder by hand:
#   OllamaSetup.exe, python-3.14.x-amd64.exe
#
# Usage:  powershell -ExecutionPolicy Bypass -File prepare_offline.ps1 -Out D:\offline_ai
#         add  -Models llama3.1:8b,qwen3-vl:4b  to choose models
#         add  -PyVersion 3.13  if the offline PC will use another Python version
# Default models: llama3.1:8b (English/German docs), qwen3-vl:4b (photos),
#                 qwen3:8b (optional: sub-classify Chinese docs)

param(
    [string]$Out = "$PWD\offline_ai",
    [string[]]$Models = @("llama3.1:8b", "qwen3-vl:4b", "qwen3:8b"),
    [string]$PyVersion = "3.14"
)
$ErrorActionPreference = "Stop"
# "-File" passes "a,b" as one string, so split it here
$Models = $Models | ForEach-Object { $_ -split "," } | Where-Object { $_ }
$repo = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force $Out | Out-Null

function Copy-Fresh($from, $to) {
    # Remove an old copy first, so re-running never nests folders
    if (Test-Path $to) { Remove-Item -Recurse -Force $to }
    Copy-Item -Recurse -Force $from $to
}

foreach ($m in $Models) {
    Write-Host "[1/3] Pulling model $m ..."
    ollama pull $m
    if ($LASTEXITCODE -ne 0) { throw "Failed to pull model $m. Check the name and the network." }
}

$modelDir = if ($env:OLLAMA_MODELS) { $env:OLLAMA_MODELS } else { "$env:USERPROFILE\.ollama\models" }
Write-Host "[2/3] Copying models from $modelDir (several GB) ..."
Copy-Fresh $modelDir "$Out\ollama_models"

Write-Host "[3/3] Downloading Python packages for Python $PyVersion (Windows 64-bit) ..."
python -m pip download -r "$repo\file_organizer\requirements.txt" -d "$Out\wheels" `
    --platform win_amd64 --python-version $PyVersion --only-binary=:all:
if ($LASTEXITCODE -ne 0) { throw "pip download failed." }

Copy-Fresh "$repo\file_organizer" "$Out\file_organizer"
Copy-Fresh "$repo\docs" "$Out\docs"
Copy-Item -Force "$repo\scripts\install_offline.ps1" "$Out\"

Write-Host ""
Write-Host "Done. Package folder: $Out"
Write-Host "Now copy OllamaSetup.exe and the Python installer into it, then copy the whole folder to the USB drive."
