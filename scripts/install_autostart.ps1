# JARVIS — start the agent automatically at logon (per-user, no admin needed)
#
# IMPORTANT: this registers a *startup shortcut in your own user session*, not a
# Windows service. A service runs in session 0 and cannot drive your visible
# desktop (mouse/keyboard/window automation would silently fail), which is why
# the blueprint keeps the agent in the interactive session.
#
# Phase 1 note: the CLI is interactive, so autostart only makes sense once the
# Phase 2/4 background entrypoint exists. This script writes the shortcut and
# leaves it disabled-by-default until then.
param(
    [switch]$Enable,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $repoRoot "scripts\start_jarvis.ps1"
$startupDir = [Environment]::GetFolderPath("Startup")
$linkPath = Join-Path $startupDir "JARVIS.lnk"

if ($Remove) {
    if (Test-Path $linkPath) {
        Remove-Item $linkPath -Force
        Write-Host "Removed autostart entry: $linkPath" -ForegroundColor Yellow
    } else {
        Write-Host "No autostart entry found." -ForegroundColor Yellow
    }
    exit 0
}

if (-not $Enable) {
    Write-Host @"
Autostart is opt-in. Review this script, then run:
    .\scripts\install_autostart.ps1 -Enable     # create the logon shortcut
    .\scripts\install_autostart.ps1 -Remove     # delete it

Target folder: $startupDir
Shortcut would launch: powershell.exe -WindowStyle Hidden -File "$startScript"
"@
    exit 0
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($linkPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`""
$shortcut.WorkingDirectory = $repoRoot
$shortcut.Description = "JARVIS desktop agent"
$shortcut.Save()
Write-Host "Created autostart shortcut: $linkPath" -ForegroundColor Green
