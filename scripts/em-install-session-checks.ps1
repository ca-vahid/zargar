# Install the EM session checks as RECURRING weekday scheduled tasks (2026-09-21).
#
# Why this exists: the 2026-09-19 checks were registered by hand for a single date. They ran correctly on
# 2026-09-21 and then stopped existing - the next session had no coverage at all, which is exactly the failure
# mode the checks were meant to prevent. These triggers are weekly Mon-Fri, so coverage does not depend on any
# person or chat session being alive on a given morning.
#
# Times are LOCAL (this host runs on Pacific time; the market is Eastern):
#   06:05 PT / 09:05 ET  clock        raw time validity BEFORE the open, while there is time to fix it
#   06:07 PT / 09:07 ET  preopen      both books, limits, routing (also re-checks the clock)
#   06:32 PT / 09:32 ET  postreplan   after the 09:25 ET re-plan and the open
#   07:22, 09:41, 11:52 PT           intraday operational exceptions
#   13:37 PT / 16:37 ET  close        the two-book comparison, the exception log and the SCORECARD (stop rule)
#   14:05 PT / 17:05 ET  evening      the baseline's paid review + arming (em-evening-batch.py; resumable, one at a time,
#                                     honours techniques.enhanced_market.paid_review) - the sheet is built at 16:15 ET
#   14:07 PT             after-arming waits for that batch, then verifies both books for the NEXT weekday
#
# It changes no trading setting. Run it from an ordinary shell; -WhatIf shows what it would do.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$Repo = 'C:\Cursor\zargar\.claude\worktrees\technique-review-trade-plan-fbb9ba',
  [string]$InstallDir = 'C:\ProgramData\Zargar'
)
$ErrorActionPreference = 'Stop'
$src = Join-Path $Repo 'scripts\em-session-checks.ps1'
$dst = Join-Path $InstallDir 'em-session-checks.ps1'
if (-not (Test-Path $src)) { throw "missing $src" }
if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null }
if ($PSCmdlet.ShouldProcess($dst, 'install versioned check script')) {
  Copy-Item $src $dst -Force
  Write-Output "installed $dst (from the repository, so it can be reviewed and restored)"
}
# the evening batch and the after-arming check are versioned in the repository too (2026-09-22); the one-off
# per-date copies (em-evening-batch-0922.py, ZargarEmEveningBatch0922 ...) are superseded by these
foreach ($f in 'em-evening-batch.py', 'em-after-arming-check.ps1') {
  $s = Join-Path $Repo "scripts\$f"
  if (-not (Test-Path $s)) { throw "missing $s" }
  if ($PSCmdlet.ShouldProcess((Join-Path $InstallDir $f), 'install versioned script')) { Copy-Item $s (Join-Path $InstallDir $f) -Force }
}

$ps = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$plan = @(
  @{ Name = 'ZargarEmChecksClock';      Phase = 'clock';      At = '06:05' },
  @{ Name = 'ZargarEmChecksPreopen';    Phase = 'preopen';    At = '06:07' },
  @{ Name = 'ZargarEmChecksPostReplan'; Phase = 'postreplan'; At = '06:32' },
  @{ Name = 'ZargarEmChecksExc1';       Phase = 'exceptions'; At = '07:22' },
  @{ Name = 'ZargarEmChecksExc2';       Phase = 'exceptions'; At = '09:41' },
  @{ Name = 'ZargarEmChecksExc3';       Phase = 'exceptions'; At = '11:52' },
  @{ Name = 'ZargarEmChecksClose';      Phase = 'close';      At = '13:37' }
)
foreach ($t in $plan) {
  # No -Date argument: the script defaults to TODAY. That is what makes the task reusable tomorrow.
  $action = New-ScheduledTaskAction -Execute $ps `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Phase {1}' -f $dst, $t.Phase)
  $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $t.At
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
  if ($PSCmdlet.ShouldProcess($t.Name, "register weekday $($t.Phase) at $($t.At)")) {
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings `
      -Description "EM read-only $($t.Phase) check (em-experiment-v1). Changes nothing; writes research files and EM-ATTENTION.md." `
      -Force | Out-Null
    Write-Output ("registered {0,-26} {1,-11} weekdays {2}" -f $t.Name, $t.Phase, $t.At)
  }
}
# ---- the evening pair: the batch can run for hours (one paid read at a time), so it gets a long limit
$py = 'C:\Cursor\zargar\backend\.venv\Scripts\python.exe'
$evening = @(
  @{ Name = 'ZargarEmEveningBatch';  At = '14:05'; Limit = 12; Exec = $py; Arg = ('"{0}"' -f (Join-Path $InstallDir 'em-evening-batch.py')) },
  @{ Name = 'ZargarEmAfterArming';   At = '14:07'; Limit = 12; Exec = $ps;
     Arg = ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -MaxWaitMinutes 660' -f (Join-Path $InstallDir 'em-after-arming-check.ps1')) }
)
foreach ($t in $evening) {
  $action = New-ScheduledTaskAction -Execute $t.Exec -Argument $t.Arg -WorkingDirectory $InstallDir
  $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $t.At
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours $t.Limit)
  if ($PSCmdlet.ShouldProcess($t.Name, "register weekday evening task at $($t.At)")) {
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings `
      -Description 'EM evening preparation (em-evening-batch-v1). Paid review of the baseline book unless techniques.enhanced_market.paid_review is off.' `
      -Force | Out-Null
    Write-Output ("registered {0,-26} evening     weekdays {1}" -f $t.Name, $t.At)
  }
}
Write-Output ''
Write-Output 'Verify with: Get-ScheduledTask ZargarEmChecks* | Get-ScheduledTaskInfo | Format-Table TaskName,LastRunTime,LastTaskResult,NextRunTime'
