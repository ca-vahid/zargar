# Verify both EM books AFTER the evening batch finishes arming, without needing anyone to be watching.
#
# 2026-09-21: the baseline's evening preparation ran detached under the scheduler, so it could finish long after
# the session that started it had ended. "Verify the books after arming" then has nobody to do it. This waits for
# the batch process to exit, runs the reconciliation and the two-book verification once, writes both into the
# research folder, and raises the keyed `armed` notice if a book is still empty.
#
# READ-ONLY with respect to trading: it runs read-only tools, arms nothing and changes no setting.
param(
  [string]$Date = '',
  [int]$MaxWaitMinutes = 180,
  [string]$BatchMatch = 'em-evening-batch'
)
$ErrorActionPreference = 'Continue'
$work = 'C:\Cursor\zargar\.claude\worktrees\technique-review-trade-plan-fbb9ba'
$py = 'C:\Cursor\zargar\backend\.venv\Scripts\python.exe'
$outDir = Join-Path $work 'docs\techniques\enhanced-market\research\experiment'
$logDir = 'C:\ProgramData\Zargar\logs'
$attention = 'C:\ProgramData\Zargar\EM-ATTENTION.md'
if (-not $Date) {                                          # the batch prepares the NEXT session: Friday's prepares Monday
  $d = (Get-Date).AddDays(1)
  while ($d.DayOfWeek -in 'Saturday', 'Sunday') { $d = $d.AddDays(1) }
  $Date = $d.ToString('yyyy-MM-dd')
}
$log = Join-Path $logDir ("em-after-arming-$Date.log")
function Say($m) {
  $line = "$((Get-Date).ToString('HH:mm:ss')) [after-arming] $m"
  Write-Host $line
  $line | Out-File -FilePath $log -Append -Encoding utf8
}

$envFile = 'C:\Cursor\zargar\backend\.env'
$dbLine = (Get-Content -LiteralPath $envFile | Where-Object { $_ -like 'ZARGAR_DATABASE_URL=*' } | Select-Object -First 1)
if (-not $dbLine) { Say 'no ZARGAR_DATABASE_URL in .env - abort'; exit 2 }
$env:ZARGAR_DATABASE_URL = ($dbLine -replace '^ZARGAR_DATABASE_URL=', '').Trim().Trim('"')
$env:PYTHONPATH = Join-Path $work 'backend'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location (Join-Path $work 'backend')

# ---- wait for the batch to finish. One instance of a venv python is a PROCESS PAIR (a launcher plus the real
# interpreter), so presence is "count greater than zero", never "count equals one".
Say "waiting for the batch to exit (up to $MaxWaitMinutes minutes)"
$deadline = (Get-Date).AddMinutes($MaxWaitMinutes)
while ((Get-Date) -lt $deadline) {
  $n = (Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like "*$BatchMatch*" } | Measure-Object).Count
  if ($n -eq 0) { Say 'batch is no longer running'; break }
  Start-Sleep -Seconds 60
}
if ((Get-Date) -ge $deadline) { Say "gave up waiting after $MaxWaitMinutes minutes - checking anyway" }

# ---- reconcile what the batch actually did: symbols, runs, billable requests, arms per book
$rec = Join-Path $outDir ("$Date-prep-reconcile.md")
Say "reconciliation -> $rec"
$rtext = & $py -m zargar.tools.em_prep_reconcile --date $Date 2>&1
$rtext | Out-File -FilePath $rec -Encoding utf8
($rtext | Select-String -Pattern 'Unique symbols|Runs of every kind|REVIEWED more than once|unresolved|Estimated cost') | ForEach-Object { Say $_.ToString() }

# ---- verify both books
$ver = Join-Path $outDir ("$Date-after-arming.md")
Say "two-book verification -> $ver"
$vtext = & $py -m zargar.tools.em_experiment_check --date $Date 2>&1
$vtext | Out-File -FilePath $ver -Encoding utf8

$armedLine = ($vtext | Select-String -Pattern '^\| Armed for the session \|')
if ($armedLine) {
  $cells = $armedLine.ToString().Split('|')
  $baseArmed = ($cells[2].Trim() -split ' ')[0]
  $expArmed = ($cells[3].Trim() -split ' ')[0]
  Say "armed after the batch: baseline $baseArmed, experiment $expArmed"
  # 2026-09-24: the baseline is prepared deterministically inside the engine, so an empty baseline is always a failure;
  # EM Experimental is retired (paused, experiment disabled) and is not required to be armed
  if ($baseArmed -eq '0') {
    $body = @("baseline armed: $baseArmed ; experiment armed: $expArmed", "",
              "EM Practice is empty after the evening. It is prepared deterministically inside the engine once the",
              "16:15 ET sheet exists; check the newest TechniquePrepared event (GET /api/events?type=TechniquePrepared)",
              "and re-run it if needed (idempotent, zero model calls): POST /api/technique/em/prepare. Never arm by hand.") -join "`r`n"
    @("# EM needs attention - EM Practice has NOTHING armed for $Date", "", "Key: armed",
      "Raised $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) by the after-arming check for session $Date.",
      "Owner: EM desk (attending); backup: the Zargar operator", "", $body) -join "`r`n" |
      Out-File -FilePath $attention -Encoding utf8
    Say 'ATTENTION RAISED [armed]: a book is still empty after the batch stopped'
  } else {
    # only the owner of this key may clear it, and an unkeyed notice is left alone
    if (Test-Path $attention) {
      $held = (Get-Content -LiteralPath $attention | Where-Object { $_ -like 'Key: *' } | Select-Object -First 1)
      $heldKey = if ($held) { ($held -replace '^Key: ', '').Trim() } else { '' }
      if ($heldKey -eq 'armed') { Remove-Item $attention -Force; Say 'attention cleared [armed]: EM Practice armed' }
      else { Say "attention kept: held by [$heldKey], not [armed]" }
    }
  }
}
Say 'done'
