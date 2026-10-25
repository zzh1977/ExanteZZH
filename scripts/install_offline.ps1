# Run this on the OFFLINE PC, from inside the copied package folder,
# AFTER installing OllamaSetup.exe and Python (tick "Add python.exe to PATH").
#
# Usage:  powershell -ExecutionPolicy Bypass -File install_offline.ps1 -Dest D:\AI
#
# Safe to run again: an existing config.json in the destination is kept.

param(
    [string]$Dest = "D:\AI",
    [switch]$BlockFirewall   # needs "Run as administrator": block Ollama from the network
)
$ErrorActionPreference = "Stop"
$pkg = $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "python not found. Install Python with 'Add python.exe to PATH' ticked, then open a NEW PowerShell window."
}
if (-not (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe") -and -not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "Ollama not found. Run OllamaSetup.exe first."
}
New-Item -ItemType Directory -Force $Dest | Out-Null

Write-Host "[1/4] Copying models to $Dest\ollama_models (several GB, please wait) ..."
Copy-Item -Recurse -Force "$pkg\ollama_models" "$Dest\"

Write-Host "[2/4] Copying the organizer tool and documents ..."
$cfg = "$Dest\file_organizer\config.json"
$keep = if (Test-Path $cfg) { Get-Content -Raw -Encoding UTF8 $cfg } else { $null }
Copy-Item -Recurse -Force "$pkg\file_organizer" "$Dest\"
if ($keep) {
    [System.IO.File]::WriteAllText($cfg, $keep, (New-Object System.Text.UTF8Encoding $false))
    Write-Host "      kept your existing config.json"
}
if (Test-Path "$pkg\docs") { Copy-Item -Recurse -Force "$pkg\docs" "$Dest\" }

Write-Host "[3/4] Setting Ollama environment variables ..."
# Per-user environment variables (take effect after Ollama restarts)
setx OLLAMA_MODELS "$Dest\ollama_models" | Out-Null
setx OLLAMA_HOST "127.0.0.1:11434" | Out-Null     # local only, never listen on LAN
setx OLLAMA_NUM_PARALLEL "1" | Out-Null           # save RAM on 16 GB
setx OLLAMA_MAX_LOADED_MODELS "1" | Out-Null      # only one model in memory at a time
setx OLLAMA_KEEP_ALIVE "10m" | Out-Null

Write-Host "[4/4] Installing Python packages offline ..."
python -m pip install --no-index --find-links "$pkg\wheels" -r "$pkg\file_organizer\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed. The Python version must match the one used to build the package (default 3.14)."
}

if ($BlockFirewall) {
    $exe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    New-NetFirewallRule -DisplayName "Block Ollama outbound" -Direction Outbound `
        -Program $exe -Action Block -ErrorAction SilentlyContinue | Out-Null
    Write-Host "Firewall rule added for $exe"
}

Write-Host ""
Write-Host "Done. Next steps:"
Write-Host "  1. Right-click the Ollama tray icon -> Quit Ollama, then start Ollama again from the Start menu."
Write-Host "  2. Open a NEW PowerShell window and run:  ollama list"
Write-Host "  3. cd $Dest\file_organizer"
Write-Host "     python organize.py scan `"D:\ToSort`" --out $Dest\plan.csv"
