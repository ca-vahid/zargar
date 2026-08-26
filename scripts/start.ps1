# Start Zargar (Windows PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1
# Brings up Postgres (Docker Desktop), rebuilds the UI if sources changed,
# then runs engine + API + UI as one process on http://127.0.0.1:8420
param([switch]$Force)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$Root = (Get-Location).Path

# Never restart over live work: analyst reads in flight (each one costs money and
# dies with the process) or armed plans holding a position. 2026-08-26: five
# restarts in one evening killed ~200 model reads. Pass -Force to override.
try {
  $st = Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/technique/status" -TimeoutSec 4
  $running = @($st.running).Count
  $armed = @($st.armed).Count
  if (-not $Force -and $running -gt 0) {
    Write-Host "! $running technique run(s) are in flight - a restart would kill them (they cost money)." -ForegroundColor Red
    Write-Host "  Wait for the batch to finish, or run again with -Force." -ForegroundColor Yellow
    exit 2
  }
  if ($running -gt 0) { Write-Host "! -Force: restarting over $running in-flight run(s)" -ForegroundColor Yellow }
  if ($armed -gt 0) { Write-Host "! $armed armed plan(s) will be restored after the restart" -ForegroundColor Yellow }
} catch {
  # no app on :8420 - nothing to protect
}

docker info *> $null
if ($LASTEXITCODE -eq 0) {
  docker compose up -d
  foreach ($i in 1..30) {
    docker compose exec -T db pg_isready -U zargar *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 1
  }
} else {
  Write-Host "! Docker is not running - assuming Postgres is available some other way" -ForegroundColor Yellow
}

# rebuild the UI only when sources are newer than the last build
$dist = "$Root\frontend\dist"
$needBuild = -not (Test-Path $dist)
if (-not $needBuild) {
  $distTime = (Get-Item $dist).LastWriteTime
  $newest = Get-ChildItem "$Root\frontend\src" -Recurse -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($newest -and $newest.LastWriteTime -gt $distTime) { $needBuild = $true }
}
if ($needBuild) {
  Write-Host "> Rebuilding frontend" -ForegroundColor Cyan
  Set-Location "$Root\frontend"
  npm run build
  if ($LASTEXITCODE -ne 0) { exit 1 }
}

Write-Host "> Zargar -> http://127.0.0.1:8420" -ForegroundColor Cyan
Set-Location "$Root\backend"
& ".venv\Scripts\python.exe" -m zargar.main
