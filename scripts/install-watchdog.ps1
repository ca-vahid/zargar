# Register the engine's watchdog + restart tasks under the CURRENT user (no elevation needed).
#   ZargarWatchdog  — every 3 minutes and at logon: start the engine if :8420 is not answering
#   ZargarRestart   — on demand only: restart the engine (deploys: schtasks /Run /TN ZargarRestart)
# Both run start.ps1 from the Task Scheduler's own process tree, so the engine no longer dies when
# the assistant that happened to start it restarts (docs/PLATFORM-RULES.md 2026-09-08).
#   scripts\install-watchdog.ps1            install / refresh
#   scripts\install-watchdog.ps1 -Remove    remove both tasks
param([switch]$Remove)
$ps = "powershell -NoProfile -ExecutionPolicy Bypass -File"
$wd = Join-Path $PSScriptRoot "watchdog.ps1"
if ($Remove) {
  schtasks /Delete /TN ZargarWatchdog /F | Out-Null
  schtasks /Delete /TN ZargarRestart /F | Out-Null
  Write-Host "removed ZargarWatchdog and ZargarRestart"
  exit 0
}
schtasks /Create /F /TN ZargarWatchdog /SC MINUTE /MO 3 /TR "$ps `"$wd`"" /RL LIMITED | Out-Null
schtasks /Create /F /TN ZargarWatchdogLogon /SC ONLOGON /TR "$ps `"$wd`"" /RL LIMITED | Out-Null
schtasks /Create /F /TN ZargarRestart /SC ONCE /SD 01/01/2000 /ST 00:00 /TR "$ps `"$wd`" -Force" /RL LIMITED | Out-Null
Write-Host "installed: ZargarWatchdog (every 3 min), ZargarWatchdogLogon (at logon), ZargarRestart (on demand)"
schtasks /Query /TN ZargarWatchdog /FO LIST | Select-String "Status|Next Run"
