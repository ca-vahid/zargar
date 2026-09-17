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
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir "watchdog.log"
function Log($m) { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) }
$up = $false
try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 4; $up = [bool]$h.ok } catch { $up = $false }
# 2026-09-16/17 (EM desk, PLATFORM-RULES; PFU-01): ONE 4 s probe timeout is not a dead engine. Classification is a
# pure function in watchdog-classify.ps1 (healthy | live-unhealthy | absent) over: a second probe 15 s later, THIS
# runtime's engine process (executable under backend\.venv), the engine log's freshness, and a time-based stall
# marker. A live engine that does not answer health is never permission to skip readiness / quiescence / the
# before-inventory: ordinary recovery is REFUSED (exit 2) and only the explicit override (-Override /
# ZargarRestartOverride) may replace it. Only `absent` (no bound process, or a stale log) takes the DOWN path below.
. (Join-Path $PSScriptRoot 'watchdog-classify.ps1')
$stallMarker = Join-Path $logDir "watchdog-stall.txt"
$classification = $null
if (-not $up -and -not $Force) {
  # probe tolerance (owner ask): 2 of 3 probes with 12 s timeouts before anything is called unhealthy
  Start-Sleep -Seconds 15
  $up2 = $false
  try { $h2 = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 12; $up2 = [bool]$h2.ok } catch { $up2 = $false }
  if (-not $up2) {
    Start-Sleep -Seconds 10
    try { $h3 = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 12; $up2 = [bool]$h3.ok } catch { $up2 = $false }
  }
  $logPath = Join-Path $root "backend\zargar-8420.log"
  $logAge = 999999
  if (Test-Path $logPath) { $logAge = [int]((Get-Date) - (Get-Item $logPath).LastWriteTime).TotalSeconds }
  $markerAt = $null
  if (Test-Path $stallMarker) { $markerAt = (Get-Item $stallMarker).LastWriteTime }
  $bound = Get-BoundEngineProcessCount -Root $root
  $classification = Get-EngineClassification -Probe1 $up -Probe2 $up2 -BoundProcesses $bound -LogAgeS $logAge -MarkerAt $markerAt -Now (Get-Date) -ReadOnly:$ProbeOnly
  if ($ProbeOnly) { Log ("probe-only: class=" + $classification.class + " persisted=" + $classification.persisted + " - " + $classification.reason); exit 0 }
  switch ($classification.markerAction) {
    'set'   { Set-Content -Path $stallMarker -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss") }
    'clear' { if (Test-Path $stallMarker) { Remove-Item $stallMarker -Force }; if (Test-Path ($stallMarker + ".alerted")) { Remove-Item ($stallMarker + ".alerted") -Force } }
  }
  if ($classification.class -eq 'healthy') { Log ("health answered late (" + $classification.reason + ") - no action"); exit 0 }
  if ($classification.class -eq 'live-unhealthy') {
    if ($Override) { Log ("OVERRIDE: live engine not answering health (" + $classification.reason + "; identity " + $script:WatchdogIdentity + ") - replacing it on explicit override") }
    else {
      $msg = ("REFUSED restart: engine alive but not answering health (" + $classification.reason + "; identity " + $script:WatchdogIdentity + "). Readiness is unavailable so ordinary recovery is refused. " +
              "HUMAN NEXT STEP: check the engine (scripts\logs.ps1, /api/health); if positions are held and it stays stalled, run the scheduled task ZargarRestartOverride (or watchdog.ps1 -Force -Override) - that override is the only path that replaces a live engine.")
      Log $msg
      $sent = Send-WatchdogAlert -Root $root -Text ("Zargar watchdog: " + $msg) -OnceFile ($stallMarker + ".alerted")
      Log ("escalation " + $(if ($sent) { "sent (Telegram, once per stall marker)" } else { "not sent (no Telegram config, already alerted for this marker, or send failed)" }))
      exit 2
    }
  } else {
    Log ("DOWN confirmed: " + $classification.reason)
  }
}
if ($ProbeOnly) { Log ("probe-only: class=healthy (first probe ok)"); exit 0 }
if ($up -and -not $Force) {
  # PFU-01 acceptance: a first-probe recovery clears an old stall marker (and its alert companion) so two unrelated
  # stalls never chain - this is the normal healthy tick, so it must do the clearing too, not only the classifier path.
  if (Test-Path $stallMarker) { Remove-Item $stallMarker -Force; Log "engine healthy on the first probe - stall marker cleared" }
  if (Test-Path ($stallMarker + ".alerted")) { Remove-Item ($stallMarker + ".alerted") -Force }
  exit 0
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
