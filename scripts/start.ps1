# Start Zargar (Windows PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1
# Brings up Postgres (Docker Desktop), rebuilds the UI if sources changed,
# then runs engine + API + UI as one process on http://127.0.0.1:8420
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$Root = (Get-Location).Path

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
