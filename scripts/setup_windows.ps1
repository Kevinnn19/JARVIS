# JARVIS — Phase 1 setup for Windows 11
# Usage (PowerShell, from the repo root):
#     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#     .\scripts\setup_windows.ps1
#
# Creates the virtual environment, installs Phase 1 dependencies and runs the
# test suite. Does not change any Windows settings.

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$agentDir = Join-Path $repoRoot "desktop-agent"

Write-Host "== JARVIS setup ==" -ForegroundColor Cyan
Write-Host "Repo:  $repoRoot"
Write-Host "Agent: $agentDir"

# 1. Python check ------------------------------------------------------------
$python = Get-Command py -ErrorAction SilentlyContinue
if ($null -eq $python) {
    Write-Host "Python launcher 'py' not found. Install Python 3.11+ from python.org" -ForegroundColor Red
    exit 1
}
Write-Host "`nPython:" -ForegroundColor Cyan
& py -3 --version

# 2. Virtual environment -----------------------------------------------------
$venv = Join-Path $agentDir "venv"
if (-not (Test-Path $venv)) {
    Write-Host "`nCreating virtual environment..." -ForegroundColor Cyan
    & py -3 -m venv $venv
} else {
    Write-Host "`nVirtual environment already exists." -ForegroundColor Cyan
}

$venvPython = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "venv looks broken (no Scripts\python.exe). Delete $venv and re-run." -ForegroundColor Red
    exit 1
}

# 3. Dependencies ------------------------------------------------------------
Write-Host "`nInstalling dependencies..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r (Join-Path $agentDir "requirements.txt")

# 4. Tests -------------------------------------------------------------------
Write-Host "`nRunning the test suite..." -ForegroundColor Cyan
Push-Location $agentDir
try {
    & $venvPython -m pytest tests -q
} finally {
    Pop-Location
}

Write-Host @"

== Setup complete ==
Start JARVIS:
    .\scripts\start_jarvis.ps1                # interactive
    .\scripts\start_jarvis.ps1 -DryRun        # rehearsal, no real actions

Or manually:
    cd desktop-agent
    .\venv\Scripts\Activate.ps1
    python main.py
"@ -ForegroundColor Green
