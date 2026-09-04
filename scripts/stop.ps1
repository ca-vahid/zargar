# Stop Zargar (the server on :8420 plus its helper windows) — the counterpart of start.ps1.
#
#   scripts\stop.ps1             stop the server, the Discord intake and the EM ingestion worker
#   scripts\stop.ps1 -Force      stop even if analyst runs are in flight (they cost money)
#   scripts\stop.ps1 -KeepHelpers  stop only the server; leave the intake / ingest windows alone
#
# Why a separate script: the server is usually started from an ELEVATED terminal, and a
# non-elevated shell (an agent session, a scheduled task) cannot stop it. Run this from the
# terminal that owns the process; afterwards anyone can `scripts\start.ps1 -Detach` and the
# new process belongs to them. Armed plans are write-ahead and restore on the next start.
#
# Exit codes: 0 stopped (or nothing was running) / 2 refused (runs in flight)
#             3 port 8420 held by something that is not Zargar

param(
  [switch]$Force,
  [switch]$KeepHelpers
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Step($msg) { Write-Host "> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "! $msg" -ForegroundColor Yellow }
function Fail($msg, $code) { Write-Host "x $msg" -ForegroundColor Red; exit $code }

# --- 1. safety check (same rule as start.ps1) --------------------------------
try {
  $h = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/health" -TimeoutSec 4
  $running = [int]$h.local.techniqueRunning
  $armed   = [int]$h.local.armed
  if ($running -gt 0 -and -not $Force) {
    Warn "$running analyst run(s) in flight - stopping would kill them (they cost money)."
    Fail "Wait for the batch to finish, or run again with -Force." 2
  }
  if ($running -gt 0) { Warn "-Force: stopping over $running in-flight run(s)" }
  if ($armed -gt 0)   { Warn "$armed armed plan(s) are write-ahead and will restore on the next start" }
} catch {
  # nothing answering on :8420 - nothing to protect
}

# --- 2. the server -----------------------------------------------------------
$procIds = @(Get-NetTCPConnection -LocalPort 8420 -State Listen -ErrorAction SilentlyContinue |
             Select-Object -ExpandProperty OwningProcess -Unique)
if ($procIds.Count -eq 0) {
  Step "Nothing is listening on :8420"
} else {
  foreach ($procId in $procIds) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc) { continue }
    if ($proc.ProcessName -notmatch "python") {
      Fail "Port 8420 is held by '$($proc.ProcessName)' (pid $procId), not Zargar - not touching it." 3
    }
    Step "Stopping Zargar (pid $procId)"
    Stop-Process -Id $procId -Force -Confirm:$false
  }
  foreach ($i in 1..20) {
    if (-not (Get-NetTCPConnection -LocalPort 8420 -State Listen -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 500
  }
  if (Get-NetTCPConnection -LocalPort 8420 -State Listen -ErrorAction SilentlyContinue) {
    Fail "port 8420 is still held after 10s" 1
  }
  Step "Server stopped"
}

# --- 3. helper windows -------------------------------------------------------
if (-not $KeepHelpers) {
  $stopped = 0
  try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -and ($_.CommandLine -match "discord_gateway|discord-intake\.ps1|em_ingest|em-ingest\.ps1") } |
      ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -Confirm:$false -ErrorAction SilentlyContinue
        $stopped++
      }
  } catch { }
  if ($stopped -gt 0) { Step "Stopped $stopped helper process(es) (Discord intake / EM ingestion)" }
}

Write-Host "  Start again with: scripts\start.ps1 -Detach   (any terminal; the new process is yours)" -ForegroundColor DarkGray
exit 0
