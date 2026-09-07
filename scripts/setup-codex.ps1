# Installs only this checkout's dependencies and provisions only its test DB.
# -StartTestPostgres opts into a separate container if port 5433 is unused.
param([switch]$StartTestPostgres)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $root
try {
    $envFile = Join-Path $root 'backend\.env'
    if (-not (Test-Path $envFile)) {
        $dist = (Join-Path $root 'frontend/dist') -replace '\\', '/'
        @(
            '# Codex-only; runtime database is intentionally not provisioned by test setup.'
            'ZARGAR_DATABASE_URL=postgresql+asyncpg://zargar:zargar@127.0.0.1:5433/zargar_dev_codex'
            'ZARGAR_BROKER=sim'
            'ZARGAR_QUOTE_SOURCE=sim'
            'ZARGAR_HOST=127.0.0.1'
            'ZARGAR_PORT=8421'
            'ZARGAR_CORS_ORIGINS=http://127.0.0.1:5174,http://localhost:5174'
            "ZARGAR_FRONTEND_DIST=$dist"
        ) | Set-Content -LiteralPath $envFile -Encoding utf8
    }
    $python = Join-Path $root 'backend\.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        python -m venv backend/.venv
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    }
    & $python -m pip install -e './backend[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }

    if ($StartTestPostgres) {
        $client = New-Object System.Net.Sockets.TcpClient
        try { $client.Connect('127.0.0.1', 5433); $occupied = $true }
        catch { $occupied = $false }
        finally { $client.Dispose() }
        if ($occupied) {
            Write-Host 'Port 5433 is occupied; using the existing test server without changing its container.'
        } else {
            docker compose -f docker-compose.codex-test.yml up -d --wait
            if ($LASTEXITCODE -ne 0) { throw 'Codex test PostgreSQL startup failed.' }
        }
    }
    & $python scripts/codex-test-db.py
    if ($LASTEXITCODE -ne 0) { throw 'Codex test database creation/verification failed.' }

    Push-Location frontend
    try {
        npm ci --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
    Write-Host 'Dependencies, frontend build, and zargar_test_codex verified. No trading runtime started.'
} finally { Pop-Location }
