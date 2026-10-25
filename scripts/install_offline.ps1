# Run this on the OFFLINE PC, from inside the copied package folder,
# AFTER installing OllamaSetup.exe and Python (tick "Add python.exe to PATH").
#
# Usage:  powershell -ExecutionPolicy Bypass -File install_offline.ps1 -Dest D:\AI

param(
    [string]$Dest = "D:\AI",
    [switch]$BlockFirewall   # needs Administrator: block Ollama from the network
)
$ErrorActionPreference = "Stop"
$pkg = $PSScriptRoot
New-Item -ItemType Directory -Force $Dest | Out-Null

Write-Host "Copying models to $Dest\ollama_models (several GB, please wait) ..."
Copy-Item -Recurse -Force "$pkg\ollama_models" "$Dest\"
Copy-Item -Recurse -Force "$pkg\file_organizer" "$Dest\"

# Per-user environment variables for Ollama (take effect after Ollama restarts)
setx OLLAMA_MODELS "$Dest\ollama_models" | Out-Null
setx OLLAMA_HOST "127.0.0.1:11434" | Out-Null     # local only, never listen on LAN
setx OLLAMA_NUM_PARALLEL "1" | Out-Null           # save RAM on 16 GB
setx OLLAMA_MAX_LOADED_MODELS "1" | Out-Null
setx OLLAMA_KEEP_ALIVE "10m" | Out-Null

Write-Host "Installing Python packages offline ..."
python -m pip install --no-index --find-links "$pkg\wheels" -r "$pkg\file_organizer\requirements.txt"

if ($BlockFirewall) {
    $exe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    New-NetFirewallRule -DisplayName "Block Ollama outbound" -Direction Outbound `
        -Program $exe -Action Block -ErrorAction SilentlyContinue | Out-Null
    Write-Host "Firewall rule added for $exe"
}

Write-Host ""
Write-Host "Done. Now: quit Ollama from the tray icon, start it again, then run:"
Write-Host "  ollama list"
Write-Host "  cd $Dest\file_organizer"
Write-Host "  python organize.py scan `"D:\ToSort`" --out plan.csv"
