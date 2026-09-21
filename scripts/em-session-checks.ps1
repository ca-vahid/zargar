# EM two-book session checks (em-experiment-v1). READ-ONLY: runs the read-only EM tools, writes markdown/JSON into the
# EM research folder, and raises a persistent attention file when something needs a person. It changes no setting, arms
# nothing, places no order and never pauses a book.
#
# 2026-09-21: this file is now VERSIONED IN THE REPOSITORY and installed to C:\ProgramData\Zargar by
# scripts\em-install-session-checks.ps1. Before that it existed only under ProgramData, written by a chat session - so
# nobody could review it, diff it or restore it. Two faults from that session are fixed here:
#   * the tasks were registered for ONE DATE, so tomorrow's session had no coverage at all;
#   * a check could find a fault and write it to a file that nobody would ever open.
#
#   .\em-session-checks.ps1 -Phase clock|preopen|postreplan|exceptions|close [-Date 2026-09-21]
param(
  [Parameter(Mandatory = $true)][ValidateSet('clock', 'preopen', 'postreplan', 'exceptions', 'close')][string]$Phase,
  [string]$Date = ''
)
$ErrorActionPreference = 'Continue'
$work = 'C:\Cursor\zargar\.claude\worktrees\technique-review-trade-plan-fbb9ba'
$py = 'C:\Cursor\zargar\backend\.venv\Scripts\python.exe'
$outDir = Join-Path $work 'docs\techniques\enhanced-market\research\experiment'
$logDir = 'C:\ProgramData\Zargar\logs'
$attention = 'C:\ProgramData\Zargar\EM-ATTENTION.md'
foreach ($d in @($outDir, $logDir)) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null } }
if (-not $Date) { $Date = (Get-Date).ToString('yyyy-MM-dd') }
$log = Join-Path $logDir ("em-checks-$Date.log")
function Say($m) { "$((Get-Date).ToString('HH:mm:ss')) [$Phase] $m" | Tee-Object -FilePath $log -Append }

# The attending owner is named here because there is NO push destination configured on this host: no Telegram bot and
# no web-push subscription. A check that finds a fault therefore has nowhere to page, and the honest substitute is a
# file that stays until someone clears it, plus a named person who looks.
$owner = 'EM desk (attending); backup: the Zargar operator, who runs scripts\em-session-checks.ps1 -Phase clock before the open'
function Raise-Attention($title, $body) {
  $text = @("# EM needs attention - $title", "", "Raised $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) by the $Phase check for session $Date.",
            "Owner: $owner", "", $body, "",
            "This file stays until a later check finds the condition cleared. It is a NOTICE, not a trading action:",
            "no setting was changed, no book was paused and no gate was loosened.") -join "`r`n"
  $text | Out-File -FilePath $attention -Encoding utf8
  Say "ATTENTION RAISED: $title"
}
function Clear-Attention($why) {
  if (Test-Path $attention) { Remove-Item $attention -Force; Say "attention cleared: $why" }
}

# the database URL comes from the runtime .env and is never printed
$envFile = 'C:\Cursor\zargar\backend\.env'
# Windows PowerShell 5.1 runs scheduled tasks: no Select-String -Raw here
$dbLine = (Get-Content -LiteralPath $envFile | Where-Object { $_ -like 'ZARGAR_DATABASE_URL=*' } | Select-Object -First 1)
if (-not $dbLine) { Say 'no ZARGAR_DATABASE_URL in .env - abort'; exit 2 }
$env:ZARGAR_DATABASE_URL = ($dbLine -replace '^ZARGAR_DATABASE_URL=', '').Trim().Trim('"')
$env:PYTHONPATH = Join-Path $work 'backend'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location (Join-Path $work 'backend')

Say "start (worktree $work)"
try {
  $health = Invoke-RestMethod 'http://127.0.0.1:8420/api/health' -TimeoutSec 10
  Say ("health: ok=$($health.ok) version=$($health.version) build=$($health.build) armed=$($health.local.armed)")
} catch { Say "health unreachable: $($_.Exception.Message)" }

# ---- clock: the check that was missing on 2026-09-21 -------------------------------------------------------------
# Every experimental entry that day was refused because the host clock was ~10 s behind and correct venue timestamps
# looked future-dated. This runs BEFORE the open so the fault is known while there is still time to fix it.
function Invoke-ClockCheck([string]$file) {
  $text = & $py -m zargar.tools.clock_health 2>&1
  $code = $LASTEXITCODE
  if ($file) { $text | Out-File -FilePath $file -Encoding utf8 }
  $text | ForEach-Object { Say $_.ToString() }
  if ($code -ne 0) {
    Raise-Attention 'host clock is wrong - entries will be refused' (($text | Out-String) + "`r`n" +
      "What to do: restore Windows time synchronization (an administrator runs, in an elevated shell):`r`n" +
      "    Set-Service w32time -StartupType Automatic; Start-Service w32time; w32tm /resync /force`r`n" +
      "Do NOT widen the admission tolerance instead. The gate is refusing evidence that genuinely looks future-dated;`r`n" +
      "loosening it would admit real stale quotes for the sake of a clock fault.")
  }
  return $code
}

if ($Phase -eq 'clock') {
  $file = Join-Path $outDir ("$Date-clock.md")
  Say "raw time validity -> $file"
  $code = Invoke-ClockCheck $file
  if ($code -eq 0) { Clear-Attention 'clock healthy' }
  exit 0
} elseif ($Phase -eq 'exceptions') {
  # operational exceptions so far this session: halts, pauses, arm refusals, restarts, order-rate rejections,
  # recorder drops, and entries the admission gate could not decide
  $stamp = (Get-Date).ToString('HHmm')
  $file = Join-Path $outDir ("$Date-exceptions-$stamp.md")
  Say "operational exceptions -> $file"
  $text = & $py -m zargar.tools.em_experiment_check --date $Date --exceptions 2>&1
  $text | Out-File -FilePath $file -Encoding utf8
  ($text | Select-String -Pattern 'Anything to report|order-rate|Recorder:|admission gate could not decide|^- ') | ForEach-Object { Say $_.ToString() }
  $deferrals = ($text | Select-String -Pattern 'Entries the admission gate could not decide: (\d+)')
  $n = 0
  if ($deferrals) { $n = [int]$deferrals.Matches[0].Groups[1].Value }
  if ($n -ge 3) {
    Raise-Attention "$n entries could not be decided by the admission gate" (($text | Out-String))
  }
} elseif ($Phase -eq 'close') {
  Say 'daily comparison report (it embeds the session exception log)'
  & $py -m zargar.tools.em_experiment_report report --date $Date 2>&1 | Tee-Object -FilePath $log -Append
  # the exception log is ALSO written as its own file, so the report and the log are always delivered together
  $exc = Join-Path $outDir ("$Date-exceptions-close.md")
  Say "exception log -> $exc"
  (& $py -m zargar.tools.em_experiment_check --date $Date --exceptions 2>&1) | Out-File -FilePath $exc -Encoding utf8
} else {
  $name = if ($Phase -eq 'preopen') { "$Date-preopen.md" } else { "$Date-postreplan.md" }
  $file = Join-Path $outDir $name
  if ($Phase -eq 'preopen') { Say 'clock first: a wrong host clock refuses every entry, so it is checked before anything else'; Invoke-ClockCheck (Join-Path $outDir "$Date-clock.md") | Out-Null }
  Say "two-book verification -> $file"
  $text = & $py -m zargar.tools.em_experiment_check --date $Date 2>&1
  $text | Out-File -FilePath $file -Encoding utf8
  $text | Tee-Object -FilePath $log -Append | Out-Null
  # the same check as JSON, so a later reader has the raw numbers
  (& $py -m zargar.tools.em_experiment_check --date $Date --json 2>&1) | Out-File -FilePath ($file -replace '\.md$', '.json') -Encoding utf8
}
Say 'done'
