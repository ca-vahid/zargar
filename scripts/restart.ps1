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
  [switch]$Force,
  [switch]$AllowElevated
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot 'deployment-lock.ps1')
# the scheduler runs this in a console nobody sees: the transcript starts BEFORE anything can refuse, so a run that
# exits without restarting always leaves logs/restart-<ts>.log saying why (2026-09-15: the ZargarRestart task fired
# while the watchdog was mid-start exited 1 with no transcript - "nothing happened")
$logDirEarly = Join-Path $Root "logs"
if (-not (Test-Path $logDirEarly)) { New-Item -ItemType Directory -Path $logDirEarly | Out-Null }
try { Start-Transcript -Path (Join-Path $logDirEarly ("restart-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")) -Append | Out-Null } catch { }
# elevation pre-flight BEFORE the lease and BEFORE anything is stopped (2026-09-19): an elevated shell would stop the
# engine and then have start.ps1 refuse to start it - the app went dark until someone ran the task
$elevationRefusal = Test-ZargarDoorElevation (Get-ZargarElevation) ([bool]$AllowElevated)
if ($elevationRefusal) {
  Write-Host ("x Not restarting: " + $elevationRefusal) -ForegroundColor Red
  try { Stop-Transcript | Out-Null } catch { }
  exit 8
}
# one door at a time: wait up to 5 minutes for another door (the watchdog's start after a manual stop, another
# desk's deploy) instead of failing on the spot
try { $restartMutex = Enter-ZargarDeployment $Root -Restart -WaitSeconds 300 }
catch {
  Write-Host ("x Not restarting: " + $_.Exception.Message) -ForegroundColor Red
  try { Stop-Transcript | Out-Null } catch { }
  exit 7
}
# who is driving this door: deploy.ps1 sets it, the ZargarRestart task / a shell leaves it empty
$callerSetHere = $false
if (-not $env:ZARGAR_DEPLOY_CALLER) { $env:ZARGAR_DEPLOY_CALLER = 'restart.ps1'; $callerSetHere = $true }
$script:restartFinished = $false
try {
$handoffPath = Join-Path $Root 'logs/deployment-pending.json'
$handoff = $null
$handoffManifest = $null
if (Test-Path -LiteralPath $handoffPath) {
  $handoff = Get-Content -LiteralPath $handoffPath -Raw | ConvertFrom-Json
  # KFIN-04: clean reviewed source AND the manifest of the COMPLETE built artifact (every file under
  # frontend/dist), not only HEAD and dist/index.html; a refusal is a terminal 'failed' on the receipt
  try { $handoffManifest = Assert-ZargarHandoff $Root $handoff $Expect }
  catch { $null = Set-ZargarReceiptPhase $Root 'failed' $_.Exception.Message $env:ZARGAR_DEPLOY_CALLER; $script:restartFinished = $true; throw }
  $Expect = $handoff.expectedVersion
}
# already running HEAD (the watchdog or another door just brought this commit up): nothing to bounce
if (-not $handoff -and -not $Force) {
  try { $liveHealth = Invoke-RestMethod http://127.0.0.1:8420/api/health -TimeoutSec 4 } catch { $liveHealth = $null }
  $headSha = (git -C $Root rev-parse HEAD).Trim()
  if ($liveHealth.ok -and $liveHealth.build -and ($liveHealth.build -eq $headSha) -and (-not $Expect -or $Expect -eq $liveHealth.version)) {
    Write-Host ("> Already running this checkout (build " + $headSha.Substring(0,12) + ", v" + $liveHealth.version + ") and healthy; nothing to restart.")
    Exit-ZargarDeployment $restartMutex
    try { Stop-Transcript | Out-Null } catch { }
    exit 0
  }
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

function Step($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "! $m" -ForegroundColor Yellow }
# KFIN-04: every non-zero exit is a TERMINAL phase on the receipt (failed | deferred) with its reason,
# so a deployment never stays 'restarting'; the pending handoff is kept (the reviewed artifact is still
# valid until it expires) and named in the receipt so the next run knows it is finishing THIS deploy.
function Leave($code, $why) {
  if ($code -ne 0 -and $handoff) {
    $phase = $(if ($code -eq 2) { 'deferred' } else { 'failed' })
    try { $r = Set-ZargarReceiptPhase $Root $phase ("restart.ps1 exit " + $code + ": " + $why) $env:ZARGAR_DEPLOY_CALLER
          if (-not $r.PSObject.Properties['handoffPending']) { $r | Add-Member -NotePropertyName handoffPending -NotePropertyValue $true; Write-ZargarReceipt $Root $r } } catch { }
  }
  $script:restartFinished = $true
  exit $code
}
function Fail($m, $code=1) { Write-Host $m -ForegroundColor Red; Leave $code $m }

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
# health-500 follow-up (2026-09-14 incident, PLATFORM-RULES): a process that ANSWERS /api/health with an HTTP error is
# a LIVE, unhealthy engine - not an absent one. Its entry pause, inventory and readiness safeguards still apply (the
# /api/ops endpoints answered throughout the 17:37 incident while /api/health was 500). Only a refused connection /
# no response means "no process".
$engineUp = $false; $engineHealthy = $false; $restoration = "skipped-no-baseline"; $inventoryPath = $null
try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 4; $engineUp = $true; $engineHealthy = $true }
catch {
  $resp = $_.Exception.Response
  if ($resp -ne $null) {
    $engineUp = $true
    $code = ""; try { $code = [int]$resp.StatusCode } catch { }
    Warn ("engine is REACHABLE but UNHEALTHY (HTTP " + $code + " on /api/health) - treated as a live process: pause, inventory and readiness still apply")
  } else { $engineUp = $false }
}
if ($engineUp) {
  # R1/R4: suspend NEW entries (self-expiring, 5 min) before the inventory is captured - and VERIFY it took
  if (-not (Confirm-EntryPause)) {
    if (-not $Force) { Release-DeployLease; Fail "Not safe to restart: the entry pause was not confirmed by the engine (R4). Wait, or run again with -Force (an override, journaled)." 2 }
    Warn "-Force: restarting without a confirmed entry pause (override)"
  }
  try { $stateBefore = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/state" -TimeoutSec 6 } catch { $stateBefore = $null }
  # the before-inventory is PERSISTED by id (armed plan ids, open trades, working/resting orders) so a restoration
  # verdict is never inferred from counts alone; a missing inventory is recorded as such, never as "absent process"
  $inventoryPath = Join-Path $lockDir ("restart-inventory-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".json")
  if ($stateBefore -is [System.Management.Automation.PSCustomObject]) {
    @{ capturedAt = [DateTimeOffset]::UtcNow.ToString('o'); healthy = $engineHealthy; before = $stateBefore } | ConvertTo-Json -Depth 8 | Set-Content -Path $inventoryPath -Encoding ASCII
    Step ("Before-inventory saved: " + $inventoryPath)
  } else {
    Warn "before-inventory UNAVAILABLE (/api/ops/state gave no state): restoration will be reported as skipped-no-baseline"
    @{ capturedAt = [DateTimeOffset]::UtcNow.ToString('o'); healthy = $engineHealthy; before = $null; note = "ops state unavailable" } | ConvertTo-Json -Depth 3 | Set-Content -Path $inventoryPath -Encoding ASCII
  }
  # an older engine answers the SPA shell (or nothing): no state, no restoration check
  if (-not ($stateBefore -is [System.Management.Automation.PSCustomObject]) -or -not ($stateBefore.PSObject.Properties.Name -contains "armed")) { $stateBefore = $null }
  try {
    $rc = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/restart-check?caller=restart.ps1" -TimeoutSec 6
    if (-not ($rc -is [System.Management.Automation.PSCustomObject]) -or -not ($rc.PSObject.Properties.Name -contains "safe")) {
      throw "no readiness answer (older engine or a non-JSON reply)"
    }
    if (-not $rc.safe) {
      foreach ($r in $rc.reasons) { Warn ("in flight: " + $r) }
      if (-not $Force) { try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/quiesce?release=true" -Method Post -TimeoutSec 6 } catch { }; Release-DeployLease; Warn "Not safe to restart now. Wait, or run again with -Force (an override, journaled)."; Leave 2 ("in flight: " + ($rc.reasons -join "; ")) }
      Warn "-Force: restarting over the work listed above (override)"
    }
  } catch {
    Warn ("readiness unavailable (" + $_.Exception.Message + ") - missing evidence is not a safe inventory")
    if (-not $Force) { try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/quiesce?release=true" -Method Post -TimeoutSec 6 } catch { }; Release-DeployLease; Fail "Not safe to restart: the engine could not report what is in flight. Wait, or run again with -Force (an override, journaled)." 2 }
    Warn "-Force: restarting without a readiness answer (override)"
  }
}

# --- -0.5. the TARGET must import the health contract BEFORE the running process is stopped ----------------
# (2026-09-14: the Ledger merge dropped build_sha; the process restarted on that checkout 10 s before the file was
# repaired and answered 500 for six minutes - a post-start file rewrite is not a loaded fix)
$py = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (Test-Path $py) {
  Push-Location (Join-Path $Root "backend")
  $prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  $probe = & $py -c 'import zargar, zargar.api.app; zargar.build_sha(); print(zargar.__version__)' 2>&1
  $probeExit = $LASTEXITCODE
  $ErrorActionPreference = $prevEap
  Pop-Location
  if ($probeExit -ne 0) {
    if (-not $Force) { Release-DeployLease; Fail ("Not safe to restart: the target checkout does not import the health contract - " + (($probe | Out-String).Trim() -replace "`r?`n", " | ")) 8 }
    Warn "-Force: restarting a target that FAILS the import probe (override)"
  } else { Step ("Target imports the health contract (backend " + (($probe | Select-Object -Last 1) | Out-String).Trim() + ")") }
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
$args2 = @{ Detach = $true }; if ($Force) { $args2.Force = $true }; if ($AllowElevated) { $args2.AllowElevated = $true }
if ($handoff) { $args2.NoBuild = $true } # the exact artifact was built and verified under the deployment owner
& (Join-Path $Root "scripts\start.ps1") @args2
if ($LASTEXITCODE -ne 0) { Warn "start.ps1 exited $LASTEXITCODE"; Leave 1 ("start.ps1 exited " + $LASTEXITCODE) }

# --- 3. WAIT for health - never walk away from a dark app ----------------------
Step "Waiting for /api/health ..."
$deadline = (Get-Date).AddSeconds(180)
$h = $null
while ((Get-Date) -lt $deadline) {
  try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 3; break }
  catch { Start-Sleep -Seconds 3 }
}
if (-not $h) { Warn "App did NOT come back within 180s - investigate NOW, do not walk away."; Leave 4 "health never came back within 180s" }
if ($Expect -and ($h.version -ne $Expect)) {
  Warn "App is up but on v$($h.version), expected v$Expect (stale checkout?)"; Leave 5 ("healthy on v" + $h.version + ", expected v" + $Expect)
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
    $restoration = "ok"
    Step ("Restore check OK: " + (($last.counts.PSObject.Properties | ForEach-Object { $_.Name + " " + $_.Value }) -join ", "))
  } else {
    $restoration = "mismatch"
    $snap = Join-Path $lockDir ("restore-mismatch-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".json")
    @{ before = $stateBefore; after = $last } | ConvertTo-Json -Depth 8 | Set-Content -Path $snap
    if ($last) { Warn ("RESTORE MISMATCH: " + ($last.missing | ConvertTo-Json -Compress) + " - saved " + $snap) }
    else { Warn ("RESTORE CHECK unreachable - saved " + $snap) }
    Release-DeployLease
    Leave 6 ("restoration check failed - " + $snap)
  }
}
# --- 5. the receipt: the SAME runtime identity start.ps1 stamped when it launched the engine ------
# (logs/runtime-identity.json: HEAD, clean-source verdict, artifact manifest, script hashes, caller)
$identity = $null
try { $identity = Get-Content -LiteralPath (Join-Path $Root 'logs/runtime-identity.json') -Raw | ConvertFrom-Json } catch { $identity = $null }
if ($handoff) {
  $actualManifest = Get-ZargarArtifactManifest $Root
  if ($actualManifest.ManifestSha256 -ne $handoff.artifactManifestSha256) {
    $null = Set-ZargarReceiptPhase $Root 'failed' 'Artifact changed after verified handoff; deployment receipt refused.' $env:ZARGAR_DEPLOY_CALLER
    $script:restartFinished = $true
    throw 'Artifact changed after verified handoff; deployment receipt refused.'
  }
  if ($identity -and $identity.artifactManifestSha256 -ne $handoff.artifactManifestSha256) {
    $null = Set-ZargarReceiptPhase $Root 'failed' 'The engine was launched from a different artifact than the handoff; deployment receipt refused.' $env:ZARGAR_DEPLOY_CALLER
    $script:restartFinished = $true
    throw 'The engine was launched from a different artifact than the handoff; deployment receipt refused.'
  }
  Write-ZargarReceipt $Root ([pscustomobject]@{ phase='verified'; target=$handoff.target; expectedVersion=$Expect
    artifactManifestSha256=$actualManifest.ManifestSha256; artifactFileCount=$actualManifest.FileCount
    artifactSha256=$actualManifest.Files['index.html']; completedAt=[DateTimeOffset]::UtcNow.ToString('o'); ownerPid=$PID
    caller=$env:ZARGAR_DEPLOY_CALLER; runtime=$identity; healthyVersion=$h.version
    restoration=$restoration; healthBuild=$h.build; beforeInventory=$inventoryPath })
  Remove-Item -LiteralPath $handoffPath
} else {
  # a plain restart (task / shell) is not a deployment: record the identity it brought up without
  # claiming 'verified' (that word belongs to a reviewed handoff and drives the duplicate-skip rule)
  try {
    $plain = [pscustomobject]@{ phase='restarted'; target=$(if ($identity) { $identity.head } else { $null }); expectedVersion=$Expect
      artifactManifestSha256=$(if ($identity) { $identity.artifactManifestSha256 } else { $null })
      completedAt=[DateTimeOffset]::UtcNow.ToString('o'); ownerPid=$PID; caller=$env:ZARGAR_DEPLOY_CALLER; runtime=$identity
      healthyVersion=$h.version; force=[bool]$Force }
    Write-ZargarReceipt $Root $plain
  } catch { Warn ("receipt not written: " + $_.Exception.Message) }
}
$script:restartFinished = $true
Release-DeployLease
exit 0
} finally {
  # an exception (not a Leave) that escaped with a handoff in flight is a terminal 'failed' too
  if ($handoff -and -not $script:restartFinished) {
    try { $null = Set-ZargarReceiptPhase $Root 'failed' 'restart.ps1 ended by an unhandled error; see the restart transcript' $env:ZARGAR_DEPLOY_CALLER } catch { }
  }
  if ($callerSetHere) { Remove-Item Env:ZARGAR_DEPLOY_CALLER -ErrorAction SilentlyContinue }
  Exit-ZargarDeployment $restartMutex
}
