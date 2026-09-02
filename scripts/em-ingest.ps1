# Zargar EM ingestion worker - transcribes the author's pre-trading videos for the
# EnhancedMarket method pipeline (docs\techniques\enhanced-market\INGESTION-PLAN.md).
# Runs in its own window; launched by scripts\start.ps1 (unless -NoIngest) or by hand:
#
#   scripts\em-ingest.ps1            poll the app for pending videos, transcribe, report
#   scripts\em-ingest.ps1 -Once      drain what's pending and exit
#
# Media deps (yt-dlp, faster-whisper) live in backend\.venv-ingest - created here on
# first run so the app's own venv never carries them. ffmpeg must be on PATH.
# EM-only: this worker talks to /api/technique/ingest/* and nothing else.

param(
  [switch]$Once,
  [switch]$NoWait,
  [string]$Api = "http://127.0.0.1:8420",
  [string]$Model = "small"
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Backend = Join-Path $Root "backend"
$appPy = Join-Path $Backend ".venv\Scripts\python.exe"
$venv = Join-Path $Backend ".venv-ingest"
$py = Join-Path $venv "Scripts\python.exe"
$Host.UI.RawUI.WindowTitle = "Zargar - EM ingestion"

function Step($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "! $m" -ForegroundColor Yellow }

if (-not (Test-Path $appPy)) { Warn "backend\.venv not found"; Read-Host "Enter to close"; exit 1 }
Set-Location $Backend

# --- media venv (one-time) ------------------------------------------------------
if (-not (Test-Path $py)) {
  Step "Creating backend\.venv-ingest (yt-dlp + faster-whisper; one-time, ~1 min)"
  & $appPy -m venv $venv
  & $py -m pip -q install --upgrade pip
  & $py -m pip -q install yt-dlp faster-whisper httpx
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Warn "ffmpeg not on PATH - transcription will fail. Install: winget install Gyan.FFmpeg"
}

# --- wait for the API -------------------------------------------------------------
if (-not $NoWait) {
  Step "Waiting for Zargar API on $Api ..."
  foreach ($i in 1..40) {
    try { Invoke-RestMethod -Uri "$Api/api/health" -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Seconds 1 }
  }
}

# --- session (auth) ------------------------------------------------------------------
try {
  $tok = & $appPy -m zargar.tools.mint_session --hours 720 2>$null
  if ($tok -and $tok.Trim() -match '^[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.') { $env:ZARGAR_SESSION = $tok.Trim(); Step "Session minted." }
  else { Warn "Could not mint a session (auth may be off). Proceeding without one." }
} catch { Warn "mint_session failed: $($_.Exception.Message)" }

# --- run --------------------------------------------------------------------------------
# the worker imports the app package (for nothing but its own module) from the app venv's
# source tree; PYTHONPATH keeps it importable from the media venv
$env:PYTHONPATH = $Backend
$env:PYTHONUTF8 = "1"
$args = @("-m", "zargar.tools.em_ingest", "--api", $Api, "--model", $Model)
if ($Once) { $args += "--once" }
Step ("Starting worker: python " + ($args -join " "))
& $py @args
Warn "Worker exited (code $LASTEXITCODE)."
if (-not $Once) { Read-Host "Press Enter to close this window" }
