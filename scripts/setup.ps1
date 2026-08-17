# Zargar one-time setup (Windows PowerShell).
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# Checks prerequisites, starts Postgres (Docker Desktop), installs backend +
# frontend, builds the UI, and writes backend\.env. Then: scripts\start.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$Root = (Get-Location).Path

function Say($msg)  { Write-Host "> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "X $msg" -ForegroundColor Red; exit 1 }

# -- prerequisites ----------------------------------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue))   { Fail "git not found - install from https://git-scm.com" }
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Fail "Python not found - install 3.11+ from https://python.org (check 'Add to PATH')" }
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if ($LASTEXITCODE -ne 0) { Fail "Python 3.11+ required (found $(python -V))" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "Node.js 20+ not found - install from https://nodejs.org" }
node -e "process.exit(parseInt(process.versions.node) >= 20 ? 0 : 1)"
if ($LASTEXITCODE -ne 0) { Fail "Node.js 20+ required (found $(node -v))" }

# -- database ------------------------------------------------------------------
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Fail "Docker is not running. Start Docker Desktop, wait for it to finish starting, then re-run this script."
}
Say "Starting Postgres via Docker Compose"
docker compose up -d
if ($LASTEXITCODE -ne 0) { Fail "docker compose up failed" }

# -- backend ---------------------------------------------------------------
Say "Installing backend (Python)"
Set-Location "$Root\backend"
if (-not (Test-Path ".venv")) { python -m venv .venv }
& ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& ".venv\Scripts\python.exe" -m pip install --quiet -e ".[dev]"
if ($LASTEXITCODE -ne 0) { Fail "backend install failed" }

if (-not (Test-Path ".env")) {
  Say "Writing backend\.env"
  Copy-Item "$Root\.env.example" ".env"
  $dist = "$Root\frontend\dist" -replace '\\', '/'
  (Get-Content ".env") -replace '^ZARGAR_FRONTEND_DIST=.*', "ZARGAR_FRONTEND_DIST=$dist" | Set-Content ".env"
} else {
  Say "backend\.env already exists - leaving it untouched"
}

# -- frontend ---------------------------------------------------------------
Say "Installing + building frontend"
Set-Location "$Root\frontend"
npm install --no-fund --no-audit
if ($LASTEXITCODE -ne 0) { Fail "npm install failed" }
npm run build
if ($LASTEXITCODE -ne 0) { Fail "frontend build failed" }

Set-Location $Root
Say "Setup complete. Start the app with:  powershell -ExecutionPolicy Bypass -File scripts\start.ps1"
