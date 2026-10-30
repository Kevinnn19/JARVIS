# JARVIS — launch the desktop agent (Phase 1: typed commands)
# Usage:
#     .\scripts\start_jarvis.ps1                # interactive, real actions
#     .\scripts\start_jarvis.ps1 -DryRun        # simulate only
#     .\scripts\start_jarvis.ps1 -Command "open chrome"
param(
    [switch]$DryRun,
    [switch]$Speak,
    [string]$Command = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$agentDir = Join-Path $repoRoot "desktop-agent"
$venvPython = Join-Path $agentDir "venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Virtual environment not found. Run .\scripts\setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}

$arguments = @("main.py")
if ($DryRun)  { $arguments += "--dry-run" }
if ($Speak)   { $arguments += "--speak" }
if ($Json)    { $arguments += "--json" }
if ($Command -ne "") { $arguments += @("--once", $Command) }

Push-Location $agentDir
try {
    & $venvPython @arguments
} finally {
    Pop-Location
}
