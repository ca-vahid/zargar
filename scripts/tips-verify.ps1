# Tips nightly verification (P10, 2026-09-24 sharp-pencil plan).
# Runs the Tips-owned test suites on their OWN database, only when the host has >= 2 GB free, and writes a
# status file + log. It never restarts anything and never touches the runtime database.
#
#   Register (once, from the Tips session):
#     $a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\Cursor\zargar\scripts\tips-verify.ps1'
#     $t = New-ScheduledTaskTrigger -Daily -At 22:40      # 22:40 PT = 01:40 ET, after EM's evening batch and any deploy
#     Register-ScheduledTask -TaskName ZargarTipsVerify -Action $a -Trigger $t -Description 'Tips nightly test verification (own DB, >= 2 GB free)'
#
# Output: C:\ProgramData\Zargar\tips-verify\STATUS.json  (PASSED | FAILED | SKIPPED_MEMORY | HARNESS_ERROR)
#         C:\ProgramData\Zargar\tips-verify\verify-<yyyyMMdd>.log
param([int]$MinFreeMB = 2048, [int]$WaitMinutes = 90)

$ErrorActionPreference = 'Continue'
$Root = 'C:\Cursor\zargar'
$Out = 'C:\ProgramData\Zargar\tips-verify'
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd'
$log = Join-Path $Out "verify-$stamp.log"
$statusPath = Join-Path $Out 'STATUS.json'

function Write-Status($status, $detail) {
  [pscustomobject]@{ status = $status; detail = $detail; at = (Get-Date).ToUniversalTime().ToString('o');
                     head = (git -C $Root rev-parse --short HEAD 2>$null); log = $log } |
    ConvertTo-Json | Set-Content -Path $statusPath -Encoding utf8
}

# wait (bounded) for memory
$deadline = (Get-Date).AddMinutes($WaitMinutes)
while ($true) {
  $free = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1KB)
  if ($free -ge $MinFreeMB) { break }
  if ((Get-Date) -gt $deadline) { Write-Status 'SKIPPED_MEMORY' "only $free MB free after $WaitMinutes min"; exit 0 }
  Start-Sleep -Seconds 60
}

$db = 'zargar_test_tipsverify'
docker exec zargar-db psql -U zargar -d zargar -tAc "select 1 from pg_database where datname='$db'" 2>$null | Out-String |
  ForEach-Object { if ($_.Trim() -ne '1') { docker exec zargar-db psql -U zargar -d zargar -c "create database $db" | Out-Null } }
$env:ZARGAR_TEST_DATABASE_URL = "postgresql+asyncpg://zargar:zargar@127.0.0.1:5433/$db"

$suites = @(
  'tests/test_signals_tip.py', 'tests/test_proposal_readiness.py', 'tests/test_proposal_fresh_retry.py',
  'tests/test_tip_geometry_rev2.py', 'tests/test_tip_analyst_loop.py', 'tests/test_tip_cost_levers.py',
  'tests/test_tip_plan_0842.py', 'tests/test_tip_plan_0849.py', 'tests/test_tip_lotto.py', 'tests/test_occ_loose.py',
  'tests/test_recovery.py', 'tests/test_knowledge_governance.py', 'tests/test_tip_retro_digest_accounting.py',
  'tests/test_position_chaos.py', 'tests/test_execution_exits.py'
)
Push-Location (Join-Path $Root 'backend')
try {
  & .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider @suites *> $log
  $code = $LASTEXITCODE
} catch {
  Write-Status 'HARNESS_ERROR' $_.Exception.Message; exit 1
} finally { Pop-Location }
$summary = (Get-Content $log -Tail 3 | Where-Object { $_ -match 'passed|failed|error' }) -join ' '
if (-not $summary) { Write-Status 'HARNESS_ERROR' 'no pytest summary line'; exit 1 }
Write-Status ($(if ($code -eq 0) { 'PASSED' } else { 'FAILED' })) $summary
exit 0
