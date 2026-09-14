# Restart Zargar SAFELY - the one script every desk should use to deploy.
#
#   scripts\restart.ps1                stop -> start -> WAIT for /api/health (the whole point)
#   scripts\restart.ps1 -Expect 0.7.15 additionally require that version to report healthy
#   scripts\restart.ps1 -Force         restart over in-flight work (open technique trades, working orders,
#                                      analyst runs) - the readiness check refuses otherwise; logged as an override
#
# Why this exists (2026-09-08): three market-hours outages in three sessions
# came from a desk stopping the app and walking away before it was back
# (09-04 x2, 09-08 14:24-14:35 ET). Separately, intake windows stacked up 9
# deep because an UNELEVATED restart cannot close ELEVATED windows - the
# Stop-Process fails silently. This script:
#   1. stops the server + helpers (and REPORTS anything it could not kill,
#      instead of failing silently - run it elevated to clean those too)
#   2. starts via start.ps1 -Detach (which rebuilds dist when needed)
#   3. WAITS for /api/health - it does not exit 0 until the app answers
#   4. prints the restored armed-plan/managed-position counts
#
# Exit codes: 0 healthy / 1 start failed / 2 refused (work in flight) / 4 health never came back / 5 stale version
#             6 restoration check failed (state before vs after, logs\restore-mismatch-*.json)
# ASCII ONLY in this file: the ZargarRestart task runs it under Windows PowerShell 5.1, which reads a
# BOM-less file as ANSI - an em dash inside a string literal made the whole script a parse error
# (2026-09-09 01:20 ET: "The string is missing the terminator", exit 1, nothing restarted).
param(
  [string]$Expect = "",
  [switch]$Force
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot 'deployment-lock.ps1')
$restartMutex = Enter-ZargarDeployment $Root -Restart
try {
$handoffPath = Join-Path $Root 'logs/deployment-pending.json'
$handoff = $null
if (Test-Path -LiteralPath $handoffPath) {
  $handoff = Get-Content -LiteralPath $handoffPath -Raw | ConvertFrom-Json
  if ([DateTimeOffset]::Parse($handoff.expiresAt) -le [DateTimeOffset]::UtcNow) { throw 'Deployment handoff expired; revalidate source and artifact before restart.' }
  if ((git -C $Root rev-parse HEAD).Trim() -ne $handoff.target) { throw 'Deployment target changed after handoff; restart refused.' }
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Root 'frontend/dist/index.html')).Hash -ne $handoff.artifactSha256) { throw 'Deployment artifact changed after handoff; restart refused.' }
  if ($Expect -and $Expect -ne $handoff.expectedVersion) { throw 'Expected version disagrees with deployment handoff.' }
  $Expect = $handoff.expectedVersion
}
$receiptPath = Join-Path $Root 'logs/deployment-receipt.json'
if (-not $handoff -and -not $Force -and (Test-Path -LiteralPath $receiptPath)) {
  $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
  if ($receipt.phase -eq 'verified' -and $receipt.target -eq (git -C $Root rev-parse HEAD).Trim() -and
      ([DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse($receipt.completedAt)).TotalMinutes -lt 5) {
    try { $recentHealth = Invoke-RestMethod http://127.0.0.1:8420/api/health -TimeoutSec 4 } catch { $recentHealth = $null }
    if ($recentHealth.ok -and $recentHealth.version -eq $receipt.expectedVersion -and (-not $Expect -or $Expect -eq $recentHealth.version)) {
      Write-Host 'This commit was just deployed and is healthy; duplicate restart skipped.'
      exit 0
    }
  }
}
# the scheduler runs this in a console nobody sees: keep a transcript per run in logs/restart-<ts>.log
$logDirEarly = Join-Path $Root "logs"
if (-not (Test-Path $logDirEarly)) { New-Item -ItemType Directory -Path $logDirEarly | Out-Null }
try { Start-Transcript -Path (Join-Path $logDirEarly ("restart-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")) -Append | Out-Null } catch { }

function Fail($m, $code=1) { Write-Host $m -ForegroundColor Red; exit $code }
function Step($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "! $m" -ForegroundColor Yellow }

# --- -1. readiness: what would this restart interrupt? (2026-09-09, PLATFORM-RULES invariant 18) -----
# "No open positions" was never the test. The engine enumerates open technique trades, working
# entries/exits, venue orders and paid analyst reads across EVERY technique; refuse unless -Force
# (which is logged as an override). The state captured here is compared after the restart.
$stateBefore = $null
$engineUp = $false
$lockDir = Join-Path $Root "logs"
if (-not (Test-Path $lockDir)) { New-Item -ItemType Directory -Path $lockDir | Out-Null }
# --- R4 (2026-09-14): exclusive deploy lease + a VERIFIED entry pause -------------------------------
# Two callers (a task, a shell, the watchdog) must never both proceed; the lease file is created atomically and
# names its owner. A pause that is not confirmed by the engine (POST failed, or the state still says
# quiesced=false) is missing evidence: the ordinary path refuses; only -Force may continue (an override).
# Compatibility names retained; the shared helper owns the OS lock and deploy.lock marker.
function Acquire-DeployLease { return $true }
function Release-DeployLease { } # outer finally releases only the actual owner
function Confirm-EntryPause {
  # returns $true only when the engine CONFIRMED the pause: the POST answered quiesced=true AND the state reads quiesced=true
  try { $q = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/quiesce?minutes=5" -Method Post -TimeoutSec 6 } catch { Warn ("entry pause request failed: " + $_.Exception.Message); return $false }
  if (-not ($q -is [System.Management.Automation.PSCustomObject]) -or -not $q.quiesced) { Warn "entry pause not acknowledged by the engine"; return $false }
  try { $st = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/state" -TimeoutSec 6 } catch { Warn ("entry pause could not be verified: " + $_.Exception.Message); return $false }
  if (-not ($st -is [System.Management.Automation.PSCustomObject]) -or -not $st.quiesced) { Warn "entry pause NOT in effect (state says quiesced=false)"; return $false }
  return $true
}
if (-not (Acquire-DeployLease)) { Fail "Not safe to restart: another deploy holds the lease (R4)." 7 }
try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 4; $engineUp = $true } catch { $engineUp = $false }
if ($engineUp) {
  # R1/R4: suspend NEW entries (self-expiring, 5 min) before the inventory is captured - and VERIFY it took
  if (-not (Confirm-EntryPause)) {
    if (-not $Force) { Release-DeployLease; Fail "Not safe to restart: the entry pause was not confirmed by the engine (R4). Wait, or run again with -Force (an override, journaled)." 2 }
    Warn "-Force: restarting without a confirmed entry pause (override)"
  }
  try { $stateBefore = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/state" -TimeoutSec 6 } catch { $stateBefore = $null }
  # an older engine answers the SPA shell (or nothing): no state, no restoration check
  if (-not ($stateBefore -is [System.Management.Automation.PSCustomObject]) -or -not ($stateBefore.PSObject.Properties.Name -contains "armed")) { $stateBefore = $null }
  try {
    $rc = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/restart-check?caller=restart.ps1" -TimeoutSec 6
    if (-not ($rc -is [System.Management.Automation.PSCustomObject]) -or -not ($rc.PSObject.Properties.Name -contains "safe")) {
      throw "no readiness answer (older engine or a non-JSON reply)"
    }
    if (-not $rc.safe) {
      foreach ($r in $rc.reasons) { Warn ("in flight: " + $r) }
      if (-not $Force) { try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/quiesce?release=true" -Method Post -TimeoutSec 6 } catch { }; Release-DeployLease; Warn "Not safe to restart now. Wait, or run again with -Force (an override, journaled)."; exit 2 }
      Warn "-Force: restarting over the work listed above (override)"
    }
  } catch {
    Warn ("readiness unavailable (" + $_.Exception.Message + ") - missing evidence is not a safe inventory")
    if (-not $Force) { try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/quiesce?release=true" -Method Post -TimeoutSec 6 } catch { }; Release-DeployLease; Fail "Not safe to restart: the engine could not report what is in flight. Wait, or run again with -Force (an override, journaled)." 2 }
    Warn "-Force: restarting without a readiness answer (override)"
  }
}

# --- 0. hold the watchdog off ---------------------------------------------------
# ZargarWatchdog ticks every 3 minutes and starts the engine whenever /api/health is
# silent. A restart is ~45 s of silence, and on 2026-09-09 01:25 ET the tick landed
# inside it: a SECOND engine started, both ran restore + schedulers on one database,
# health hung for two minutes and the duplicate only exited when its bind failed.
# The watchdog honours an age-based lock (logs\watchdog.lock < 180 s = skip), so
# stamp it here before stopping anything.
Set-Content -Path (Join-Path $lockDir "watchdog.lock") -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss")

# --- 1. stop, elevation-aware ------------------------------------------------
# match by PROCESS NAME + command line, never by command line alone: an assistant's shell whose command
# text merely mentions the engine module was killed by this step (2026-09-09 09:33 ET, twice)
$pyPatterns = "zargar\.main|discord_gateway|em_ingest|discord_watch"
$psPatterns = "discord-intake\.ps1|em-ingest\.ps1"
$leftAlive = @()
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.ProcessId -ne $PID -and (
      ($_.Name -match '^python' -and $_.CommandLine -match $pyPatterns) -or
      ($_.Name -match '^(pwsh|powershell)' -and $_.CommandLine -match $psPatterns -and $_.CommandLine -match '-File')) } |
  ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -Confirm:$false -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 200
    if (Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue) {
      $leftAlive += "$($_.ProcessId) $($_.Name)"
    }
  }
if ($leftAlive.Count -gt 0) {
  Warn ("Could NOT stop (likely elevated, this shell is not): " + ($leftAlive -join ", "))
  Warn "They will keep running - re-run this script from an elevated terminal to clean them."
}
Start-Sleep -Seconds 2

# --- 2. start ------------------------------------------------------------------
# splat a HASHTABLE: under Windows PowerShell 5.1 an array splat passes "-Detach" as a positional string,
# not as the switch, and start.ps1 then ran the engine in this console's FOREGROUND (2026-09-09 09:26 ET:
# the restart never reached its health wait or restoration check)
$args2 = @{ Detach = $true }; if ($Force) { $args2.Force = $true }
& (Join-Path $Root "scripts\start.ps1") @args2
if ($LASTEXITCODE -ne 0) { Warn "start.ps1 exited $LASTEXITCODE"; exit 1 }

# --- 3. WAIT for health - never walk away from a dark app ----------------------
Step "Waiting for /api/health ..."
$deadline = (Get-Date).AddSeconds(180)
$h = $null
while ((Get-Date) -lt $deadline) {
  try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 3; break }
  catch { Start-Sleep -Seconds 3 }
}
if (-not $h) { Warn "App did NOT come back within 180s - investigate NOW, do not walk away."; exit 4 }
if ($Expect -and ($h.version -ne $Expect)) {
  Warn "App is up but on v$($h.version), expected v$Expect (stale checkout?)"; exit 5
}
Step ("Healthy: v" + $h.version + " | armed " + $h.local.armed + " | runs in flight " + $h.local.techniqueRunning)

# --- 4. restoration check: what was armed / open / working before must be back (by id) ---------
if ($stateBefore -ne $null) {
  $ok = $false; $last = $null
  foreach ($i in 1..12) {
    try {
      $cmp = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/restore-check" -Method Post -ContentType "application/json" -Body ($stateBefore | ConvertTo-Json -Depth 6 -Compress) -TimeoutSec 8
      $last = $cmp
      if ($cmp.ok) { $ok = $true; break }
    } catch { }
    Start-Sleep -Seconds 5
  }
  if ($ok) {
    Step ("Restore check OK: " + (($last.counts.PSObject.Properties | ForEach-Object { $_.Name + " " + $_.Value }) -join ", "))
  } else {
    $snap = Join-Path $lockDir ("restore-mismatch-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".json")
    @{ before = $stateBefore; after = $last } | ConvertTo-Json -Depth 8 | Set-Content -Path $snap
    if ($last) { Warn ("RESTORE MISMATCH: " + ($last.missing | ConvertTo-Json -Compress) + " - saved " + $snap) }
    else { Warn ("RESTORE CHECK unreachable - saved " + $snap) }
    Release-DeployLease
    exit 6
  }
}
if ($handoff) {
  @{ phase='verified'; target=$handoff.target; expectedVersion=$Expect; artifactSha256=$handoff.artifactSha256; completedAt=[DateTimeOffset]::UtcNow.ToString('o'); ownerPid=$PID } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Root 'logs/deployment-receipt.json') -Encoding ASCII
  Remove-Item -LiteralPath $handoffPath
}
Release-DeployLease
exit 0
} finally { Exit-ZargarDeployment $restartMutex }
