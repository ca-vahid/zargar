# Zargar engine watchdog - ASCII ONLY (Windows PowerShell 5.1 reads a BOM-less file as ANSI) - meant to run from a Windows Scheduled Task under YOUR account
# (scripts\install-watchdog.ps1 registers it), NOT from a Claude/Codex shell: an engine started
# from an assistant's shell dies with that assistant's process tree (2026-09-04 and 2026-09-08,
# "Claude VM Service stopped" for a package update took the engine down for 9 minutes each time).
#
#   watchdog.ps1                 start the engine only if /api/health does not answer
#   watchdog.ps1 -Force          restart it (the deploy path: schtasks /Run /TN ZargarRestart) - REFUSES
#                                when /api/ops/restart-check says something is in flight (open technique
#                                trades, working entries/exits, venue orders, paid analyst reads)
#   watchdog.ps1 -Force -Override  restart anyway (schtasks /Run /TN ZargarRestartOverride) - an emergency,
#                                logged as such
#
# Every restart records the engine's state before (armed plans, open trades, pending exits, working
# orders) and compares it after (restoration check, PLATFORM-RULES 2026-09-09); a mismatch is logged
# as RESTORE MISMATCH with the missing ids and exits 4.
param([switch]$Force, [switch]$Override)
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
# --- readiness + the state to compare against after the restart (only when something is running)
$before = $null
if ($up) {
  try { $before = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/state" -TimeoutSec 6 } catch { $before = $null }
  try {
    $rc = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/restart-check?caller=watchdog" -TimeoutSec 6
    if (-not $rc.safe) {
      $why = ($rc.reasons -join "; ")
      if ($Override) { Log ("OVERRIDE: restarting over in-flight work: " + $why) }
      else { Log ("REFUSED restart: " + $why + "  (use ZargarRestartOverride / -Override for an emergency)"); exit 2 }
    }
  } catch { Log ("restart-check unavailable (" + $_.Exception.Message + ") - proceeding on the health check alone") }
}
Set-Content -Path $lock -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Log ("engine " + $(if ($Force) { "restart requested" } else { "DOWN - no answer on :8420" }) + " -> start.ps1 -Detach" + $(if ($Override) { " -Force" } else { "" }))
$startArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "start.ps1"), "-Detach")
if ($Override) { $startArgs += "-Force" }
& powershell @startArgs 2>&1 | ForEach-Object { Log ("  " + $_) }
$code = $LASTEXITCODE
Log ("start.ps1 exit " + $code)
if ($code -ne 0) { exit $code }
# --- restoration check: what was armed / open / working before must be back
if ($before -ne $null) {
  $ok = $false
  foreach ($i in 1..12) {
    Start-Sleep -Seconds 5
    try {
      $cmp = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/restore-check" -Method Post -ContentType "application/json" -Body ($before | ConvertTo-Json -Depth 6 -Compress) -TimeoutSec 8
      if ($cmp.ok) { $ok = $true; Log ("restore check OK: " + (($cmp.counts.PSObject.Properties | ForEach-Object { $_.Name + " " + $_.Value }) -join ", ")); break }
      $last = $cmp
    } catch { $last = $null }
  }
  if (-not $ok) {
    $missing = if ($last) { ($last.missing | ConvertTo-Json -Compress) } else { "restore-check unreachable" }
    Log ("RESTORE MISMATCH after restart: " + $missing)
    $snap = Join-Path $logDir ("restore-mismatch-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".json")
    @{ before = $before; after = $last } | ConvertTo-Json -Depth 8 | Set-Content -Path $snap
    exit 4
  }
}
exit 0
