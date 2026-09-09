# Register the engine's watchdog + restart tasks under the CURRENT user (no elevation needed).
#   ZargarWatchdog  - every 3 minutes and at logon: start the engine if :8420 is not answering
#   ZargarRestart   - on demand only: restart the engine (deploys: schtasks /Run /TN ZargarRestart); REFUSES while
#                     the engine reports work in flight (/api/ops/restart-check)
#   ZargarRestartOverride - on demand, emergencies only: restart over in-flight work (logged as an override)
# Both run start.ps1 from the Task Scheduler's own process tree, so the engine no longer dies when
# the assistant that happened to start it restarts (docs/PLATFORM-RULES.md 2026-09-08).
# The 3-minute tick runs WINDOWLESS: a plain "powershell -File" task action allocates a visible
# console every tick (a cmd window flashing on the desktop every 3 minutes, 2026-09-08), so the
# watchdog tasks go through wscript + scripts\run-hidden.vbs (copied to C:\ProgramData\Zargar so the
# task depends on no checkout; NOT the user profile - an assistant's sandbox virtualizes writes there
# and the Task Scheduler never sees them, 2026-09-08). ZargarRestart stays visible:
# a deploy is deliberate and its output is useful.
#   scripts\install-watchdog.ps1                       install / refresh
#   scripts\install-watchdog.ps1 -ScriptsDir <dir>     register against another checkout's scripts\
#   scripts\install-watchdog.ps1 -Remove               remove the tasks
param([switch]$Remove, [string]$ScriptsDir = $PSScriptRoot)
$ps = "powershell -NoProfile -ExecutionPolicy Bypass -File"
$wd = Join-Path $ScriptsDir "watchdog.ps1"
if (-not (Test-Path $wd)) { Write-Error "no watchdog.ps1 in $ScriptsDir"; exit 1 }
if ($Remove) {
  schtasks /Delete /TN ZargarWatchdog /F | Out-Null
  schtasks /Delete /TN ZargarRestart /F | Out-Null
  schtasks /Delete /TN ZargarRestartOverride /F 2>$null | Out-Null
  schtasks /Delete /TN ZargarWatchdogLogon /F 2>$null | Out-Null
  Write-Host "removed ZargarWatchdog and ZargarRestart"
  exit 0
}
$launcherDir = Join-Path $env:ProgramData "Zargar"
if (-not (Test-Path $launcherDir)) { New-Item -ItemType Directory -Path $launcherDir | Out-Null }
$launcher = Join-Path $launcherDir "run-hidden.vbs"
Copy-Item (Join-Path $PSScriptRoot "run-hidden.vbs") $launcher -Force
$hidden = "wscript.exe //B //Nologo `"$launcher`" `"$wd`""
schtasks /Create /F /TN ZargarWatchdog /SC MINUTE /MO 3 /TR $hidden /RL LIMITED | Out-Null
# an at-logon trigger needs an elevated shell on this machine ("Access is denied" unelevated); best-effort -
# the 3-minute tick covers a logon within 3 minutes anyway
schtasks /Create /F /TN ZargarWatchdogLogon /SC ONLOGON /TR $hidden /RL LIMITED 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "note: ZargarWatchdogLogon not registered (needs an elevated shell); the 3-minute tick covers logon" }
# ZargarRestart is on-demand and desks re-point it (e.g. at restart.ps1 -Expect <version>): create it only if missing
# the deploy door is restart.ps1 (ASCII, Windows PowerShell 5.1): readiness check -> stop -> start -> wait for
# health -> restoration check. Always refreshed: a task with a baked "-Expect <version>" is a dead deploy.
$rs = Join-Path $PSScriptRoot "restart.ps1"
schtasks /Create /F /TN ZargarRestart /SC ONCE /SD 01/01/2000 /ST 00:00 /TR "$ps `"$rs`"" /RL LIMITED | Out-Null
schtasks /Create /F /TN ZargarRestartOverride /SC ONCE /SD 01/01/2000 /ST 00:00 /TR "$ps `"$rs`" -Force" /RL LIMITED | Out-Null
Write-Host "installed: ZargarWatchdog (every 3 min), ZargarWatchdogLogon (at logon, best-effort), ZargarRestart (on demand; refuses over in-flight work), ZargarRestartOverride (emergency)"
schtasks /Query /TN ZargarWatchdog /FO LIST | Select-String "Status|Next Run|Task To Run"
