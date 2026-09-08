# Zargar engine watchdog — meant to run from a Windows Scheduled Task under YOUR account
# (scripts\install-watchdog.ps1 registers it), NOT from a Claude/Codex shell: an engine started
# from an assistant's shell dies with that assistant's process tree (2026-09-04 and 2026-09-08,
# "Claude VM Service stopped" for a package update took the engine down for 9 minutes each time).
#
#   watchdog.ps1          start the engine only if /api/health does not answer
#   watchdog.ps1 -Force   restart it regardless (the deploy path: schtasks /Run /TN ZargarRestart)
param([switch]$Force)
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir "watchdog.log"
function Log($m) { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) }
$up = $false
try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 4; $up = [bool]$h.ok } catch { $up = $false }
if ($up -and -not $Force) { exit 0 }
# one start at a time: a start takes ~30-60 s (start.ps1 stops the old process, rebuilds dist if stale, launches)
# and the 3-minute tick must not pile a second engine onto a restart in progress. The lock is age-based
# (never deleted), so a crash mid-start cannot wedge the watchdog either.
$lock = Join-Path $logDir "watchdog.lock"
if (Test-Path $lock) {
  $age = ((Get-Date) - (Get-Item $lock).LastWriteTime).TotalSeconds
  if ($age -lt 180) { Log ("a start began {0:N0}s ago - skipping this tick" -f $age); exit 0 }
}
Set-Content -Path $lock -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Log ("engine " + $(if ($Force) { "restart requested" } else { "DOWN - no answer on :8420" }) + " -> start.ps1 -Detach")
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "start.ps1") -Detach 2>&1 | ForEach-Object { Log ("  " + $_) }
Log ("exit " + $LASTEXITCODE)
exit $LASTEXITCODE
