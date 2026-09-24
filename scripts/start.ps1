# Start (or restart) Zargar on http://127.0.0.1:8420
#
#   scripts\start.ps1            run in this terminal (Ctrl+C stops it)
#   scripts\start.ps1 -Detach    run hidden in the background and return
#   scripts\start.ps1 -Force     restart even if work is in flight (analyst runs, open technique trades,
#                                working entries/exits, venue orders) - the readiness check refuses otherwise
#   scripts\start.ps1 -NoBuild   skip the frontend rebuild check
#   scripts\start.ps1 -NoDiscord skip the experimental Discord intake window
#   scripts\start.ps1 -NoIngest  skip the EM ingestion worker window (video transcription)
#   scripts\stop.ps1             stop the server + helpers (run it from the terminal that OWNS the
#                                process; a non-elevated shell can then start.ps1 -Detach and own it)
#
# The Discord intake (a DM listener that feeds tips into the pipeline) launches
# by default in ITS OWN window (scripts\discord-intake.ps1). It is experimental
# and uses your Discord user token — see docs\techniques\tip\INTAKE-PLAN.md.
#
# To watch the running server's log (colorized, attach/detach anytime):
#   scripts\logs.ps1             see its header for -Tail/-Errors/-Match/-NoFollow
#
# What it does, in order:
#   1. safety check   refuses to kill in-flight analyst runs (they cost money)
#   2. stop           stops the old server on :8420, wherever it was started
#   3. postgres       docker compose up + wait until ready
#   4. frontend       rebuild dist only when sources changed
#   5. run            engine + API + UI as one process
#
# Exit codes: 0 ok / 1 build or launch failure / 2 refused (work in flight)
#             3 port 8420 held by something that is not Zargar
# After a detached restart the engine's state (armed plans, open trades, pending exits, working orders)
# is compared with the state before it (restoration check); a mismatch is printed loudly and saved to
# logs\restore-mismatch-<ts>.json (PLATFORM-RULES 2026-09-09).

param(
  [switch]$Force,
  [switch]$Detach,
  [switch]$NoBuild,
  [switch]$NoDiscord,
  [switch]$NoIngest,
  [switch]$AllowElevated
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot 'deployment-lock.ps1')
$startLease = Enter-ZargarDeployment $Root -Nested
try {
Set-Location $Root

function Step($msg) { Write-Host "> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "! $msg" -ForegroundColor Yellow }
function Fail($msg, $code) { Write-Host "x $msg" -ForegroundColor Red; exit $code }

# Stop any running Discord intake (gateway python + its host window) so a
# restart never stacks windows. Matches by command line, own processes only.
function Stop-DiscordIntake {
  try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -and (
          ($_.Name -match '^python' -and $_.CommandLine -match "discord_gateway") -or
          ($_.Name -match '^(pwsh|powershell)' -and $_.CommandLine -match "discord-intake\.ps1" -and $_.CommandLine -match '-File')) } |
      ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -Confirm:$false -ErrorAction SilentlyContinue
      }
  } catch { }
}

# Launch scripts\discord-intake.ps1 in its OWN window (never this terminal).
function Start-DiscordIntake {
  $intake = Join-Path $Root "scripts\discord-intake.ps1"
  if (-not (Test-Path $intake)) { Warn "discord-intake.ps1 missing - skipping intake"; return }
  $psHost = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
  if (-not $psHost) { $psHost = "powershell.exe" }
  Step "Launching Discord intake in its own window (experimental; -NoDiscord to skip)"
  Start-Process -FilePath $psHost `
    -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $intake `
    -WorkingDirectory $Root | Out-Null
}

# EM method ingestion worker (docs	echniques\enhanced-market\INGESTION-PLAN.md):
# transcribes the author's pre-trading videos for the EnhancedMarket pipeline.
# Own window, own venv (backend\.venv-ingest). EM-only; -NoIngest skips it.
function Stop-EmIngest {
  try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -and (
          ($_.Name -match '^python' -and $_.CommandLine -match "em_ingest") -or
          ($_.Name -match '^(pwsh|powershell)' -and $_.CommandLine -match "em-ingest\.ps1" -and $_.CommandLine -match '-File')) } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false -ErrorAction SilentlyContinue }
  } catch { }
}
function Start-EmIngest {
  $worker = Join-Path $Root "scripts\em-ingest.ps1"
  if (-not (Test-Path $worker)) { Warn "em-ingest.ps1 missing - skipping EM ingestion"; return }
  $psHost = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
  if (-not $psHost) { $psHost = "powershell.exe" }
  Step "Launching EM ingestion worker in its own window (-NoIngest to skip)"
  Start-Process -FilePath $psHost `
    -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $worker `
    -WorkingDirectory $Root | Out-Null
}

# --- 1. safety check ---------------------------------------------------------
# Never restart over live work: analyst reads in flight die with the process and
# each one costs money (2026-08-26: five restarts in one evening killed ~200
# reads). Armed plans are write-ahead and restore on startup - warning only.
$armedBefore = 0
try {
  $h = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 4
  $running = [int]$h.local.techniqueRunning
  $armed   = [int]$h.local.armed
  if ($running -gt 0 -and -not $Force) {
    Warn "$running analyst run(s) in flight - a restart would kill them (they cost money)."
    Fail "Wait for the batch to finish, or run again with -Force." 2
  }
  if ($running -gt 0) { Warn "-Force: restarting over $running in-flight run(s)" }
  if ($armed -gt 0)   { Warn "$armed armed plan(s) will be restored after the restart" }
  $armedBefore = $armed
  # 2026-09-09 (F75 review): "no open positions" was never the test. Ask the engine what a restart
  # would interrupt across EVERY technique + the order book, and keep its state for the check after.
  # R1/R4: suspend NEW entries (self-expiring, 5 min) before the inventory is captured - and VERIFY it took
  $q = $null; $st = $null; $paused = $false
  try { $q = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/quiesce?minutes=5" -Method Post -TimeoutSec 6 } catch { $q = $null }
  if ($q -is [System.Management.Automation.PSCustomObject] -and $q.quiesced) {
    try { $st = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/state" -TimeoutSec 6 } catch { $st = $null }
    if ($st -is [System.Management.Automation.PSCustomObject] -and $st.quiesced) { $paused = $true }
  }
  if (-not $paused) {
    if (-not $Force) { Fail "Not safe to restart: the entry pause was not confirmed by the engine (R4). Wait, or run again with -Force (an override, journaled)." 2 }
    Warn "-Force: restarting without a confirmed entry pause (override)"
  }
  try { $script:stateBefore = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/state" -TimeoutSec 6 } catch { $script:stateBefore = $null }
  # an older engine answers the SPA shell (or nothing): no state, no restoration check
  if (-not ($script:stateBefore -is [System.Management.Automation.PSCustomObject]) -or -not ($script:stateBefore.PSObject.Properties.Name -contains "armed")) { $script:stateBefore = $null }
  try {
    $rc = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/restart-check?caller=start.ps1" -TimeoutSec 6
    if (-not ($rc -is [System.Management.Automation.PSCustomObject]) -or -not ($rc.PSObject.Properties.Name -contains "safe")) {
      throw "no readiness answer (older engine or a non-JSON reply)"
    }
    if (-not $rc.safe) {
      foreach ($r in $rc.reasons) { Warn "in flight: $r" }
      if (-not $Force) { try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/quiesce?release=true" -Method Post -TimeoutSec 6 } catch { }; Fail "Not safe to restart now. Wait, or run again with -Force (logged as an override)." 2 }
      Warn "-Force: restarting over the work listed above"
    }
  } catch {
    Warn ("readiness unavailable (" + $_.Exception.Message + ") - missing evidence is not a safe inventory")
    if (-not $Force) { try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/quiesce?release=true" -Method Post -TimeoutSec 6 } catch { }; Fail "Not safe to restart: the engine could not report what is in flight. Wait, or run again with -Force (an override, journaled)." 2 }
    Warn "-Force: restarting without a readiness answer (override)"
  }
} catch {
  # nothing answering on :8420 - nothing to protect
}

# --- 1b. the server runs UNELEVATED (user decision 2026-09-05; PLATFORM-RULES 2026-09-10 / 09-15) -----------
# An engine launched from an elevated shell cannot be stopped by the Limited door tasks (ZargarRestart, the
# watchdog) - "Access is denied" - and every desk's restart is blocked until the user stops it by hand. Refuse
# here, before anything is stopped: assistants and desks use the ZargarRestart task; a person who really wants an
# elevated engine says so with -AllowElevated.
$isElevated = $false
try { $isElevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) } catch { }
if ($isElevated -and -not $AllowElevated) {
  Fail "This shell is ELEVATED: an engine started here could not be stopped by the ZargarRestart task or the watchdog (every desk's door would close). Run the ZargarRestart scheduled task (Start-ScheduledTask -TaskName ZargarRestart) or use a non-elevated terminal; -AllowElevated overrides deliberately." 8
}
# --- 2. stop the old server --------------------------------------------------
# The server may have been started in another terminal or detached; find it by
# the port it holds. Refuse to touch a process that is not python (typo'd
# config, another app squatting on 8420).
$procIds = @(Get-NetTCPConnection -LocalPort 8420 -State Listen -ErrorAction SilentlyContinue |
             Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($procId in $procIds) {
  $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
  if (-not $proc) { continue }
  if ($proc.ProcessName -notmatch "python") {
    Fail "Port 8420 is held by '$($proc.ProcessName)' (pid $procId), not Zargar - not touching it." 3
  }
  Step "Stopping old server (pid $procId)"
  try { Stop-Process -Id $procId -Force -Confirm:$false -ErrorAction Stop }
  catch {
    # 2026-09-15: an engine started from an ELEVATED shell cannot be stopped by the Limited door ("Access is denied").
    # Recovery is the user's: scripts\stop.ps1 from the elevated terminal that owns it, then the ZargarRestart task.
    Fail ("Cannot stop the running server (pid $procId): " + $_.Exception.Message +
          " - it runs with higher privileges than this door (started from an elevated shell). Stop it with scripts\stop.ps1 from an ELEVATED terminal, then run the ZargarRestart task; never start a second engine beside it.") 3
  }
}
if ($procIds.Count -gt 0) {
  foreach ($i in 1..20) {
    if (-not (Get-NetTCPConnection -LocalPort 8420 -State Listen -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 500
  }
}
# also stop any prior Discord intake so it re-launches fresh against the new server
Stop-DiscordIntake
Stop-EmIngest

# --- 3. postgres -------------------------------------------------------------
docker info *> $null
if ($LASTEXITCODE -eq 0) {
  docker compose up -d
  foreach ($i in 1..30) {
    docker compose exec -T db pg_isready -U zargar *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 1
  }
} else {
  Warn "Docker is not running - assuming Postgres is available some other way"
}

# --- 4. frontend -------------------------------------------------------------
# Rebuild only when an input is newer than the last build. Inputs = src/,
# public/, index.html and the build config - not just src/.
if (-not $NoBuild) {
  $marker = Join-Path $Root "frontend\dist\index.html"
  $needBuild = -not (Test-Path $marker)
  if (-not $needBuild) {
    $built = (Get-Item $marker).LastWriteTime
    $inputs = @()
    foreach ($dir in @("frontend\src", "frontend\public")) {
      $p = Join-Path $Root $dir
      if (Test-Path $p) { $inputs += Get-ChildItem $p -Recurse -File }
    }
    foreach ($f in @("frontend\index.html", "frontend\package.json", "frontend\vite.config.ts")) {
      $p = Join-Path $Root $f
      if (Test-Path $p) { $inputs += Get-Item $p }
    }
    $newest = $inputs | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newest -and $newest.LastWriteTime -gt $built) { $needBuild = $true }
  }
  if ($needBuild) {
    Step "Rebuilding frontend"
    Push-Location (Join-Path $Root "frontend")
    npm run build
    $buildExit = $LASTEXITCODE
    Pop-Location
    if ($buildExit -ne 0) { Fail "frontend build failed" 1 }
  }
}

# --- 5. run ------------------------------------------------------------------
$py = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Fail "backend\.venv not found - create the venv first" 1 }

# KFIN-04: ONE runtime identity for every door (task -> restart.ps1, a shell, the watchdog): what is
# about to run - HEAD, clean-source verdict, the manifest of the complete built artifact, the deploy
# script hashes and who asked - written BEFORE the launch to logs\runtime-identity.json. restart.ps1
# copies it into the deployment receipt; a reviewed handoff must match it exactly.
$identityCaller = $env:ZARGAR_DEPLOY_CALLER
if (-not $identityCaller) { $identityCaller = "start.ps1" }
try {
  $identity = Write-ZargarRuntimeIdentity $Root $identityCaller
  if (-not $identity.clean) { Warn ("launching UNREVIEWED source (" + $identity.problems.Count + " item(s), first: " + ($identity.problems | Select-Object -First 1) + ")") }
  Step ("Runtime identity: " + $(if ($identity.head) { $identity.head.Substring(0, 12) } else { "no-git" }) + " artifact " + $(if ($identity.artifactManifestSha256) { $identity.artifactManifestSha256.Substring(0, 12) + " (" + $identity.artifactFileCount + " files)" } else { "none" }) + " via " + $identityCaller)
} catch { Warn ("runtime identity not recorded: " + $_.Exception.Message) }

if ($Detach) {
  Step "Starting Zargar in the background"
  Start-Process -FilePath $py -ArgumentList "-m", "zargar.main" `
    -WorkingDirectory (Join-Path $Root "backend") -WindowStyle Hidden
  $up = $false
  # 180 s, not 30: this runtime restores 50+ armed plans and answers ~2 minutes after launch (the 09-14 and 09-15 doors
  # reported 'did not answer within 30s' for restarts that had in fact succeeded); restart.ps1 waits 180 s too
  foreach ($i in 1..180) {
    Start-Sleep -Seconds 1
    try {
      $h = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 2
      $up = $true; break
    } catch { }
  }
  if (-not $up) { Fail "server did not answer on :8420 within 180s - check backend\zargar-8420.log" 1 }
  # armed plans restore asynchronously after the API answers - wait for the
  # count to catch up with what was armed before the restart (or go stable)
  $restored = [int]$h.local.armed
  $stable = 0
  foreach ($i in 1..20) {
    if ($restored -ge $armedBefore -or $stable -ge 3) { break }
    Start-Sleep -Seconds 1
    try {
      $now = [int](Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 2).local.armed
      if ($now -eq $restored) { $stable++ } else { $stable = 0 }
      $restored = $now
    } catch { }
  }
  Step "Zargar is up -> http://127.0.0.1:8420 (armed plans restored: $restored)"
  # restoration check: what was armed / open / working before must be back (ids, not counts)
  if ($script:stateBefore -ne $null) {
    $ok = $false; $last = $null
    # P-G (2026-09-23): a large restore (EM arms ~200 plans a night) outlasts a fixed 60 s window. Pass as soon as the
    # check is OK; call it a MISMATCH only once the missing set has stopped shrinking for 60 s (12 polls), max 5 min.
    $sig = $null; $still = 0
    foreach ($i in 1..60) {
      try {
        $cmp = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/ops/restore-check" -Method Post -ContentType "application/json" -Body ($script:stateBefore | ConvertTo-Json -Depth 6 -Compress) -TimeoutSec 8
        $last = $cmp
        if ($cmp.ok) { $ok = $true; break }
        $now = ($cmp.missing | ConvertTo-Json -Depth 6 -Compress)
        if ($now -eq $sig) { $still++ } else { $still = 0; $sig = $now }
        if ($still -ge 12) { break }
      } catch { }
      Start-Sleep -Seconds 5
    }
    if ($ok) {
      Step ("Restore check OK: " + (($last.counts.PSObject.Properties | ForEach-Object { $_.Name + " " + $_.Value }) -join ", "))
    } else {
      $logDir = Join-Path $Root "logs"
      if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
      $snap = Join-Path $logDir ("restore-mismatch-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".json")
      @{ before = $script:stateBefore; after = $last } | ConvertTo-Json -Depth 8 | Set-Content -Path $snap
      Warn ("RESTORE MISMATCH: " + $(if ($last) { ($last.missing | ConvertTo-Json -Compress) } else { "restore-check unreachable" }) + " - saved " + $snap)
    }
  }
  Write-Host "  Watch the log anytime: scripts\logs.ps1 (Ctrl+C detaches, server unaffected)" -ForegroundColor DarkGray
  if (-not $NoDiscord) { Start-DiscordIntake }
  if (-not $NoIngest) { Start-EmIngest }
} else {
  # launch the intake window first (it waits for the API), then run the app in
  # the foreground - the intake keeps its own window regardless of Ctrl+C here
  if (-not $NoDiscord) { Start-DiscordIntake }
  if (-not $NoIngest) { Start-EmIngest }
  Step "Zargar -> http://127.0.0.1:8420 (Ctrl+C stops it)"
  Set-Location (Join-Path $Root "backend")
  # Foreground ownership passes to the process; retain the watchdog startup grace period.
  Set-Content -LiteralPath (Join-Path $Root 'logs/watchdog.lock') -Value (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
  Exit-ZargarDeployment $startLease
  & $py -m zargar.main
}

} finally { Exit-ZargarDeployment $startLease }
