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
param([switch]$Force, [switch]$Override, [switch]$ProbeOnly)
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "logs"
$log = Join-Path $logDir "watchdog.log"
# -ProbeOnly is a diagnostic: it creates no directory, writes no log line and touches no recovery state (stdout only).
if (-not $ProbeOnly -and -not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
function Log($m) { if ($ProbeOnly) { Write-Output $m; return }; Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) }
# 2026-09-17 (EM desk, PFU-01 re-review): classification AND the caller decision live in watchdog-classify.ps1 as pure
# functions; this file only supplies the real actions. healthy | live-unhealthy | uncertain | absent - a live process
# with a quiet log is LIVE; a discovery failure is UNCERTAIN; both refuse ordinary recovery (with or without -Force)
# because readiness is unavailable, and only -Override replaces a living engine. Only `absent` takes the DOWN path.
. (Join-Path $PSScriptRoot 'watchdog-classify.ps1')
$stallMarker = Join-Path $logDir "watchdog-stall.txt"
$engineLog = Join-Path $root "backend\zargar-8420.log"
$actions = @{
  Probe       = { param($t) try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec $t; return [bool]$h.ok } catch { return $false } }
  Sleep       = { param($s) Start-Sleep -Seconds $s }
  Liveness    = { $age = 999999; if (Test-Path $engineLog) { $age = [int]((Get-Date) - (Get-Item $engineLog).LastWriteTime).TotalSeconds }
                  $b = Get-BoundEngineProcessCount -Root $root; return @{ bound = $b; logAgeS = $age; identity = $script:WatchdogIdentity } }
  ReadMarker  = { if (Test-Path $stallMarker) { return (Get-Item $stallMarker).LastWriteTime } else { return $null } }
  SetMarker   = { Set-Content -Path $stallMarker -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss") }
  ClearMarker = { if (Test-Path $stallMarker) { Remove-Item $stallMarker -Force }; if (Test-Path ($stallMarker + ".alerted")) { Remove-Item ($stallMarker + ".alerted") -Force } }
  Log         = { param($m) Log $m }
  Alert       = { param($t) return (Send-WatchdogAlert -Root $root -Text $t -OnceFile ($stallMarker + ".alerted")) }
  Now         = { Get-Date }
}
$decision = Invoke-WatchdogDecision -Force ([bool]$Force) -Override ([bool]$Override) -ProbeOnly ([bool]$ProbeOnly) -Actions $actions
if ($ProbeOnly) { Write-Output ("probe-only: class=" + $decision.class + " - " + $decision.reason + $(if ($decision.identity) { " (identity " + $decision.identity + ")" } else { "" })); exit 0 }
switch ($decision.action) {
  'exit-healthy'     { exit 0 }
  'refuse'           { exit 2 }
  'proceed-force'    { $up = $true }        # health answers: readiness / quiesce / before-inventory run below
  'proceed-override' { $up = $false }       # explicit override over a live or uncertain engine (logged as OVERRIDE above)
  'proceed-down'     { $up = $false }       # no bound engine process: the DOWN path, nothing to quiesce
  default            { Log ("unexpected decision " + $decision.action + " - refusing"); exit 2 }
}
# one start at a time: a start takes ~30-60 s (start.ps1 stops the old process, rebuilds dist if stale, launches)
# and the 3-minute tick must not pile a second engine onto a restart in progress. The lock is age-based
# (never deleted), so a crash mid-start cannot wedge the watchdog either.
$lock = Join-Path $logDir "watchdog.lock"
if (Test-Path $lock) {
  $age = ((Get-Date) - (Get-Item $lock).LastWriteTime).TotalSeconds
  if ($age -lt 180) { Log ("a start began {0:N0}s ago - skipping this tick" -f $age); exit 0 }
}
. (Join-Path $PSScriptRoot 'deployment-lock.ps1')
try { $watchdogLease = Enter-ZargarDeployment $root } catch { Log $_.Exception.Message; exit 0 }
try {
# --- readiness + the state to compare against after the restart (only when something is running)
$before = $null
if ($up) {
  # R1/R4: suspend NEW entries (self-expiring, 5 min) before the inventory is captured - and VERIFY it took
  $q = $null; $st = $null; $paused = $false
  try { $q = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/quiesce?minutes=5" -Method Post -TimeoutSec 6 } catch { $q = $null }
  if ($q -is [System.Management.Automation.PSCustomObject] -and $q.quiesced) {
    try { $st = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/state" -TimeoutSec 6 } catch { $st = $null }
    if ($st -is [System.Management.Automation.PSCustomObject] -and $st.quiesced) { $paused = $true }
  }
  if (-not $paused) {
    if ($Override) { Log "OVERRIDE: entry pause not confirmed - restarting anyway" }
    else { Log "REFUSED restart: the entry pause was not confirmed by the engine (R4); use -Override for an emergency"; exit 2 }
  }
  try { $before = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/state" -TimeoutSec 6 } catch { $before = $null }
  # an older engine answers the SPA shell (or nothing): no state, no restoration check
  if (-not ($before -is [System.Management.Automation.PSCustomObject]) -or -not ($before.PSObject.Properties.Name -contains "armed")) { $before = $null }
  try {
    $rc = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/restart-check?caller=watchdog" -TimeoutSec 6
    if (-not ($rc -is [System.Management.Automation.PSCustomObject]) -or -not ($rc.PSObject.Properties.Name -contains "safe")) {
      throw "no readiness answer (older engine or a non-JSON reply)"
    }
    if (-not $rc.safe) {
      $why = ($rc.reasons -join "; ")
      if ($Override) { Log ("OVERRIDE: restarting over in-flight work: " + $why) }
      else { Log ("REFUSED restart: " + $why + "  (use ZargarRestartOverride / -Override for an emergency)"); try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/quiesce?release=true" -Method Post -TimeoutSec 6 } catch { }; exit 2 }
    }
  } catch {
    if ($Override) { Log ("OVERRIDE: readiness unavailable (" + $_.Exception.Message + ") - restarting anyway") }
    else { Log ("REFUSED restart: readiness unavailable (" + $_.Exception.Message + ") - missing evidence is not a safe inventory; use -Override"); try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/quiesce?release=true" -Method Post -TimeoutSec 6 } catch { }; exit 2 }
  }
}
Set-Content -Path $lock -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Log ("engine " + $(if ($Force) { "restart requested" } else { "DOWN - no answer on :8420" }) + " -> start.ps1 -Detach" + $(if ($Override) { " -Force" } else { "" }))
# KFIN-04: the same door and the same runtime identity as a task / manual restart - start.ps1 stamps
# logs\runtime-identity.json with caller=watchdog before it launches; the identity is logged here.
$env:ZARGAR_DEPLOY_CALLER = $(if ($Override) { "watchdog-override" } elseif ($Force) { "watchdog-restart" } else { "watchdog" })
$startArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "start.ps1"), "-Detach")
if ($Override) { $startArgs += "-Force" }
& powershell @startArgs 2>&1 | ForEach-Object { Log ("  " + $_) }
$code = $LASTEXITCODE
Log ("start.ps1 exit " + $code)
try {
  $identity = Get-Content -LiteralPath (Join-Path $logDir "runtime-identity.json") -Raw | ConvertFrom-Json
  Log ("runtime identity: head " + $identity.head + " artifact " + $identity.artifactManifestSha256 + " clean=" + $identity.clean + " caller=" + $identity.caller)
} catch { Log ("runtime identity unavailable: " + $_.Exception.Message) }
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

} finally { Exit-ZargarDeployment $watchdogLease }
