# Start (or restart) Zargar on http://127.0.0.1:8420
#
#   scripts\start.ps1            run in this terminal (Ctrl+C stops it)
#   scripts\start.ps1 -Detach    run hidden in the background and return
#   scripts\start.ps1 -Force     restart even if analyst runs are in flight
#   scripts\start.ps1 -NoBuild   skip the frontend rebuild check
#   scripts\start.ps1 -NoDiscord skip the experimental Discord intake window
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
# Exit codes: 0 ok / 1 build or launch failure / 2 refused (runs in flight)
#             3 port 8420 held by something that is not Zargar

param(
  [switch]$Force,
  [switch]$Detach,
  [switch]$NoBuild,
  [switch]$NoDiscord
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Step($msg) { Write-Host "> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "! $msg" -ForegroundColor Yellow }
function Fail($msg, $code) { Write-Host "x $msg" -ForegroundColor Red; exit $code }

# Stop any running Discord intake (gateway python + its host window) so a
# restart never stacks windows. Matches by command line, own processes only.
function Stop-DiscordIntake {
  try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -and ($_.CommandLine -match "discord_gateway|discord-intake\.ps1") } |
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
} catch {
  # nothing answering on :8420 - nothing to protect
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
  Stop-Process -Id $procId -Force -Confirm:$false
}
if ($procIds.Count -gt 0) {
  foreach ($i in 1..20) {
    if (-not (Get-NetTCPConnection -LocalPort 8420 -State Listen -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 500
  }
}
# also stop any prior Discord intake so it re-launches fresh against the new server
Stop-DiscordIntake

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

if ($Detach) {
  Step "Starting Zargar in the background"
  Start-Process -FilePath $py -ArgumentList "-m", "zargar.main" `
    -WorkingDirectory (Join-Path $Root "backend") -WindowStyle Hidden
  $up = $false
  foreach ($i in 1..30) {
    Start-Sleep -Seconds 1
    try {
      $h = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 2
      $up = $true; break
    } catch { }
  }
  if (-not $up) { Fail "server did not answer on :8420 within 30s - check backend\zargar-8420.log" 1 }
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
  Write-Host "  Watch the log anytime: scripts\logs.ps1 (Ctrl+C detaches, server unaffected)" -ForegroundColor DarkGray
  if (-not $NoDiscord) { Start-DiscordIntake }
} else {
  # launch the intake window first (it waits for the API), then run the app in
  # the foreground - the intake keeps its own window regardless of Ctrl+C here
  if (-not $NoDiscord) { Start-DiscordIntake }
  Step "Zargar -> http://127.0.0.1:8420 (Ctrl+C stops it)"
  Set-Location (Join-Path $Root "backend")
  & $py -m zargar.main
}
