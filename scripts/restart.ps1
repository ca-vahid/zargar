# Restart Zargar SAFELY — the one script every desk should use to deploy.
#
#   scripts\restart.ps1                stop -> start -> WAIT for /api/health (the whole point)
#   scripts\restart.ps1 -Expect 0.7.15 additionally require that version to report healthy
#   scripts\restart.ps1 -Force         pass -Force to start.ps1 (restart over in-flight runs)
#
# Why this exists (2026-09-08): three market-hours outages in three sessions
# came from a desk stopping the app and walking away before it was back
# (09-04 x2, 09-08 14:24-14:35 ET). Separately, intake windows stacked up 9
# deep because an UNELEVATED restart cannot close ELEVATED windows — the
# Stop-Process fails silently. This script:
#   1. stops the server + helpers (and REPORTS anything it could not kill,
#      instead of failing silently — run it elevated to clean those too)
#   2. starts via start.ps1 -Detach (which rebuilds dist when needed)
#   3. WAITS for /api/health — it does not exit 0 until the app answers
#   4. prints the restored armed-plan/managed-position counts
#
# Exit codes: 0 healthy / 1 start failed / 4 health never came back / 5 stale version
param(
  [string]$Expect = "",
  [switch]$Force
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Step($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "! $m" -ForegroundColor Yellow }

# --- 1. stop, elevation-aware ------------------------------------------------
$patterns = "zargar\.main|discord_gateway|discord-intake\.ps1|em_ingest|em-ingest\.ps1|discord_watch"
$leftAlive = @()
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine -match $patterns -and $_.ProcessId -ne $PID } |
  ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -Confirm:$false -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 200
    if (Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue) {
      $leftAlive += "$($_.ProcessId) $($_.Name)"
    }
  }
if ($leftAlive.Count -gt 0) {
  Warn ("Could NOT stop (likely elevated, this shell is not): " + ($leftAlive -join ", "))
  Warn "They will keep running — re-run this script from an elevated terminal to clean them."
}
Start-Sleep -Seconds 2

# --- 2. start ------------------------------------------------------------------
$args2 = @("-Detach"); if ($Force) { $args2 += "-Force" }
& (Join-Path $Root "scripts\start.ps1") @args2
if ($LASTEXITCODE -ne 0) { Warn "start.ps1 exited $LASTEXITCODE"; exit 1 }

# --- 3. WAIT for health — never walk away from a dark app ----------------------
Step "Waiting for /api/health ..."
$deadline = (Get-Date).AddSeconds(180)
$h = $null
while ((Get-Date) -lt $deadline) {
  try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 3; break }
  catch { Start-Sleep -Seconds 3 }
}
if (-not $h) { Warn "App did NOT come back within 180s — investigate NOW, do not walk away."; exit 4 }
if ($Expect -and ($h.version -ne $Expect)) {
  Warn "App is up but on v$($h.version), expected v$Expect (stale checkout?)"; exit 5
}
Step ("Healthy: v" + $h.version + " · armed " + $h.local.armed + " · runs in flight " + $h.local.techniqueRunning)
exit 0
