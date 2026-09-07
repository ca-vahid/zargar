# Run sequential tests in this worktree's disposable database only.
# Example: .\scripts\test-codex.ps1 tests/test_engine_flow.py -q
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Install backend dependencies first; see docs/COLLABORATION.md.' }
$saved = @{}
# Prevent inherited runtime credentials/config from leaking into test fixtures.
Get-ChildItem Env: | Where-Object Name -like 'ZARGAR_*' | ForEach-Object {
    $saved[$_.Name] = $_.Value
    Remove-Item -LiteralPath "Env:$($_.Name)"
}
$code = 1
Push-Location (Join-Path $root 'backend')
try {
    $env:ZARGAR_TEST_DATABASE_URL = 'postgresql+asyncpg://zargar:zargar@127.0.0.1:5433/zargar_test_codex'
    $env:ZARGAR_DATABASE_URL = $env:ZARGAR_TEST_DATABASE_URL
    $env:ZARGAR_BROKER = 'sim'
    $env:ZARGAR_QUOTE_SOURCE = 'sim'
    & $python -m pytest @args
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    Get-ChildItem Env: | Where-Object Name -like 'ZARGAR_*' | ForEach-Object { Remove-Item -LiteralPath "Env:$($_.Name)" }
    foreach ($name in $saved.Keys) { Set-Item -LiteralPath "Env:$name" -Value $saved[$name] }
}
exit $code
